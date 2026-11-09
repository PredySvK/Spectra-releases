# =====================================================================
# FILE: gui/workspace/workspace.py
# =====================================================================
"""
Workspace -- the holder of the central tabs: which docks are open, opening
and refreshing them, and closing them. Its public interface is listed in the
class docstring; the tab strip's own behaviour
(menu, rename, MRU, tab list) is `gui.workspace.tab_strip.TabStrip`.
"""

from typing import Any, Dict, List, Optional, Union
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QTabBar, QTabWidget, QWidget

from core.jobs import job_step
from gui.workspace.plot_title import set_plot_title
from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from gui.workspace.tab_strip import TabStrip
from gui.workspace.workspace_dock import WorkspaceDock
from gui.handlers.companion_curves import CompanionCurvesHandler
from gui.handlers.dock_tab_label import resolve_dock_tab_label, update_dock_tab_label
from gui.workspace.live_compute import DockBaseCurveTarget
from io_modules.tab_cache import write_tab_cache_file
from orchestration import tab_cache
from orchestration.channel_drop import build_channel_descriptors, resolve_dropped_channels
from orchestration.open_tabs import resolve_curve_refusal
from orchestration.dock_tasks import PURPOSE_COMPUTE, PURPOSE_TAB_CACHE, DockTasks
from core.evaluation import EvaluationConfig
from core.legend_config import LegendConfig
from core.units import strip_channel_name_prefix
from gui.workspace.open_tabs import OpenTabs
from io_modules.measurement_files import canonical_path
from session.data_pool import DeadLink, ResolvedTrace
from session.project import channel_label_for
from orchestration import live_compute
from orchestration.live_compute import ComputeOrigin
from selection.tacho import tacho_missing
from signal_processing.result_blocks import TrackingScratch
from view_models.tab_label import TabLabel, build_tab_label, build_tab_source
from view_models.analysis_kinds import (
    ANALYSIS_MODE_PROJECT, ANALYSIS_ORDERS, ANALYSIS_OVERALL_LEVEL, ANALYSIS_SPECTROGRAM, ANALYSIS_SPECTRUM,
    ANALYSIS_TIME, SKIP_CAPACITY, SKIP_IMPORTED, resolve_channel_analysis_kind, resolve_open_plan,
    resolve_analysis_kind, resolve_analysis_mode, resolve_analysis_mode_of_kind,
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
    Workspace itself exists -- the tab
    widget is created and never replaced well before Workspace is.
    """
    if not dock_id:
        return None

    for idx in range(tab_widget.count()):
        widget = tab_widget.widget(idx)
        if isinstance(widget, WorkspaceDock) and widget.dock_id == dock_id:
            return widget
        # Docks nested inside a container tab still have to be reachable.
        for child in widget.findChildren(QWidget):
            if isinstance(child, WorkspaceDock) and child.dock_id == dock_id:
                return child
    return None


class Workspace:
    """
    The central tab area as one object: which analysis docks are open, what
    each of them is computing, and where a result that arrives seconds later
    is allowed to land.

    Public interface (#251). Every other method of this class is internal: callers outside, tests included, drive the names
    below. (What a tab's Save recipe is while it is a "Missing" placeholder is
    kept by `open_tabs`, not on the dock.)

    Lifecycle
        The composition root builds this after the tab widget and the
        handlers it routes to, then hands over the two collaborators that
        cannot come by constructor because they are built *from* this object:
        `bind_evaluation_card`, `bind_workspace_layout` (§1.74/§1.75). Both
        are optional -- a window without them leaves the matching calls
        no-ops -- but neither may be bound twice.

    Open and refresh a dock
        `open_analysis_tab`, `open_specific_channel_tab`,
        `open_multi_channel_overlay_tab` open one; `open_channels_tab` picks
        between the last two for a Data Pool selection; `show_home_tab` puts the
        placeholder back when no tab is open. `refresh_active_tab`,
        `refresh_last_n_curves` recompute the tab in front.
        `build_shell` makes an empty dock and `base_curve_compute.start` starts
        (or restarts) its computation -- the pair a restore drives directly.

    Compute a Base curve
        `base_curve_compute` (`live_compute.BaseCurveCompute`, ADR §1.273) owns
        the whole life of a compute, its landing and its failure; this class
        only holds the tabs. Each of its steps takes a `dock_id` rather than a
        dock, and drops the result without a word when no open dock carries it.

    Ask about the docks
        `find_dock_by_id`, `open_dock_ids`, `route_channel_drop`.

    Session and settings
        `capture_open_tabs_spec`, `restore_open_tabs`
        (S6/S7), `rebuild_active_dock_display_settings`,
        `apply_graph_performance_settings`, `replot_time_docks_for_unit_change`,
        `toggle_band_rms_cursors`, `close_all_tabs`, `close_specific_tab`,
        `close_dock`. The Tools tab switches (Cursor, Pin, Highlight, Track,
        Track pin; their state is the Settings store's, ADR §1.290):
        `bind_tool_switches`, `toggle_tool_switch` (the shortcuts),
        `apply_tool_switches` (the store's reaction); `open_cursor_settings`,
        `open_track_cursor_settings`.

    Tab labels and the tab strip
        `set_tab_custom_label`, `reset_tab_label` are the one writer of a
        tab's custom label, as `close_dock` is the one way a tab ends.
        `tab_strip` (`gui.workspace.tab_strip.TabStrip`; None over a
        stand-in tab widget) is the strip's own behaviour -- menu, rename,
        MRU switching, tab list -- and goes through those two for both.

    Thread affinity
        Every method here is called on the GUI thread and touches widgets, so
        nothing on this class may be called from a worker. The one hop out is
        `dock_tasks` (`orchestration.dock_tasks.DockTasks` over the
        QtJobRunner): it runs a read on the interactive lane and applies the
        result back on the GUI thread, dropping it if the dock was closed or a
        newer task with the same purpose for the same dock has since started. A
        dock's own compute -- cache lookup, read and DSP -- is one such task
        (`live_compute.run_live_compute`, ADR §1.167).

    Callback ordering
        A fresh open is `build_shell` then `base_curve_compute.start` -- the dock
        exists, and is in the tab widget, before anything is computed for it,
        because that is what lets a late result find it by id. A restore adds
        the base curve first and re-drops the saved overlays only once it has
        landed.

    Error modes
        These methods do not raise for a condition the user can cause: a
        missing tacho, a dead link in a saved recipe, a read that fails, a
        ribbon action on the wrong kind of tab all log through
        `app_context.log` and leave something to look at. What a failed
        compute does to its tab depends on why the dock was computing
        (`ComputeOrigin`) and is decided in one table,
        `live_compute.plan_compute_failure`: a fresh open drops its own tab, a
        restored one stays (a "Missing" placeholder when its file cannot be
        read), a refresh keeps the plot it already had. A `TypeError` from a
        wrong call *is* raised: it is a programming mistake, not a data problem.

    Test seam
        Tests build a real instance through this constructor and drive the
        names above. `tests/workspace_harness.py` is the only place allowed to
        substitute the background hop (see its module docstring).
    """

    def __init__(self, app_context, tab_widget: QTabWidget, *,
                 placeholder_graph=None,
                 filter_panel=None,
                 job_runner,
                 result_content_handler=None,
                 # gui.handlers.filter_routing.FilterRoutingHandler
                 # (#234, ARCHITECTURE_DECISIONS §1.76), built by the
                 # composition root before this manager so it can be handed
                 # over by constructor. None in a window with no Filter panel
                 # and in tests that do not drive the mask -- both leave the
                 # three call sites below as no-ops.
                 filter_routing=None,
                 # The Tab cache file write; tests hand in a fake.
                 tab_cache_write=write_tab_cache_file):
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
        # dock task run on it. Always the window's own -- a workspace never
        # builds a queue the Jobs dock cannot see.
        self.job_runner = job_runner
        # Every dock's background read goes through here: one
        # answer to "is this result still wanted?" for the whole workspace.
        self.dock_tasks = DockTasks(
            self.job_runner, is_open=lambda dock_id: self.find_dock_by_id(dock_id) is not None)
        # The Tab cache of every curve of every open tab: names, writes, and
        # what an Untitled project holds until its first Save.
        self.tab_cache_files = tab_cache.TabCacheFiles(
            start_write=lambda dock_id, fn, *args, on_error: self.dock_tasks.run(
                dock_id, fn, *args, purpose=PURPOSE_TAB_CACHE, on_error=on_error),
            writes_in_flight=lambda: self.dock_tasks.count_in_flight(PURPOSE_TAB_CACHE),
            project_path=self._project_path,
            saved_open_tabs=self._saved_open_tabs,
            mark_view_changed=self._mark_view_changed,
            log=lambda text: self.app_context.log(text),
            is_open=lambda dock_id: self.find_dock_by_id(dock_id) is not None,
            write_file=tab_cache_write)
        self.companion_curves = CompanionCurvesHandler(
            app_context, self.dock_tasks, self.route_channel_drop)
        # One TrackingPlan bag for every dock's compute: a click on another
        # channel of the same file (same tacho, same sweep) reuses the plan
        # instead of rebuilding it (#500, ADR §1.133).
        self.tracking_scratch = TrackingScratch()
        self.result_content_handler = result_content_handler
        self.filter_routing = filter_routing
        # Save / restore of the tab set.
        self.open_tabs = OpenTabs(self)
        # The whole life of every tab's Base curve compute.
        self.base_curve_compute = live_compute.BaseCurveCompute(
            find_target=self._find_base_curve_target,
            run_task=lambda dock_id, fn, *args, **kwargs: self.dock_tasks.run(
                dock_id, fn, *args, purpose=PURPOSE_COMPUTE, **kwargs),
            ribbon_config=lambda kind: getattr(
                self.app_context, resolve_analysis_mode_of_kind(kind).settings_name),
            cache_finder=lambda: live_compute.resolve_cache_finder(
                getattr(self.app_context, "project_session", None),
                getattr(self.app_context, "use_result_cache_lookup", True)),
            with_order_overall_level=lambda: bool(
                getattr(self.app_context, "order_tracking_overall_level", False)),
            project_path=self._project_path,
            tab_cache_files=self.tab_cache_files,
            tracking_scratch=self.tracking_scratch,
            log=lambda text: self.app_context.log(text))
        # Bound after construction rather than by constructor: both are built
        # from this manager (EvaluationCard takes it, WorkspaceLayout takes
        # that panel), so neither can exist yet -- see bind_evaluation_card
        # and bind_workspace_layout.
        self.evaluation_card = None
        self.tool_switch_buttons: Dict[str, Any] = {}
        self.workspace_layout = None
        # The tab strip's own behaviour (menu, rename, MRU, tab list) -- only
        # over a real QTabWidget; a stand-in tab widget in a test gets none.
        self.tab_strip = TabStrip(
            self.tabs, placeholder=placeholder_graph, close_dock=self.close_dock,
            set_label=self.set_tab_custom_label, reset_label=self.reset_tab_label,
        ) if isinstance(self.tabs, QTabWidget) else None

        self.selection_drops = None

        # The placeholder is a GraphDock, so it accepts a channel drag like any
        # dock -- but it is no place to keep curves (capture_open_tabs_spec
        # skips it). A drop on it opens a tab the way a double click would.
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

    def bind_evaluation_card(self, panel) -> None:
        """
        Hands over the Evaluation card once it exists.

        It cannot come by constructor: EvaluationCard takes this manager by
        constructor itself (it runs its reads through `dock_tasks`), so
        the manager is necessarily the older of the two. Same `bind_*` shape
        UnvChannelExplorer.bind_workspace uses for the mirror-image case
        (#241).
        """
        self.evaluation_card = panel

    def bind_workspace_layout(self, layout) -> None:
        """
        Hands over the dock layout once it exists, so closing a tab can save
        the arrangement. Built after this manager for the same reason
        `bind_evaluation_card` exists: WorkspaceLayout is assembled from the
        panels -- the Evaluation card among them -- that are made from this
        manager.
        """
        self.workspace_layout = layout

    def bind_tool_switches(self, buttons: Dict[str, Any]) -> None:
        """Hands over the Tools tab's switch buttons, keyed like the settings they show.

        The Settings store owns each switch; a click writes it there and the button only
        shows what the store holds.
        """
        self.tool_switch_buttons = dict(buttons)
        for key, button in self.tool_switch_buttons.items():
            button.setChecked(bool(self.app_context.settings_store.value(key)))
            button.toggled.connect(
                lambda checked, key=key: self.app_context.settings_store.apply({key: bool(checked)}))

    def toggle_tool_switch(self, key: str) -> None:
        """A switch's shortcut (`C`, `P`, `H`, `T`): flips the switch in the Settings store."""
        store = self.app_context.settings_store
        store.apply({key: not store.value(key)})

    def apply_tool_switches(self, changed: Dict[str, bool]) -> None:
        """A Settings store reaction: show the changed switches on the ribbon and in every open graph.

        Run for a click, a shortcut and Reset All Settings alike.
        """
        for key, value in changed.items():
            button = self.tool_switch_buttons.get(key)
            if button is not None:
                # Signals stay on: a tile restyles and enables its chip from `toggled`.
                # The echo writes the same value back, which the store does not report.
                button.setChecked(bool(value))
        for dock in self._open_docks():
            # Off (or unpinned) hides the boxes, so they reappear at the mouse.
            if any(key in changed and not changed[key] for key in ("cursor_enabled", "cursor_pinned")):
                dock.hide_cursor_box()
            if changed.get("highlight_enabled") is False:
                dock.clear_highlight()
            if "track_cursor_enabled" in changed:
                dock.refresh_track_cursor()
            if "track_cursor_pinned" in changed:
                dock.apply_track_cursor_pin()
            if "track_cursor_highlight_enabled" in changed:
                dock.refresh_track_cursor_highlight()

    def open_cursor_settings(self) -> None:
        """Cursor Settings: the field list is global, so it is saved on OK, not into the project."""
        from gui.dialogs.field_priority_dialog import FieldPriorityDialog
        ctx = self.app_context
        dialog = FieldPriorityDialog(
            ctx.pool.schema().master, ctx.cursor_config, self.tabs.window(),
            settings=getattr(ctx, "settings", None), other_opacity=ctx.highlight_other_opacity)
        try:
            if dialog.exec():
                ctx.set_cursor_config(dialog.result_config())
                for dock in self._open_docks():
                    dock.refresh_cursor_box()
                # The window's settings reactions redraw the graphs.
                ctx.settings_store.apply({"highlight_other_opacity": dialog.result_other_opacity()})
        finally:
            dialog.deleteLater()

    def apply_highlight_opacity(self) -> None:
        """Update already highlighted curves in every open graph."""
        for dock in self._open_docks():
            dock.refresh_highlight()

    def _preview_track_cursor(self, config, table_opacity=None, other_opacity=None) -> None:
        """Track cursor Settings' Auto apply: show the working fields and opacities in every open graph (None ends it)."""
        for dock in self._open_docks():
            dock.set_track_preview(config, table_opacity)
            dock.set_highlight_preview(None if config is None else other_opacity)

    def apply_track_table_opacity(self) -> None:
        """Repaint the Track table's background in every open graph."""
        for dock in self._open_docks():
            dock.refresh_track_cursor()

    def open_track_cursor_settings(self) -> None:
        """Track cursor Settings: the Track table's own global columns, saved on OK."""
        from gui.dialogs.field_priority_dialog import TRACK_CURSOR_SETTINGS, FieldPriorityDialog
        ctx = self.app_context
        dialog = FieldPriorityDialog(
            ctx.pool.schema().master, ctx.track_cursor_config, self.tabs.window(),
            settings=getattr(ctx, "settings", None), spec=TRACK_CURSOR_SETTINGS,
            other_opacity=ctx.highlight_other_opacity, table_opacity=ctx.track_table_opacity,
            on_live_change=self._preview_track_cursor)
        try:
            if dialog.exec():
                ctx.set_track_cursor_config(dialog.result_config())
                # The one "Other curves opacity" Cursor Settings stores too (cursors §1.293).
                ctx.settings_store.apply({"track_table_opacity": dialog.result_table_opacity(),
                                          "highlight_other_opacity": dialog.result_other_opacity()})
            # OK has saved what the preview showed; Cancel goes back to the saved values.
            self._preview_track_cursor(None)
        finally:
            dialog.deleteLater()

    def find_dock_by_id(self, dock_id: str):
        """Delegates to the module-level `find_dock_by_id` (see its docstring),
        bound to this instance's own tab widget."""
        return find_dock_by_id(self.tabs, dock_id)

    def _find_base_curve_target(self, dock_id: str) -> Optional[DockBaseCurveTarget]:
        dock = self.find_dock_by_id(dock_id)
        return DockBaseCurveTarget(self, dock) if dock is not None else None

    def _open_docks(self) -> List[WorkspaceDock]:
        """Every dock open as a tab, in tab order -- the one walk every
        broadcast to the docks goes through (#899)."""
        docks = []
        for idx in range(self.tabs.count()):
            widget = self.tabs.widget(idx)
            if isinstance(widget, WorkspaceDock):
                docks.append(widget)
        return docks

    def open_dock_ids(self) -> set:
        """Every currently open tab's `dock_id` (skipping tabs that have none,
        e.g. the startup placeholder) -- callers that need to reconcile
        dock ids against saved state, like the Filter panel's orphan-card
        prune (§1.37, §1.94)."""
        return {dock.dock_id for dock in self._open_docks() if dock.dock_id}

    def _mark_project_dirty(self) -> None:
        """
        Records that an open tab was added or removed since the last Save.

        getattr guards the lightweight StubContext several dock-routing tests
        substitute for a real AppContext -- those tests care about routing,
        not the project's dirty flag, and never set up a project_session.
        """
        session = getattr(self.app_context, "project_session", None)
        if session is not None:
            session.mark_work_changed()

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
        actual = widget.analysis_kind if isinstance(widget, WorkspaceDock) else None

        if actual != analysis_kind:
            self.app_context.log(
                f"WARNING: {action_label} needs an active {analysis_kind} tab "
                f"(current tab is '{actual or 'empty'}')."
            )
            return None

        if not isinstance(widget, (GraphDock, SpectrogramDock)):
            self.app_context.log(f"WARNING: This tab has no source channel to recompute.")
            return None

        return widget

    def route_channel_drop(self, dock_instance, raw_descriptors, batch_label=None, *,
                           mark_work_changed=True, from_refresh=False) -> bool:
        """
        The one place that knows what `execute_channel_drop_processing` needs.

        An accepted drop changes what capture_open_tabs_spec writes on the next
        Save, so it marks the project dirty -- except a re-drop of curves the
        graph already had (a restore or a refresh, `mark_work_changed=False`).
        `from_refresh` says a Refresh re-drops them, so they obey the ribbon on
        a dock holding result sets. A tab with a warning refuses
        the drop, so its saved recipe stays whole.

        Three of its arguments are collaborators this manager holds and the
        drop router does not (#242); binding them here means a fourth one is
        added in one place rather than at every site that routes a drop --
        the dock's own drop signal, a restored dock's pending overlays, and
        refresh_last_n_curves.
        """
        refusal = resolve_curve_refusal(
            dead_link=dock_instance.dead_link, compute_failed=dock_instance.compute_failed,
            is_graph=isinstance(dock_instance, GraphDock))
        if refusal is not None:
            self.app_context.log(refusal)
            return False

        from gui.workspace.channel_drop import execute_channel_drop_processing
        accepted = execute_channel_drop_processing(
            dock_instance=dock_instance,
            raw_descriptors=raw_descriptors,
            app_context=self.app_context,
            workspace=self,
            batch_label=batch_label,
            from_refresh=from_refresh,
        )
        if accepted and mark_work_changed:
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
        and logs the rest. Imported results alone open in the Analysis kind that shows
        them; mixed with other channels they never switch the active mode --
        outside their own mode they are skipped (#509). `resolve_open_plan` decides.
        """
        if not channels:
            return
        analysis_mode = resolve_analysis_mode(getattr(self.app_context, "current_analysis_mode", ANALYSIS_MODE_PROJECT))
        plan = resolve_open_plan(channels, analysis_mode)
        imported = [row for row, reason in plan.skipped if reason == SKIP_IMPORTED]
        if imported:
            self.app_context.log(f"WARN: {len(imported)} imported result channel(s) skipped; they open only "
                                 f"in the mode that shows them (Order Tracking, Spectrum or Overall Level).")
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
        self._drop_home_tab()
        dock = GraphDock(app_context=self.app_context)
        dock.analysis_kind = analysis_kind
        self._connect_dock_signals(dock)
        # T4: same reasoning as build_shell -- a Global filter's selection
        # already exists project-wide, so this fresh dock should not have to
        # wait for a tab switch to pick it up.
        if self.filter_routing is not None:
            self.filter_routing.apply_active_filter_to_dock(dock)
        self._add_dock_tab(dock, build_tab_label(analysis_kind, [
            build_tab_source(r[0].file_name if r[0] else "", r[1].name)
            for r in rows
        ]))
        set_plot_title(dock.plot_widget, "⏳ Loading...")

        kind = resolve_analysis_kind(analysis_kind)
        label = f"{'Load' if analysis_kind == ANALYSIS_TIME else kind.display_name} — {what or f'{len(rows)} channels'}"
        if not self.route_channel_drop(dock, build_channel_descriptors(rows), batch_label=label):
            self.app_context.log(f"WARN: No channel could be loaded into the {kind.display_name} comparison tab; "
                                 f"tab closed.")
            self.close_dock(dock, mark_work_changed=False)

    def _open_dropped_on_home_tab(self, raw_descriptors: list) -> None:
        context = self.app_context
        channels = resolve_dropped_channels(raw_descriptors, context.pool.run_lookup, context.log)
        self.open_channels_tab([channel.row for channel in channels])

    def _drop_home_tab(self):
        """Removes the lone "Home Workspace" placeholder before the first real dock opens."""
        placeholder = self.placeholder_graph
        if placeholder is not None:
            index = self.tabs.indexOf(placeholder)
            if index != -1:
                self.tabs.removeTab(index)
        elif self.tabs.count() == 1 and self.tabs.tabText(0) == HOME_TAB_TITLE:
            self.tabs.removeTab(0)

    def _connect_dock_signals(self, dock_instance: WorkspaceDock):
        """Binds every WorkspaceDock signal to the Workspace step that answers it."""
        dock_instance.sig_channels_dropped.connect(
            lambda payload, d=dock_instance: self.route_channel_drop(d, payload)
        )
        dock_instance.sig_cursor_toggle_requested.connect(lambda: self.toggle_tool_switch("cursor_enabled"))
        dock_instance.sig_cursor_pin_requested.connect(lambda: self.toggle_tool_switch("cursor_pinned"))
        dock_instance.sig_highlight_toggle_requested.connect(lambda: self.toggle_tool_switch("highlight_enabled"))
        dock_instance.sig_track_cursor_toggle_requested.connect(
            lambda: self.toggle_tool_switch("track_cursor_enabled"))
        dock_instance.sig_selection_dropped.connect(
            lambda name, d=dock_instance: self.draw_selection(name, d)
        )
        dock_instance.sig_first_trace_rendered.connect(
            lambda d=dock_instance: self._reapply_filter_for_dock(d)
        )
        dock_instance.sig_trace_added.connect(
            lambda d=dock_instance: self._reapply_filter_for_dock(d)
        )
        dock_instance.sig_content_or_mask_changed.connect(
            lambda d=dock_instance: self.companion_curves.handle_curves_added(d)
        )
        dock_instance.sig_content_or_mask_changed.connect(
                lambda d=dock_instance: self._notify_evaluation_card(d)
            )

    def _notify_evaluation_card(self, dock) -> None:
        """
        Consumer of GraphDock.sig_content_or_mask_changed (issue #136): the
        Evaluation card ignores this unless `dock` is the one it is showing
        (EvaluationCard.on_dock_content_changed does that check itself).

        None-guarded the same way `_mark_project_dirty` guards
        `project_session` -- the routing tests build this manager without an
        Evaluation card at all, and they render/overlay docks without caring
        about it.
        """
        panel = self.evaluation_card
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
        custom_tab_label: Optional[str] = None,
        legend_config: Optional[LegendConfig] = None,
    ):
        """
        Creates the tab + dock for `analysis_kind` and stamps run_index/
        channel_meta onto it when `resolved` is live -- but never starts a
        background read (that is base_curve_compute.start's job, called right after
        by every caller below). Split out so a fresh double-click and a
        future restore (S6) go through the exact same branch: a double-click
        already has a live (run_index, channel_meta) pair and wraps it in a
        ResolvedTrace inline; restore hands whatever tab_spec_resolver.
        resolve_trace returned it, dead links included
        (the session persistence plan S3/S4/S6).

        `analysis_kind` is TabSpec's vocabulary ("time" | "spectrum" |
        "orders" | "overall_level" | "spectrogram") and the same value
        ends up on `dock.analysis_kind`; a SpectrogramDock sets its own
        "spectrogram" in its constructor.

        A DeadLink produces an empty, titled dock and a log line, never a
        crash -- the file or channel a saved recipe pointed at may be gone
        by the time the project reopens. Callers must not call
        base_curve_compute.start on the result in that case; there is nothing to
        compute it from.

        `dock_id` is the id a restored dock was saved with: the
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
        dock.custom_tab_label = custom_tab_label
        if legend_config is not None and isinstance(dock, GraphDock):
            dock.curves.set_legend_config(legend_config)    # else the Default it started with
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
            # is still missing does not drop this recipe from open_tabs --
            # capture_open_tabs_spec reads it back when dock.run_index is None
            # (S5/PLAN.md S6 "Zastaraný súbor"). The file may simply be on an
            # unmounted drive this session; without this, restoring once would
            # be the last time it is ever tried again.
            dock.dead_link = resolved
            self._add_dock_tab(dock, resolve_dock_tab_label(dock))
            self.app_context.log(
                f"WARNING: could not restore '{resolved.channel_name}' ({resolved.reason})."
            )
            return dock

        dock.run_index = resolved.run_index
        dock.channel_meta = resolved.channel_meta
        self._add_dock_tab(dock, resolve_dock_tab_label(dock))
        return dock

    def _add_dock_tab(self, dock, tab_label: TabLabel) -> None:
        """Puts `dock` up as the current tab, under the label built for it."""
        tab_idx = self.tabs.addTab(dock, tab_label.label)
        self.tabs.setTabToolTip(tab_idx, tab_label.tooltip)
        self.tabs.setCurrentIndex(tab_idx)

    def open_analysis_tab(self, analysis_kind: str, run_index, channel_meta) -> None:
        """
        Opens a tab of `analysis_kind` on the channel and starts its compute.
        A kind that cannot go without a tacho is refused here rather than in
        an empty dock: there is nothing useful to show in one.
        """
        if not self._refuse_missing_tacho(analysis_kind, run_index):
            self._open_tab(analysis_kind, run_index, channel_meta)

    def _open_tab(self, analysis_kind: str, run_index, channel_meta) -> None:
        dock = self.build_shell(analysis_kind, ResolvedTrace(run_index, channel_meta))
        # A newly opened tab is a recipe the project does not have yet --
        # unlike a View change (a checked filter value), losing it silently
        # on close is exactly what the user opens a tab to avoid (session_persistence
        # follow-up, 2026-09-04: PLAN.md's S5 "no dirty tracking" call reversed here).
        self._mark_project_dirty()
        self.base_curve_compute.start(dock.dock_id, origin=ComputeOrigin.FRESH_OPEN)

    def refresh_active_tab(self, analysis_kind: str) -> None:
        """Recomputes the tab in front, which has to be of `analysis_kind`."""
        dock = self._require_active_dock(analysis_kind, resolve_analysis_kind(analysis_kind).refresh_action)
        if dock is None:
            return
        if dock.run_index is None:
            self._refresh_user_channels(dock)
            return
        if self._refuse_missing_tacho(analysis_kind, dock.run_index, tacho_bound=dock.tacho_block is not None):
            return

        # The landing of the recompute resets the
        # graph to just the base curve -- the overlays on screen at that moment
        # are captured and re-dropped (BUGS.md I1, #285, GraphCurves.begin_refresh).
        # A spectrogram holds no overlays.
        if isinstance(dock, GraphDock):
            dock.curves.begin_refresh()
        self.base_curve_compute.start(dock.dock_id, origin=ComputeOrigin.REFRESH)

    def _refresh_user_channels(self, dock) -> None:
        """
        Refresh of a tab with no run of its own -- one opened on several
        channels at once (§1.288, #926): every channel the user dropped or opened it on
        is taken off the graph and dropped again, so it obeys the ribbon like
        any Refresh. A curve only a result set holds is only read
        again; an Adopted curve stays as its set's until the channel lands
        (§1.241). A channel whose file has no tacho is refused by the drop, one
        file at a time, and its siblings still go.
        """
        if not isinstance(dock, GraphDock):
            self.app_context.log("WARNING: This tab has no source channel to recompute.")
            return
        descriptors = dock.curves.user_channel_drop_descriptors()
        if not descriptors:
            self.app_context.log("WARNING: This tab shows only result sets; there is no channel to recompute.")
            return
        if dock.curves.remove_user_channels():
            dock.clear_plot()
        self.route_channel_drop(dock, descriptors, mark_work_changed=False, from_refresh=True)

    def _refuse_missing_tacho(self, analysis_kind: str, run_index, *, tacho_bound: bool = False) -> bool:
        """True, with the kind's one refusal logged, when `analysis_kind` needs
        a tacho the channel's run does not have (ADR §1.62 point 7 and 19,
        issue #124: only rpm tracking needs one for an Overall Level)."""
        kind = resolve_analysis_kind(analysis_kind)
        if not kind.tacho_missing_message:
            return False
        tracking_mode = "rpm"
        if kind.tacho_only_in_rpm_mode:
            settings_name = resolve_analysis_mode_of_kind(analysis_kind).settings_name
            tracking_mode = getattr(self.app_context, settings_name).tracking_mode
        if not tacho_missing(run_index, tacho_bound=tacho_bound, tracking_mode=tracking_mode):
            return False
        self.app_context.log(kind.tacho_missing_message.format(file_name=run_index.file_name))
        return True

    def refresh_last_n_curves(self, n: int) -> None:
        """
        Ribbon "Refresh Last N" (S8, the session persistence plan): recomputes
        only the N most recently added curves on the active spectrum/order dock
        with the ribbon's current config, leaving every other curve exactly as
        it is. A plain Refresh already recomputes everything (see
        RefreshSplitButton's docstring); this exists for "I dropped one more
        comparison channel, only recompute that one" without disturbing curves
        already tuned by an earlier partial refresh.

        The base curve is always the *oldest* curve on a dock (it is drawn
        before anything can be dropped onto it), so "last N" only ever reaches
        it once N covers every curve on the dock -- at that point this is
        exactly a plain Refresh, and delegates there rather than duplicating
        it. Below that, only overlay curves are touched, which needs no new
        per-curve removal: the target overlays are dropped through `dock.
        curves.remove_overlays` (cheap -- no disk I/O, the surviving curves'
        arrays are already in memory, and GraphCurves redraws what remains),
        and the removed curves are re-added through `execute_channel_drop_
        processing`, the exact entry point a real drag uses, so they get a
        real recompute under the current ribbon config rather than a re-plot
        of stale data.
        """
        widget = self.tabs.currentWidget()
        analysis_kind = widget.analysis_kind if isinstance(widget, WorkspaceDock) else None
        if analysis_kind not in (ANALYSIS_SPECTRUM, ANALYSIS_ORDERS, ANALYSIS_OVERALL_LEVEL):
            self.app_context.log(
                f"WARNING: Refresh Last {n} needs an active spectrum, order "
                f"tracking or Overall Level tab (current tab is '{analysis_kind or 'empty'}')."
            )
            return

        dock = self._require_active_dock(analysis_kind, f"Refresh Last {n}")
        if dock is None or dock.curves.model is None:
            return

        base_channel = None
        if dock.run_index is not None and dock.channel_meta is not None:
            base_channel = (str(dock.run_index.file_path), int(dock.channel_meta.index))
        targets = live_compute.plan_last_n_refresh(dock.curves.overlay_drop_descriptors(), n, base_channel)
        if targets is None:
            self.refresh_active_tab(analysis_kind)
            return

        target_keys = {(t["file_path"], t["channel_index"]) for t in targets}

        def _is_target(trace):
            meta = trace.meta_ref or {}
            return (str(meta.get("file_path", "")), int(meta.get("channel_index", 0))) in target_keys

        dock.curves.remove_overlays(_is_target)

        self.route_channel_drop(dock, list(targets), mark_work_changed=False, from_refresh=True)

    def _project_path(self):
        """The project file's path; None while the project is Untitled."""
        return getattr(getattr(self.app_context, "project_session", None), "path", None)

    def capture_open_tabs_spec(self) -> List[Dict[str, Any]]:
        """`self.tabs` -> one `TabSpec` dict per live analytical dock (see `OpenTabs.capture`)."""
        return self.open_tabs.capture()

    def restore_open_tabs(self) -> None:
        """Rebuilds every dock the project's `open_tabs` recorded (see `OpenTabs.restore`)."""
        self.open_tabs.restore()

    def open_specific_channel_tab(self, run_index, channel_meta):
        # An Imported result is only read: it never needs the tacho its kind's
        # compute would.
        shown_by = resolve_channel_analysis_kind(channel_meta)
        if shown_by is not None:
            self._open_tab(shown_by, run_index, channel_meta)
            return
        analysis_mode = resolve_analysis_mode(getattr(self.app_context, "current_analysis_mode", ANALYSIS_MODE_PROJECT))
        self.open_analysis_tab(analysis_mode.analysis_kind, run_index, channel_meta)

    def toggle_band_rms_cursors(self, enabled: bool) -> None:
        """Band RMS is one app-level flag for every spectrum; a graph that holds
        none has nothing to show and says nothing."""
        self.app_context.band_rms_cursors_enabled = bool(enabled)
        for dock in self._open_docks():
            dock.refresh_band_rms_cursors()

    def rebuild_active_dock_display_settings(self, expected_kind: Optional[str] = None) -> None:
        """
        Instantly re-scales the active dock's display format / amplitude / scale (< 1 ms),
        without background worker jobs or DSP recomputation.

        The dock reads its own settings (`_display_settings`, #833); a ribbon
        tab that changed only says so. A dock whose Block kind has no
        `display_only_params` has nothing to rebuild.
        """
        dock = self.tabs.currentWidget()
        if not isinstance(dock, (GraphDock, SpectrogramDock)):
            return
        if expected_kind is not None and dock.analysis_kind != expected_kind:
            return
        if not resolve_analysis_kind(dock.analysis_kind).display_only_params:
            return
        dock.rebuild_with_display_settings()

    def apply_graph_performance_settings(self) -> None:
        """
        Asks every open dock for the same clip / downsample sweep a resize runs
        (#665 C27). Workspace applies nothing itself: the point-count rule and the
        PlotDataItem calls live in GraphDock.apply_viewport_clipping. Docks without
        that sweep (SpectrogramDock: no 1D curves, no secondary axis) are skipped.
        """
        for dock in self._open_docks():
            dock.apply_viewport_clipping()

    def replot_time_docks_for_unit_change(self) -> None:
        """
        Tells every open dock the global units changed -- each one does its
        own steps (``WorkspaceDock.apply_unit_preferences``: display prefixes,
        the ADR §1.89 rebuild from ``y_raw``, the Cursor Box) -- and the
        Evaluation table with them.

        Lives here so the Settings window no longer walks
        main_window.workspace_tabs and replaces time records itself.
        """
        for dock in self._open_docks():
            dock.apply_unit_preferences()

        panel = self.evaluation_card
        if panel is not None:
            panel.on_units_changed()

    def replot_docks_for_x_axis_unit_change(self) -> None:
        """
        Redraws every open dock -- graphs and spectrograms alike -- for a
        changed global X axis unit (issue #459), and the Evaluation table's
        "at X" with them. A display rescale only: no model is rebuilt, a dock
        opened later simply draws in the new unit from its first curve on.
        """
        for dock in self._open_docks():
            dock.apply_x_axis_unit()

        panel = self.evaluation_card
        if panel is not None:
            panel.on_units_changed()

    def _saved_open_tabs(self):
        """The saved project's open tabs; None without a session."""
        session = self._project_session()
        return session.project.open_tabs if session is not None else None

    def _mark_view_changed(self) -> None:
        session = self._project_session()
        if session is not None:
            session.mark_view_changed()

    def _project_session(self):
        return getattr(self.app_context, "project_session", None)

    def finish_tab_cache_writes(self, show_note=None, timeout_ms: int = 60000) -> bool:
        """
        Waits, keeping the window painted, until every Tab cache write in
        flight has landed -- closing the application calls this before it
        cancels the job queue, or a result the user just waited for would
        compute again on the next open, and Save As before it lists the files
        to copy. `show_note(text)` puts a line on the
        status strip for the wait and `show_note(None)` takes it down.
        Returns False when `timeout_ms` ran out first.
        """
        def writing() -> bool:
            return self.tab_cache_files.has_writes_in_flight()

        if not writing():
            return True
        if show_note is not None:
            show_note("Saving tab cache before closing…")
        loop = QEventLoop()

        def landed(_job_id) -> None:
            if not writing():
                loop.quit()

        # Every write is a job of its own: each finished job is the moment
        # to look again. Nothing runs between the check above and exec(),
        # so the last write cannot finish unseen.
        self.job_runner.job_finished.connect(landed)
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        deadline.start(timeout_ms)
        loop.exec()
        deadline.stop()
        self.job_runner.job_finished.disconnect(landed)
        if show_note is not None:
            show_note(None)
        return not writing()

    def close_all_tabs(self) -> None:
        """
        Drops every open analysis tab, keeping the Home Workspace placeholder.

        Called when the project is swapped (New / Open): the previous project's
        plots otherwise stay on screen against a project that has no channel
        for any of them -- the same trap as a standing pool, one level up.
        See orchestration.project_swap.

        Never marks the project dirty: the tabs closed here belong to the
        outgoing project, never to the one being opened (#640).
        """
        placeholder = self.placeholder_graph
        for index in range(self.tabs.count() - 1, -1, -1):
            if self.tabs.widget(index) is placeholder:
                continue
            self.close_specific_tab(index, mark_work_changed=False)

    def set_tab_custom_label(self, index: int, label: str) -> None:
        """Sets a custom user label on the tab at `index` (#847)."""
        if index < 0 or index >= self.tabs.count():
            return
        dock = self.tabs.widget(index)
        if dock is self.placeholder_graph:
            return
        dock.custom_tab_label = label
        update_dock_tab_label(dock)
        self._mark_project_dirty()

    def reset_tab_label(self, index: int) -> None:
        """Resets the tab at `index` to its automatic label (#847)."""
        if index < 0 or index >= self.tabs.count():
            return
        dock = self.tabs.widget(index)
        if dock is self.placeholder_graph:
            return
        dock.custom_tab_label = None
        update_dock_tab_label(dock)
        self._mark_project_dirty()

    def close_specific_tab(self, index: int, *, mark_work_changed: bool = True):
        if index < 0 or index >= self.tabs.count():
            return
        target_widget = self.tabs.widget(index)
        if not target_widget:
            return

        self.close_dock(target_widget, mark_work_changed=mark_work_changed)

    def close_dock(self, dock, *, mark_work_changed: bool = True) -> None:
        """
        The one way a tab ends, whoever asks: the user, or a fresh open that
        failed. Looks the tab up by its dock, so a stale captured index never
        removes the wrong one. The Home Workspace comes back when this was the
        last tab, or the workspace would accept no drop.
        """
        index = self.tabs.indexOf(dock)
        if index == -1:
            return

        # The Home Workspace is never closed (see show_home_tab); its tab has
        # no close button, and this guards every other way of asking.
        if dock is self.placeholder_graph:
            return

        self.tabs.removeTab(index)

        if mark_work_changed and isinstance(dock, (GraphDock, SpectrogramDock)):
            # Closing a tab changes what capture_open_tabs_spec would write on
            # the next Save just as much as opening one does -- see
            # _open_tab.
            self._mark_project_dirty()

        if isinstance(dock, GraphDock):
            # A custom Local filter card is owned by the dock it was made on
            #; with the dock gone, drop the card and its
            # selections now rather than leave them invisible forever.
            panel = self.filter_panel
            if panel is not None:
                panel.forget_dock(dock.dock_id)

            dock.plot_widget.clear()

        # The dock is gone -- stop its reads and its computation still in
        # flight; their results have nowhere to land.
        if isinstance(dock, WorkspaceDock):
            tag = dock.dock_id
            self.dock_tasks.cancel(tag)
            self.base_curve_compute.forget(tag)
            self.tab_cache_files.close_tab(tag)

        dock.setParent(None)
        if self.tab_strip is not None:
            self.tab_strip.forget(dock)
        dock.deleteLater()

        if self.tabs.count() == 0:
            self.show_home_tab()

        if self.workspace_layout is not None:
            self.workspace_layout.save_state()
