# =====================================================================
# FILE: gui/workspace/workspace.py
# =====================================================================
"""
Workspace controlling central tabs and routing double-click actions.
Refactored to meet strict Clean Architecture rules (Dependency Injection implemented).
Fetches high-precision float64 vectors exclusively through the DataAccessor (DAL layer).
Uses DTO configuration objects to stay completely decoupled from UI ribbon elements.
"""

import pyqtgraph as pg
from typing import Any, Dict, List, Optional, Union
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from core.jobs import job_step
from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from core.block_kinds import KIND_ORDER_CUT, resolve_clipped_f_stop
from core.models import resolve_channel_block_kind
from gui.workspace.analysis_tabs import AnalysisTabsMixin
from gui.jobs.qt_job_runner import QtJobRunner
from gui.handlers.companion_curves import CompanionCurvesHandler
from orchestration.dock_tasks import PURPOSE_COMPUTE, DockTasks
from core.evaluation import EvaluationConfig
from core.units import strip_channel_name_prefix
from gui.workspace.open_tabs import OpenTabs
from io_modules.data_accessor import DataAccessor
from io_modules.measurement_files import canonical_path
from session.data_pool import DeadLink, ResolvedTrace
from session.project import channel_label_for
from signal_processing.result_blocks import UnevenRpmAxisError
from view_models.analysis_kinds import (
    ANALYSIS_MODE_PROJECT, ANALYSIS_ORDERS, ANALYSIS_OVERALL_LEVEL, ANALYSIS_SPECTROGRAM, ANALYSIS_SPECTRUM,
    ANALYSIS_TIME, SKIP_CAPACITY, SKIP_IMPORTED, resolve_open_plan, resolve_analysis_kind, resolve_analysis_mode,
    resolve_analysis_mode_of_kind,
)

HOME_TAB_TITLE = "Home Workspace"


def find_dock_by_id(tab_widget, dock_id: str):
    """
    Locates the dock that requested a computation, wherever it sits now.

    Results come back seconds after the request, so the tab the user is
    looking at is not necessarily the one that asked. Returns None when the
    dock has been closed in the meantime, in which case the result is simply
    dropped rather than drawn somewhere it does not belong.

    A module-level function (rather than only a Workspace method) so
    gui.handlers.result_content.ResultContentHandler can be handed a
    dock-lookup callable bound to `main_window.workspace_tabs` before
    Workspace itself exists (ARCHITECTURE_DECISIONS §1.75) -- the tab
    widget is created and never replaced well before Workspace is.
    """
    if not dock_id:
        return None

    for idx in range(tab_widget.count()):
        widget = tab_widget.widget(idx)
        if getattr(widget, "dock_id", None) == dock_id:
            return widget
        # Docks nested inside a container tab still have to be reachable.
        if hasattr(widget, "findChildren"):
            for child in widget.findChildren(QWidget):
                if getattr(child, "dock_id", None) == dock_id:
                    return child
    return None


class Workspace(AnalysisTabsMixin):
    """
    The central tab area as one object: which analysis docks are open, what
    each of them is computing, and where a result that arrives seconds later
    is allowed to land.

    Public interface (#251). Every other method of this class and its
    mixin is internal: callers outside, tests included, drive the names
    below. (How a tab was opened, and what its Save recipe is while it is a
    "Missing" placeholder, is kept by `open_tabs`, not on the dock.)

    Lifecycle
        The composition root builds this after the tab widget and the
        handlers it routes to, then hands over the two collaborators that
        cannot come by constructor because they are built *from* this object:
        `bind_evaluation_panel`, `bind_workspace_layout` (§1.74/§1.75). Both
        are optional -- a window without them leaves the matching calls
        no-ops -- but neither may be bound twice.

    Open and refresh a dock
        `open_acc_spectrum_tab`, `open_acc_spectrogram_tab`,
        `open_acc_order_tracking_tab`, `open_acc_overall_level_tab`,
        `open_specific_channel_tab`, `open_multi_channel_overlay_tab` open
        one; `open_channels_tab` picks between the last two for a Data Pool
        selection; `show_home_tab` puts the placeholder back when no tab is
        open. `refresh_active_spectrum`, `refresh_active_spectrogram`,
        `refresh_active_order_tracking`, `refresh_active_overall_level`,
        `refresh_last_n_curves` recompute the tab in front.
        `build_shell` makes an empty dock and `dispatch_compute` starts (or
        restarts) its computation -- the pair a restore drives directly.

    Receive a result
        `plot_frequency_block`, `plot_spectrogram_block`, `plot_order_cuts`,
        `plot_overall_level_block`, `report_computation_failure`: the Qt slots
        `SpectralRequests`' signals connect to. Each takes a `widget_tag`
        (a `dock_id`) rather than a dock, and drops the result without a word
        when no open dock carries that id.

    Ask about the docks
        `find_dock_by_id`, `open_dock_ids`, `route_channel_drop`.

    Session and settings
        `capture_open_tabs_spec`, `persist_open_tabs`, `restore_open_tabs`
        (S6/S7), `rebuild_active_dock_display_settings`,
        `apply_graph_performance_settings`, `replot_time_docks_for_unit_change`,
        `toggle_band_rms_cursors`, `close_all_tabs`, `close_specific_tab`.

    Thread affinity
        Every method here is called on the GUI thread and touches widgets, so
        nothing on this class may be called from a worker. The one hop out is
        `dock_tasks` (`orchestration.dock_tasks.DockTasks` over the
        QtJobRunner): it runs a read on the interactive lane and applies the
        result back on the GUI thread, dropping it if the dock was closed or a
        newer task with the same purpose for the same dock has since started. DSP computation
        leaves by `SpectralRequests` and comes back as a Qt signal into the
        `plot_*` slots above.

    Callback ordering
        A fresh open is `build_shell` then `dispatch_compute` -- the dock
        exists, and is in the tab widget, before anything is computed for it,
        because that is what lets a late result find it by id. A restore adds
        the base curve first and re-drops the saved overlays only once it has
        landed.

    Error modes
        These methods do not raise for a condition the user can cause: a
        missing tacho, a dead link in a saved recipe, a read that fails, a
        ribbon action on the wrong kind of tab all log through
        `app_context.log` and leave something to look at -- a fresh open drops
        its own tab (a restored one whose read fails stays a "Missing"
        placeholder, `OpenTabs.drop_unreadable_fresh_open`), a refresh keeps the plot it already had
        (`_abort_refresh`). A `TypeError` from a wrong call *is* raised: it is
        a programming mistake, not a data problem.

    Test seam
        Tests build a real instance through this constructor and drive the
        names above. `tests/workspace_harness.py` is the only place allowed to
        substitute the background hop (see its module docstring).
    """

    def __init__(self, app_context, tab_widget: QTabWidget, *,
                 placeholder_graph=None,
                 filter_panel=None,
                 job_manager=None,
                 spectral_requests=None,
                 live_drop_handler=None,
                 result_content_handler=None,
                 # gui.handlers.filter_routing.FilterRoutingHandler
                 # (#234, ARCHITECTURE_DECISIONS §1.76), built by the
                 # composition root before this manager so it can be handed
                 # over by constructor. None in a window with no Filter panel
                 # and in tests that do not drive the mask -- both leave the
                 # three call sites below as no-ops.
                 filter_routing=None):
        self.app_context = app_context
        self.tabs = tab_widget
        # The Home Workspace tab: never an analysis dock, so every loop over
        # `self.tabs` that means "the docks the user opened" skips it. None in
        # tests that build a bare tab widget with no placeholder in it.
        self.placeholder_graph = placeholder_graph
        # gui.filter_panel.filter_panel.FilterPanel. None in a window with no
        # Filter panel and in the routing tests, which never drive the mask --
        # the same reason `filter_routing` below is None-able.
        self.filter_panel = filter_panel
        # gui.jobs.qt_job_runner.QtJobRunner: the workspace restore and every
        # dock task run on it. The window always hands its own over; a
        # workspace built without one (tests over a bare tab widget) gets a
        # private queue rather than None, so its reads still leave the GUI
        # thread the way the application's do.
        self.job_manager = job_manager if job_manager is not None else QtJobRunner(app_context)
        # Every dock's background read goes through here (ADR §1.84): one
        # answer to "is this result still wanted?" for the whole workspace.
        self.dock_tasks = DockTasks(
            self.job_manager, is_open=lambda dock_id: self.find_dock_by_id(dock_id) is not None)
        self.companion_curves = CompanionCurvesHandler(
            app_context, self.dock_tasks, self.route_channel_drop)
        # gui.workspace.spectral_requests.SpectralRequests: every 1D/2D
        # computation this manager and the channel drops ask for goes through
        # it, and a closed dock's generation counter is dropped on it.
        self.spectral_requests = spectral_requests
        # gui.handlers.live_channel_drop.LiveChannelDropHandler, handed
        # straight on to `execute_channel_drop_processing` for result-content
        # docks (ARCHITECTURE_DECISIONS §1.30).
        # Same name as the window's own attribute -- one thing, one name.
        self.live_drop_handler = live_drop_handler
        self.result_content_handler = result_content_handler
        self.filter_routing = filter_routing
        # Save / restore of the tab set and the per-dock state they share.
        self.open_tabs = OpenTabs(self)
        # Bound after construction rather than by constructor: both are built
        # from this manager (EvaluationPanel takes it, WorkspaceLayout takes
        # that panel), so neither can exist yet -- see bind_evaluation_panel
        # and bind_workspace_layout.
        self.evaluation_panel = None
        self.cursor_switch = None
        self.highlight_switch = None
        self.pin_switch = None
        self.workspace_layout = None
        # The placeholder is a GraphDock, so it accepts a channel drag like any
        # dock -- but it is no place to keep curves (capture_open_tabs_spec
        # skips it). A drop on it opens a tab the way a double click would.
        self.selection_drops = None
        if placeholder_graph is not None:
            placeholder_graph.sig_channels_dropped.connect(self._open_dropped_on_home_tab)
            placeholder_graph.sig_selection_dropped.connect(lambda name: self.draw_selection(name))

    def bind_selection_drops(self, handler) -> None:
        """Hands over the Selection drop handler, which is made from this manager (#465)."""
        self.selection_drops = handler

    def draw_selection(self, name: str, dock=None) -> None:
        """Draw Selection `name` on `dock`, or in a new tab when `dock` is None."""
        if self.selection_drops is not None:
            self.selection_drops.draw(name, dock)

    def bind_evaluation_panel(self, panel) -> None:
        """
        Hands over the Evaluation card once it exists.

        It cannot come by constructor: EvaluationPanel takes this manager by
        constructor itself (it runs its reads through `dock_tasks`), so
        the manager is necessarily the older of the two. Same `bind_*` shape
        UnvChannelExplorer.bind_workspace uses for the mirror-image case
        (#241).
        """
        self.evaluation_panel = panel

    def bind_workspace_layout(self, layout) -> None:
        """
        Hands over the dock layout once it exists, so closing a tab can save
        the arrangement. Built after this manager for the same reason
        `bind_evaluation_panel` exists: WorkspaceLayout is assembled from the
        panels -- the Evaluation card among them -- that are made from this
        manager.
        """
        self.workspace_layout = layout

    def bind_cursor_switch(self, button) -> None:
        """Hands over the Tools tab's Cursor button, the one owner of the on/off state."""
        self.cursor_switch = button
        button.setChecked(self.app_context.cursor_enabled)
        button.toggled.connect(self.set_cursor_enabled)

    def set_cursor_enabled(self, enabled: bool) -> None:
        """The Cursor is one app-level flag for every graph; off hides every open box."""
        self.app_context.cursor_enabled = bool(enabled)
        self.app_context.remember_tool_flag("cursor_enabled", enabled)
        if not enabled:
            for idx in range(self.tabs.count()):
                dock = self.tabs.widget(idx)
                if hasattr(dock, "hide_cursor_box"):
                    dock.hide_cursor_box()

    def open_cursor_settings(self) -> None:
        """Cursor Settings: the field list is global, so it is saved on OK, not into the project."""
        from gui.dialogs.cursor_settings_dialog import CursorSettingsDialog
        ctx = self.app_context
        dialog = CursorSettingsDialog(
            ctx.pool.schema().master, ctx.cursor_config, self.tabs.window(),
            settings=getattr(ctx, "settings", None), other_opacity=ctx.highlight_other_opacity)
        try:
            if dialog.exec():
                ctx.set_cursor_config(dialog.result_config())
                ctx.set_highlight_other_opacity(dialog.result_other_opacity())
        finally:
            dialog.deleteLater()

    def bind_pin_switch(self, button) -> None:
        """Hands over the Tools tab's Pin button, the one owner of the pinned state."""
        self.pin_switch = button
        button.setChecked(self.app_context.cursor_pinned)
        button.toggled.connect(self.set_cursor_pinned)

    def set_cursor_pinned(self, pinned: bool) -> None:
        """Pin is one app-level flag; unpinning hides the boxes so they reappear at the mouse."""
        self.app_context.cursor_pinned = bool(pinned)
        self.app_context.remember_tool_flag("cursor_pinned", pinned)
        if not pinned:
            for idx in range(self.tabs.count()):
                dock = self.tabs.widget(idx)
                if hasattr(dock, "hide_cursor_box"):
                    dock.hide_cursor_box()

    def toggle_cursor_pin(self) -> None:
        """The `P` shortcut: flips the ribbon button, which carries the state."""
        switch = self.pin_switch
        if switch is not None:
            switch.toggle()
        else:
            self.set_cursor_pinned(not self.app_context.cursor_pinned)

    def bind_highlight_switch(self, button) -> None:
        """Hands over the Tools tab's Highlight button, the one owner of the on/off state."""
        self.highlight_switch = button
        button.setChecked(self.app_context.highlight_enabled)
        button.toggled.connect(self.set_highlight_enabled)

    def set_highlight_enabled(self, enabled: bool) -> None:
        """Highlight is one app-level flag for every graph; off restores every open graph's pens."""
        self.app_context.highlight_enabled = bool(enabled)
        self.app_context.remember_tool_flag("highlight_enabled", enabled)
        if not enabled:
            for idx in range(self.tabs.count()):
                dock = self.tabs.widget(idx)
                if hasattr(dock, "clear_highlight"):
                    dock.clear_highlight()

    def toggle_highlight(self) -> None:
        """The `H` shortcut: flips the ribbon button, which carries the state."""
        switch = self.highlight_switch
        if switch is not None:
            switch.toggle()
        else:
            self.set_highlight_enabled(not self.app_context.highlight_enabled)

    def toggle_cursor(self) -> None:
        """The `C` shortcut: flips the ribbon button, which carries the state."""
        switch = self.cursor_switch
        if switch is not None:
            switch.toggle()
        else:
            self.set_cursor_enabled(not self.app_context.cursor_enabled)

    def find_dock_by_id(self, dock_id: str):
        """Delegates to the module-level `find_dock_by_id` (see its docstring),
        bound to this instance's own tab widget."""
        return find_dock_by_id(self.tabs, dock_id)

    def open_dock_ids(self) -> set:
        """Every currently open tab's `dock_id` (skipping tabs that have none,
        e.g. the startup placeholder) -- callers that need to reconcile
        dock ids against saved state, like the Filter panel's orphan-card
        prune (§1.37, §1.94)."""
        ids = set()
        for idx in range(self.tabs.count()):
            dock_id = getattr(self.tabs.widget(idx), "dock_id", None)
            if dock_id:
                ids.add(dock_id)
        return ids

    def _mark_project_dirty(self) -> None:
        """
        Records that an open tab was added or removed since the last Save.

        getattr guards the lightweight StubContext several dock-routing tests
        substitute for a real AppContext -- those tests care about routing,
        not the project's dirty flag, and never set up a project_session.
        """
        session = getattr(self.app_context, "project_session", None)
        if session is not None:
            session.mark_dirty()

    def _remove_dock_tab(self, dock) -> None:
        """
        Drops a fresh dock's tab that never opened, looked up fresh so a stale
        captured index never removes the wrong tab. The Home Workspace comes
        back when this was the last tab, or the workspace would accept no drop.
        """
        idx = self.tabs.indexOf(dock)
        if idx != -1:
            self.tabs.removeTab(idx)
            dock.deleteLater()
        if self.tabs.count() == 0:
            self.show_home_tab()

    def _require_active_dock(self, analysis_kind: str, action_label: str) -> Optional[Union[GraphDock, SpectrogramDock]]:
        """
        Returns the current tab only when it is the kind of analysis this ribbon
        button acts on, and logs a usable reason when it is not.

        The refresh handlers used to accept any GraphDock carrying a run_index --
        which a spectrum tab and an order tab both do -- so pressing "Extract
        Order Cuts" while a spectrum was in front tried to run order tracking on
        it and failed further downstream on a missing tacho.
        """
        widget = self.tabs.currentWidget()
        actual = getattr(widget, "analysis_kind", None)

        if actual != analysis_kind:
            self.app_context.log(
                f"WARNING: {action_label} needs an active {analysis_kind} tab "
                f"(current tab is '{actual or 'empty'}')."
            )
            return None

        if not isinstance(widget, (GraphDock, SpectrogramDock)) or widget.run_index is None:
            self.app_context.log(f"WARNING: This tab has no source channel to recompute.")
            return None

        return widget

    def route_channel_drop(self, dock_instance, raw_descriptors, batch_label=None, *, mark_dirty=True) -> bool:
        """
        The one place that knows what `execute_channel_drop_processing` needs.

        An accepted drop changes what capture_open_tabs_spec writes on the next
        Save, so it marks the project dirty -- except a re-drop of curves the
        graph already had (a restore or a refresh, `mark_dirty=False`).

        Three of its arguments are collaborators this manager holds and the
        drop router does not (#242); binding them here means a fourth one is
        added in one place rather than at every site that routes a drop --
        the dock's own drop signal, a restored dock's pending overlays, and
        AnalysisTabsMixin.refresh_last_n_curves.
        """
        from gui.file_explorer.actions.channel_drop import execute_channel_drop_processing
        accepted = execute_channel_drop_processing(
            dock_instance=dock_instance,
            raw_descriptors=raw_descriptors,
            app_context=self.app_context,
            workspace=self,
            spectral_requests=self.spectral_requests,
            live_drop_handler=self.live_drop_handler,
            batch_label=batch_label,
        )
        if accepted and mark_dirty:
            self._mark_project_dirty()
        return accepted

    def show_home_tab(self) -> None:
        """
        Puts the Home Workspace placeholder back when no tab is open.

        An empty tab widget accepts no drop at all, so the workspace is never
        left without it: the window shows it at startup and closing the last
        dock brings it back. It carries no close button -- closing it would
        leave exactly that empty widget behind.
        """
        placeholder = self.placeholder_graph
        if placeholder is None or self.tabs.indexOf(placeholder) != -1:
            return
        index = self.tabs.addTab(placeholder, HOME_TAB_TITLE)
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)

    def open_channels_tab(self, channels: list, what=None) -> None:
        """
        Opens the tab a set of channels gets from the Data Pool -- a double
        click on its rows or a drop on the Home Workspace.

        `channels` holds `(run_index, channel_meta, label)` rows. One channel
        opens the active Analysis mode's own tab; several open one comparison
        tab of that mode's Analysis kind holding what the channels opened one
        by one would -- except the Spectrogram, which opens the first channel
        and logs the rest. Imported order cuts alone open in Order Tracking;
        mixed with other channels they never switch the active mode -- outside
        Order Tracking they are skipped (#509). `resolve_open_plan` decides.
        """
        if not channels:
            return
        analysis_mode = resolve_analysis_mode(getattr(self.app_context, "current_analysis_mode", ANALYSIS_MODE_PROJECT))
        plan = resolve_open_plan(channels, analysis_mode)
        imported = [row for row, reason in plan.skipped if reason == SKIP_IMPORTED]
        if imported:
            self.app_context.log(f"WARN: {len(imported)} imported result channel(s) skipped; "
                                 f"they open only in Order Tracking mode.")
        over_capacity = [row[2] for row, reason in plan.skipped if reason == SKIP_CAPACITY]
        if over_capacity:
            kind = resolve_analysis_kind(plan.analysis_kind)
            self.app_context.log(f"WARN: {kind.display_name} holds {kind.max_channels} channel(s); "
                                 f"not opened: {', '.join(over_capacity)}.")
        if plan.is_comparison:
            self.open_multi_channel_overlay_tab(plan.rows, what=what, analysis_kind=plan.analysis_kind)
        else:
            run_index, channel_meta, _ = plan.rows[0]
            self.open_specific_channel_tab(run_index, channel_meta)

    def open_multi_channel_overlay_tab(self, rows: list, what=None, *, analysis_kind: str) -> None:
        """
        One comparison tab: an empty dock of `analysis_kind` that takes `rows`
        through the channel drop, so it holds what the same channels opened
        one by one would. `what` names the drawn set in the job label, e.g.
        "Selection 'X'" (#469). A tab nothing could be loaded into closes
        again with the reason in the log.
        """
        from gui.file_explorer.actions.channel_drop import build_channel_descriptors

        self._drop_home_tab()
        dock = GraphDock(app_context=self.app_context)
        dock.analysis_kind = analysis_kind
        self._connect_dock_signals(dock)
        # T4: same reasoning as build_shell -- a Global filter's selection
        # already exists project-wide, so this fresh dock should not have to
        # wait for a tab switch to pick it up.
        if self.filter_routing is not None:
            self.filter_routing.apply_active_filter_to_dock(dock)
        self.tabs.setCurrentIndex(self.tabs.addTab(dock, f"Compare: {len(rows)} Channels"))
        dock.plot_widget.setTitle("⏳ Loading...")

        kind = resolve_analysis_kind(analysis_kind)
        label = f"{'Load' if analysis_kind == ANALYSIS_TIME else kind.display_name} — {what or f'{len(rows)} channels'}"
        if not self.route_channel_drop(dock, build_channel_descriptors(rows), batch_label=label):
            self.app_context.log(f"WARN: No channel could be loaded into the {kind.display_name} comparison tab; "
                                 f"tab closed.")
            self._remove_dock_tab(dock)

    def _open_dropped_on_home_tab(self, raw_descriptors: list) -> None:
        from gui.file_explorer.actions.channel_drop import resolve_dropped_channels
        self.open_channels_tab(resolve_dropped_channels(raw_descriptors, self.app_context))

    def _drop_home_tab(self):
        """Removes the lone "Home Workspace" placeholder before the first real dock opens."""
        placeholder = self.placeholder_graph
        if placeholder is not None:
            index = self.tabs.indexOf(placeholder)
            if index != -1:
                self.tabs.removeTab(index)
        elif self.tabs.count() == 1 and self.tabs.tabText(0) == HOME_TAB_TITLE:
            self.tabs.removeTab(0)

    def _connect_dock_signals(self, dock_instance):
        """Binds the UI dock drop events to the central drop action router."""
        if hasattr(dock_instance, 'sig_channels_dropped'):
            dock_instance.sig_channels_dropped.connect(
                lambda payload, d=dock_instance: self.route_channel_drop(d, payload)
            )
        if hasattr(dock_instance, 'sig_cursor_toggle_requested'):
            dock_instance.sig_cursor_toggle_requested.connect(self.toggle_cursor)
        if hasattr(dock_instance, 'sig_cursor_pin_requested'):
            dock_instance.sig_cursor_pin_requested.connect(self.toggle_cursor_pin)
        if hasattr(dock_instance, 'sig_highlight_toggle_requested'):
            dock_instance.sig_highlight_toggle_requested.connect(self.toggle_highlight)
        if hasattr(dock_instance, 'sig_selection_dropped'):
            dock_instance.sig_selection_dropped.connect(
                lambda name, d=dock_instance: self.draw_selection(name, d)
            )
        if hasattr(dock_instance, 'sig_first_trace_rendered'):
            dock_instance.sig_first_trace_rendered.connect(
                lambda d=dock_instance: self._reapply_filter_for_dock(d)
            )
        if hasattr(dock_instance, 'sig_trace_added'):
            dock_instance.sig_trace_added.connect(
                lambda d=dock_instance: self._reapply_filter_for_dock(d)
            )
        if hasattr(dock_instance, 'sig_content_or_mask_changed'):
            dock_instance.sig_content_or_mask_changed.connect(
                lambda d=dock_instance: self.companion_curves.handle_curves_added(d)
            )
            dock_instance.sig_content_or_mask_changed.connect(
                lambda d=dock_instance: self._notify_evaluation_panel(d)
            )

    def _notify_evaluation_panel(self, dock) -> None:
        """
        Consumer of GraphDock.sig_content_or_mask_changed (issue #136): the
        Evaluation card ignores this unless `dock` is the one it is showing
        (EvaluationPanel.on_dock_content_changed does that check itself).

        None-guarded the same way `_mark_project_dirty` guards
        `project_session` -- the routing tests build this manager without an
        Evaluation card at all, and they render/overlay docks without caring
        about it.
        """
        panel = self.evaluation_panel
        if panel is not None:
            panel.on_dock_content_changed(dock)

    def _reapply_filter_for_dock(self, dock) -> None:
        """
        Consumer of both GraphDock.sig_first_trace_rendered and
        GraphDock.sig_trace_added: a Local filter's Channel facet is built
        from the focused dock's own traces
        (FilterRoutingHandler.refresh_filter_panel), which build_shell/tab-focus
        already routes through apply_active_filter_to_dock once -- but that
        one pass misses two later moments the trace list itself changes:

        - a freshly opened dock's model is still None at build/focus time
          (the background read/DSP hasn't landed yet), so the facet came back
          empty and populate_facets' "default to everything on offer"
          heuristic (BUGS.md K1) had nothing to default to, leaving the base
          curve rendered hidden ("Filter hid 1 of 1 curves") the instant real
          data arrived (sig_first_trace_rendered);
        - a second/third channel dropped onto a dock that already has focus
          (add_curve) changes what the Channel facet should
          offer, but nothing was re-running the focus routing for it -- the
          panel stayed stuck on the old trace count until an unrelated
          refresh (Configure Filters' Apply, a tab switch) happened to catch
          it up (sig_trace_added).

        Re-running the same focus routing now that the trace list has moved
        on gives the heuristic (or an existing selection) a real, current
        facet to work from either way.

        No-op unless this dock still has focus: a dock that lost focus before
        its data arrived, or before the drop landed, gets the same catch-up
        for free the next time it regains focus (dock_focus_changed
        already handles that case).
        """
        if self.tabs.currentWidget() is not dock or self.filter_routing is None:
            return
        self.filter_routing.dock_focus_changed(dock)

    def build_shell(
        self,
        analysis_kind: str,
        resolved: Union[ResolvedTrace, DeadLink],
        evaluation_config: Optional[EvaluationConfig] = None,
        dock_id: Optional[str] = None,
    ):
        """
        Creates the tab + dock for `analysis_kind` and stamps run_index/
        channel_meta onto it when `resolved` is live -- but never starts a
        background read (that is dispatch_compute's job, called right after
        by every caller below). Split out so a fresh double-click and a
        future restore (S6) go through the exact same branch: a double-click
        already has a live (run_index, channel_meta) pair and wraps it in a
        ResolvedTrace inline; restore hands whatever tab_spec_resolver.
        resolve_trace returned it, dead links included
        (ideas/session_persistence/PLAN.md S3/S4/S6).

        `analysis_kind` is TabSpec's vocabulary ("time" | "spectrum" |
        "orders" | "overall_level" | "spectrogram") and the same value
        ends up on `dock.analysis_kind`; a SpectrogramDock sets its own
        "spectrogram" in its constructor.

        A DeadLink produces an empty, titled dock and a log line, never a
        crash -- the file or channel a saved recipe pointed at may be gone
        by the time the project reopens. Callers must not call
        dispatch_compute on the result in that case; there is nothing to
        compute it from.

        `dock_id` is the id a restored dock was saved with (ADR §1.94): the
        dock takes it back, so a custom Local filter card owned by it still
        finds it. An id some open dock already holds is ignored and the dock
        keeps its fresh one -- two docks never share an id.
        """
        self._drop_home_tab()

        if analysis_kind == ANALYSIS_SPECTROGRAM:
            dock = SpectrogramDock(app_context=self.app_context)
        else:
            dock = GraphDock(app_context=self.app_context)
            dock.analysis_kind = analysis_kind
        if dock_id and self.find_dock_by_id(dock_id) is None:
            dock.dock_id = dock_id
        if evaluation_config is not None:
            dock.evaluation_config = evaluation_config
        self._connect_dock_signals(dock)
        # T4: a freshly opened dock starts under whatever filter is already
        # active -- most visibly a Global one, whose selection is already
        # populated project-wide and does not depend on this dock's own
        # (still empty) traces the way a Local one would. Without this the
        # dock ignored the filter until the user switched tabs away and back.
        if self.filter_routing is not None:
            self.filter_routing.apply_active_filter_to_dock(dock)

        if isinstance(resolved, DeadLink):
            # Kept on the dock (not just logged) so a save made while the file
            # is still missing does not drop this recipe from ui_state --
            # capture_open_tabs_spec reads it back when dock.run_index is None
            # (S5/PLAN.md S6 "Zastaraný súbor"). The file may simply be on an
            # unmounted drive this session; without this, restoring once would
            # be the last time it is ever tried again.
            self.open_tabs.mark_dead_link(dock, resolved)
            tab_idx = self.tabs.addTab(dock, f"⚠ Missing: {resolved.channel_name}")
            self.tabs.setCurrentIndex(tab_idx)
            self.app_context.log(
                f"WARNING: could not restore '{resolved.channel_name}' ({resolved.reason})."
            )
            return dock

        dock.run_index = resolved.run_index
        dock.channel_meta = resolved.channel_meta
        clean_name = strip_channel_name_prefix(resolved.channel_meta.name)
        title = f"{resolve_analysis_kind(analysis_kind).title_prefix}{resolved.run_index.file_name} [{clean_name}]"
        tab_idx = self.tabs.addTab(dock, title)
        self.tabs.setCurrentIndex(tab_idx)
        return dock

    def dispatch_compute(self, dock, *, is_fresh_open: bool) -> None:
        """
        Starts (or restarts) the background read + DSP compute for `dock`,
        branching on `dock.analysis_kind` -- the one property that already
        tells docks apart everywhere else in this file. A fresh open
        (build_shell just built `dock`, is_fresh_open=True) and a ribbon
        Refresh (dock already has a run_index, is_fresh_open=False) both
        call this; only the failure path differs (a fresh open with nothing
        on screen yet drops the tab, a refresh leaves the existing plot in
        place -- see _abort_refresh).

        `is_fresh_open` is what today's open_acc_*_tab / refresh_active_*
        pairs each hard-coded into two near-duplicate function bodies; the
        per-kind bodies now live once each in the shared
        `_dispatch_compute` method.

        No request/response object of its own on purpose: there is exactly
        one thing being computed here, this dock's own base trace, so a
        wrapper type would only mirror attributes `dock` already carries.
        """
        if (dock.analysis_kind == ANALYSIS_TIME or
                (dock.channel_meta is not None
                 and resolve_channel_block_kind(dock.channel_meta) == KIND_ORDER_CUT)):
            self._dispatch_compute_time(dock)
        else:
            self._dispatch_compute(dock, dock.analysis_kind, is_fresh_open=is_fresh_open)

    def capture_open_tabs_spec(self) -> List[Dict[str, Any]]:
        """`self.tabs` -> one `TabSpec` dict per live analytical dock (see `OpenTabs.capture`)."""
        return self.open_tabs.capture()

    def persist_open_tabs(self) -> None:
        """Writes the current tab set into the project's `ui_state` (see `OpenTabs.persist`)."""
        self.open_tabs.persist()

    def restore_open_tabs(self) -> None:
        """Rebuilds every dock the project's `ui_state` recorded (see `OpenTabs.restore`)."""
        self.open_tabs.restore()

    def open_specific_channel_tab(self, run_index, channel_meta):
        if resolve_channel_block_kind(channel_meta) == KIND_ORDER_CUT:
            dock = self.build_shell(ANALYSIS_ORDERS, ResolvedTrace(run_index, channel_meta))
            self._mark_project_dirty()
            self.dispatch_compute(dock, is_fresh_open=True)
            return
        open_by_kind = {
            ANALYSIS_SPECTROGRAM: self.open_acc_spectrogram_tab,
            ANALYSIS_SPECTRUM: self.open_acc_spectrum_tab,
            ANALYSIS_ORDERS: self.open_acc_order_tracking_tab,
            ANALYSIS_OVERALL_LEVEL: self.open_acc_overall_level_tab,
        }
        analysis_mode = resolve_analysis_mode(getattr(self.app_context, "current_analysis_mode", ANALYSIS_MODE_PROJECT))
        open_tab = open_by_kind.get(analysis_mode.analysis_kind)
        if open_tab is not None:
            open_tab(run_index, channel_meta)
            return

        dock = self.build_shell(ANALYSIS_TIME, ResolvedTrace(run_index, channel_meta))
        self._mark_project_dirty()  # see AnalysisTabsMixin.open_acc_spectrum_tab
        self.dispatch_compute(dock, is_fresh_open=True)

    def _dispatch_compute_time(self, dock) -> None:
        # Waveforms and Imported results both need only a background read.
        dock.plot_widget.setTitle("⏳ Loading...")

        def _on_loaded(data_block):
            dock.plot_blocks([data_block])
            # A restored tab (S7) may carry overlays dropped onto it in a
            # previous session -- same consumer `refresh_active_spectrum`
            # feeds, just reached from a fresh open here instead of a
            # refresh (a time dock has none of its own, see this method's
            # opening comment).
            self._restore_pending_overlays(dock)

        def _on_failed(message):
            self.app_context.log(f"ERROR: IO block read exception: {message}")
            self.open_tabs.drop_unreadable_fresh_open(dock)

        self.dock_tasks.run(
            dock.dock_id, DataAccessor.fetch_channel_data, dock.run_index, dock.channel_meta,
            purpose=PURPOSE_COMPUTE, on_success=_on_loaded, on_error=_on_failed,
        )

    # =========================================================================
    # PLOTTING CALLBACKS & CLEANUP
    # =========================================================================
    def plot_frequency_block(self, widget_tag: str, block):
        target = self.find_dock_by_id(widget_tag)
        if target is None:
            return
        if isinstance(target, GraphDock):
            target.plot_blocks([block])
            self._apply_band_rms_preference(target)
            self._restore_pending_overlays(target)

    def _restore_pending_overlays(self, target) -> None:
        """
        Gives back what the dock's `GraphCurves` still has pending as its
        base curve landed: the overlays and result sets captured just before
        the reset (`capture_overlays_before_reset`, started by a Refresh in
        `gui/workspace/analysis_tabs.py`) and a reopened tab's saved overlays
        and result sets (`restore_open_tabs`). This stays a workspace.py
        method because its callers (`plot_frequency_block`,
        `plot_order_cuts`, `plot_overall_level_block`, the time read) are
        plot-callback machinery, not analysis-specific.

        Overlays are routed through the exact same channel-drop entry point
        a real drag uses, rather than duplicating its read/compute/overlay
        logic here. A fresh open has `NOTHING_PENDING` and is left alone
        rather than having its title stomped to "Compare: 1 Channels"; a
        Refresh with nothing to re-drop only has its tab title catch up.

        Saved result-set ids (S5/plan F5) go through the same
        `ResultContentHandler.load_into_dock` a live "Load Result Sets..." click uses,
        so a restored dock's h5 content comes back through the one reading
        path rather than a second one built for restore alone.
        """
        if not isinstance(target, GraphDock):
            return
        restore = target.curves.take_pending_restore()

        # Result sets first: queueing their read marks them pending, which is
        # what a re-dropped channel reads its Parameter Set from
        # (LiveChannelDropHandler._resolve_drop_config).
        if restore.result_set_ids and self.result_content_handler is not None:
            self.result_content_handler.load_into_dock(target, list(restore.result_set_ids))

        if restore.overlays:
            self.route_channel_drop(target, list(restore.overlays), mark_dirty=False)
        elif restore.from_refresh:
            from gui.handlers.dock_tab_title import update_dock_tab_title
            update_dock_tab_title(target)

    def _band_rms_is_requested(self) -> bool:
        return bool(getattr(self.app_context, "band_rms_cursors_enabled", False))

    def _apply_band_rms_preference(self, dock):
        """Applies the ribbon's cursor preference to a freshly plotted spectrum."""
        if hasattr(dock, "set_band_rms_cursors"):
            dock.set_band_rms_cursors(self._band_rms_is_requested())

    def toggle_band_rms_cursors(self, enabled: bool):
        """Ribbon checkbox handler: acts on the tab currently in front."""
        widget = self.tabs.currentWidget()
        if not hasattr(widget, "set_band_rms_cursors"):
            if enabled:
                self.app_context.log("WARNING: Band RMS cursors need an active spectrum tab.")
            return

        if widget.set_band_rms_cursors(enabled):
            self.app_context.log("SYSTEM: Drag the band edges to set the Band RMS range.")
        elif enabled:
            self.app_context.log(
                "WARNING: Band RMS is only defined for a spectrum. "
                "Open a 1D Spectrum tab first."
            )

    def plot_spectrogram_block(self, widget_tag: str, block):
        target = self.find_dock_by_id(widget_tag)
        if not isinstance(target, SpectrogramDock):
            return

        spec_settings = getattr(getattr(self, "app_context", None), "spectrogram_settings", None)
        try:
            target.spectrogram.show_block(
                block,
                color_scale=getattr(spec_settings, "color_scale", "Linear"),
                spectrum_format=getattr(spec_settings, "spectrum_format", "linear"),
                amplitude_mode=getattr(spec_settings, "amplitude_mode", "rms"),
            )
        except UnevenRpmAxisError as error:
            # An rpm axis the image cannot draw truthfully (#434); the dock keeps
            # whatever it showed and its title says this block did not land.
            self.report_computation_failure(widget_tag, str(error))

    def plot_order_cuts(self, widget_tag: str, blocks: list):
        target = self.find_dock_by_id(widget_tag)
        if not isinstance(target, GraphDock) or not blocks:
            return

        target.plot_blocks(blocks)

        self._restore_pending_overlays(target)

    def plot_overall_level_block(self, widget_tag: str, block):
        target = self.find_dock_by_id(widget_tag)
        if not isinstance(target, GraphDock):
            return

        # A successful compute means this dock's failure state (see
        # report_computation_failure) no longer applies.
        self.open_tabs.finish_compute(target)

        target.plot_blocks([block])

        self._log_overall_level_band_clamp(block)
        self._restore_pending_overlays(target)

    def _log_overall_level_band_clamp(self, block) -> None:
        """
        One log line when the requested F max was clipped to the file's
        Nyquist (ADR §1.62 point 9) -- called once per compute, from the one
        place a freshly computed Overall Level block lands.
        """
        clipped = resolve_clipped_f_stop(block)
        if clipped is not None:
            requested, effective = clipped
            self.app_context.log(
                f"WORKSPACE: Overall Level F max clipped from {requested:g} Hz "
                f"to {effective:g} Hz (file's Nyquist)."
            )

    def rebuild_active_dock_display_settings(self, expected_kind: Optional[str] = None) -> None:
        """
        Instantly re-scales the active dock's display format / amplitude / scale (< 1 ms),
        without background worker jobs or DSP recomputation (ADR §1.60).

        Which settings are passed is the dock's Block kind's
        `display_only_params`, read through its Analysis kind (ADR §1.87);
        a setting the ribbon's config does not carry is left to the dock's
        own fallback.
        """
        dock = self.tabs.currentWidget()
        if not isinstance(dock, (GraphDock, SpectrogramDock)):
            return
        if expected_kind is not None and dock.analysis_kind != expected_kind:
            return

        analysis_kind = resolve_analysis_kind(dock.analysis_kind)
        if not analysis_kind.display_only_params:
            return
        settings = getattr(getattr(self, "app_context", None),
                           resolve_analysis_mode_of_kind(analysis_kind.name).settings_name, None)
        dock.rebuild_with_display_settings(**{
            param: getattr(settings, param)
            for param in analysis_kind.display_only_params
            if hasattr(settings, param)
        })

    def report_computation_failure(self, widget_tag: str, message: str):
        """
        Surfaces a failed computation on the dock that asked for it, so the
        placeholder title does not sit there implying work is still in progress.
        """
        self.app_context.log(f"ERROR [{widget_tag}]: {message}")
        target = self.find_dock_by_id(widget_tag)
        if target is None or not hasattr(target, "plot_widget"):
            return
        if isinstance(target, GraphDock):
            # The recompute will not land -- see AnalysisTabsMixin._abort_refresh.
            target.curves.abort_restore()

        # Overall Level is the one kind where an open-time failure (e.g. an
        # empty band on this file) must drop the empty tab, while a refresh
        # failure must leave the existing plot in place -- see
        # _dispatch_compute, which stamps this before dispatching.
        is_fresh_open = self.open_tabs.finish_compute(target)
        if is_fresh_open is not None:
            if is_fresh_open:
                self._remove_dock_tab(target)
            else:
                target.plot_widget.setTitle("Overall Level interrupted - see System Log")
            return

        target.plot_widget.setTitle("Computation failed - see System Log")

    def apply_graph_performance_settings(self) -> None:
        """
        Pushes the ribbon's decimation / clip-to-view preferences onto the
        curves of every open dock.

        Lives here so the graph layer keeps a single place that walks the open
        docks and reaches into their PlotDataItems -- open_graph_settings used
        to run this loop inline against main_window.workspace_tabs, a second
        dock-touching path outside the plot_* routing.
        """
        ctx = self.app_context
        if not ctx.perf_downsample_enabled:
            ds_value = 1
        elif ctx.perf_auto_mode_active:
            ds_value = True
        else:
            ds_value = ctx.perf_manual_factor
        auto = ctx.perf_auto_mode_active and ctx.perf_downsample_enabled
        clip = ctx.perf_render_screen_only

        for idx in range(self.tabs.count()):
            sheet = self.tabs.widget(idx)
            if not hasattr(sheet, "plot_widget"):
                continue
            # SpectrogramDock also has a plot_widget but no secondary axis and
            # no iter_all_plot_items -- fall back to its primary item list.
            if hasattr(sheet, "iter_all_plot_items"):
                items = sheet.iter_all_plot_items()
            else:
                items = list(sheet.plot_widget.plotItem.items)
            for item in items:
                if isinstance(item, pg.PlotDataItem):
                    item.setDownsampling(ds_value, auto=auto)
                    item.setClipToView(clip)
            sheet.plot_widget.viewport().update()

    def replot_time_docks_for_unit_change(self) -> None:
        """
        Re-scales every open dock whose Analysis kind is registered as
        ``rebuilds_on_unit_change`` (ADR §1.89) from its untouched ``y_raw``
        for the new global units (``dock.curves.rebuild_units``, GraphCurves'
        own operation over plot_model_builder.rebuild_with_units) -- no disk,
        no DSP, and the frame (title, axes) is preserved rather than reset (a
        time-record replacement would relabel a spectrum / order-cut dock
        as a time record while the curve stays put, audit 02/9.1).

        Lives here so UnitSettingsDialog no longer walks
        main_window.workspace_tabs and replaces time records itself.
        """
        for idx in range(self.tabs.count()):
            dock = self.tabs.widget(idx)
            if not hasattr(dock, "curves") or not hasattr(dock, "_unit_preferences"):
                continue
            if dock.curves.model is None:
                continue
            kind = resolve_analysis_kind(getattr(dock, "analysis_kind", ANALYSIS_TIME))
            if not kind.rebuilds_on_unit_change:
                continue
            # The model's own analysis_kind, not just the dock's, has to
            # agree: a dock tagged e.g. "spectrum" over a plain time-built
            # model (no real spectrum draw ever landed yet) is left alone
            # rather than routed into a redraw whose view (title, axis
            # labels) belongs to a different analysis kind.
            if getattr(dock.curves.model, "analysis_kind", "") != kind.name:
                continue
            dock.curves.rebuild_units(dock._unit_preferences())

        panel = self.evaluation_panel
        if panel is not None and hasattr(panel, "on_units_changed"):
            panel.on_units_changed()

    def replot_docks_for_x_axis_unit_change(self) -> None:
        """
        Redraws every open dock -- graphs and spectrograms alike -- for a
        changed global X axis unit (issue #459), and the Evaluation table's
        "at X" with them. A display rescale only: no model is rebuilt, a dock
        opened later simply draws in the new unit from its first curve on.
        """
        for idx in range(self.tabs.count()):
            dock = self.tabs.widget(idx)
            if hasattr(dock, "apply_x_axis_unit"):
                dock.apply_x_axis_unit()

        panel = self.evaluation_panel
        if panel is not None and hasattr(panel, "on_units_changed"):
            panel.on_units_changed()

    def close_all_tabs(self) -> None:
        """
        Drops every open analysis tab, keeping the Home Workspace placeholder.

        Called when the project is swapped (New / Open): the previous project's
        plots otherwise stay on screen against a project that has no channel
        for any of them -- the same trap as a standing pool, one level up.
        See ProjectDocumentHandler.new_project / open_project.
        """
        placeholder = self.placeholder_graph
        for index in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.widget(index) is placeholder:
                continue
            self.close_specific_tab(index)

    def close_specific_tab(self, index: int):
        if index < 0 or index >= self.tabs.count():
            return
        target_widget = self.tabs.widget(index)
        if not target_widget:
            return

        # The Home Workspace is never closed (see show_home_tab); its tab has
        # no close button, and this guards every other way of asking.
        if target_widget is self.placeholder_graph:
            return

        self.tabs.removeTab(index)

        if isinstance(target_widget, (GraphDock, SpectrogramDock)):
            # Closing a tab changes what capture_open_tabs_spec would write on
            # the next Save just as much as opening one does -- see
            # AnalysisTabsMixin.open_acc_spectrum_tab.
            self._mark_project_dirty()

        if isinstance(target_widget, GraphDock):
            # A custom Local filter card is owned by the dock it was made on
            # (ADR §1.37); with the dock gone, drop the card and its
            # selections now rather than leave them invisible forever.
            panel = self.filter_panel
            dock_id = getattr(target_widget, "dock_id", None)
            if panel is not None and dock_id:
                panel.forget_dock(dock_id)

            target_widget.plot_widget.clear()

        if hasattr(target_widget, "_controller"):
            target_widget._controller = None

        # The dock is gone -- stop its reads and its DSP computation still in
        # flight; their results have nowhere to land.
        tag = getattr(target_widget, "dock_id", None)
        if tag:
            self.dock_tasks.cancel(tag)
            self.spectral_requests.forget(tag)

        target_widget.setParent(None)
        target_widget.deleteLater()

        if self.tabs.count() == 0:
            self.show_home_tab()

        if self.workspace_layout is not None:
            self.workspace_layout.save_state()
