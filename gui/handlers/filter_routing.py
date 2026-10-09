# =====================================================================
# FILE: gui/handlers/filter_routing.py
# =====================================================================
"""
Filter panel routing: rebuilding the panel's facets from the Qt workspace
state, and routing the active profile's in-memory mask onto the open docks.

Named `compare_actions` until ADR §1.43 folded in the one-file
`filter_actions` module (`apply_active_filter_to_dock`) and lifted the
unrelated live-channel-drop half out to
`gui.handlers.live_channel_drop` -- the Compare dock it was named for
stopped being special at §1.30, and the file was one concern by then.

Since §1.76 (#234) the whole module is one handler, `FilterRoutingHandler`,
built once by the composition root (`gui/main_window.py`) with the five things
it reads -- `app_context`, `filter_panel`, `workspace_tabs`, `explorer_panel`
and a Qt `parent_widget` for the Configure Filters dialog -- instead of every
function digging them back out of the main window frame it was handed. It is
the single owner of the mask: the active profile comes from the panel, the
traces come from the docks, and both halves meet in
`refresh_and_apply_for_focused_dock`, the shared tail of the dock-focus and
profile-focus triggers, which is why this is one class and not a "panel" one
and a "mask" one.

Since §1.30, a dock's h5 curves (gui.handlers.result_content), its
dropped channels and its live computations all live side by side in the same
PlotModel, and the Filter panel's active profile reaches every open dock
through the single mask entry point, `apply_active_filter_to_dock` -- there is
no separate disk-side query path any more (that was cli_apply_filters, which
plan F3 removed together with the Compare dock's own identity).

refresh_filter_panel reads the Qt workspace state (traces off the docks) and
hands it to selection.trace_filter.resolve_panel_facets, which decides
what the on-screen facets are built from: the whole Data Pool for a Global
profile's measurement facets (its Calculated columns come from the open docks
unioned with the Result Pool, ADR §1.36), or whatever the focused dock is
actually drawing for a Local one -- a result-content dock offers nothing
special here once its h5 curves are ordinary Traces (ADR §1.38).

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Optional

from PySide6.QtWidgets import QWidget

from core.filter_card_config import FilterCardConfig, duplicate as duplicate_card
from orchestration.trace_filter import build_identity_context, plan_mask_application, save_filter_card
from selection.trace_filter import (
    OfferedFacets, builtin_column_cardinalities_for_global,
    local_card_cardinalities, resolve_card,
    resolve_panel_facets,
)
from session.trace_filter import build_filter_state_snapshot, read_filter_state_snapshot
from gui.workspace.graph_dock import GraphDock
from view_models.trace_filter import identity_for_trace
from selection.source_facets import all_pool_sources

# Key the Filter panel's profile list + Global content is saved under in the
# project's ui_state -- restored once when a project is opened (see
# FilterRoutingHandler.restore_filter_state), never during an ordinary refresh,
# which would otherwise keep overwriting whatever the user has picked live this
# session.
FILTER_STATE_KEY = "compare_filters"


def _identities_for(traces, session) -> list:
    """Every one of `traces` resolved to its own `TraceIdentity`, once, via
    `build_identity_context` (ticket #166)."""
    identity_context = build_identity_context(session)
    return [identity_for_trace(trace, identity_context.sources_by_path, identity_context.result_set_labels)
            for trace in traces]


def _curves_traces(widget) -> list:
    """The traces held on `widget.curves` (ticket #277) -- [] for a widget with
    no `curves` (not a GraphDock) or one whose model has not landed yet."""
    curves = getattr(widget, "curves", None)
    model = curves.model if curves is not None else None
    return list(model.traces) if model is not None else []


class FilterRoutingHandler:
    """
    The one owner of the Filter panel's facets and of the mask they produce on
    every open dock (ADR §1.76, ticket #234). See the module docstring for why
    the panel half and the mask half are one class.
    """

    def __init__(self, app_context, filter_panel, workspace_tabs, explorer_panel,
                 parent_widget: Optional[QWidget] = None):
        self.app_context = app_context
        # A spawned view-only workspace has no Filter panel, and a caller that
        # only drives part of this (a test frame) may have no tabs or explorer
        # either -- every read below tolerates None rather than assuming the
        # whole window is there.
        self.filter_panel = filter_panel
        self.workspace_tabs = workspace_tabs
        self.explorer_panel = explorer_panel
        self.parent_widget = parent_widget

    # =========================================================================
    # MASK
    # =========================================================================

    def apply_active_filter_to_dock(self, dock, *, force: bool = False) -> None:
        """
        Applies the active profile's in-memory mask to `dock`, gated on its own
        last-applied snapshot having actually moved on (R6') unless `force` skips
        that gate -- for callers whose reason to redraw is invisible to the key
        (reapply_active_filter_everywhere below). A SpectrogramDock has no traces
        to mask (ADR §1.7) and is left untouched.

        Every GraphDock gets the same in-memory mask, including a result-content
        dock (ADR §1.30) -- the disk-side query this used to route the Compare dock
        to separately (cli_apply_filters) is gone, along with the identity check
        that picked it out.
        """
        panel = self.filter_panel
        if panel is None or not isinstance(dock, GraphDock):
            return

        context = self.app_context
        identity_context = build_identity_context(context.project_session)
        plan = plan_mask_application(
            panel.selection_store,
            panel.active_profile_id(),
            dock.dock_id,
            showing_all=panel.showing_all(),
            applied_filter_key=dock.curves.applied_mask_key,
            traces=_curves_traces(dock),
            sources_by_path=identity_context.sources_by_path,
            result_set_labels=identity_context.result_set_labels,
            schema=context.pool.schema().master,
            force=force,
        )
        if plan is None:
            return

        for message in plan.messages:
            context.log(message)
        dock.curves.set_trace_filter(plan.predicate, key=plan.key)

    def reapply_active_filter_everywhere(self) -> None:
        """
        Rebuilds every open dock's mask whether or not its key moved.

        For the changes a mask depends on but dock.curves.applied_mask_key cannot see: a
        predicate closes over the metadata schema and the source lookup as they
        were when it was built, so editing the schema leaves every open graph
        filtering by a schema that no longer exists. Deliberately not solved by
        fingerprinting the project into the key -- that would cost a pool-wide
        sweep on every focus change to catch an event the caller already knows
        about (plan rev_01 R3).
        """
        tabs = self.workspace_tabs
        if tabs is None:
            return
        for index in range(tabs.count()):
            self.apply_active_filter_to_dock(tabs.widget(index), force=True)

    # =========================================================================
    # PROJECT STATE
    # =========================================================================

    def restore_filter_state(self) -> None:
        """
        Makes the Filter panel show the current project's saved state: first
        back to clean builtins, then the profile list + Global content saved in
        the project's ui_state, if any (T5). The reset comes first so a project
        that never saved a filter state does not inherit the previous project's
        cards, picks or switches (issue #372). Call exactly once per project
        switch, right after the session holds the new project
        (ProjectDocumentHandler.open_project / new_project) -- never
        from an ordinary refresh, or it would keep stomping on whatever the user
        has picked live this session every time something unrelated refreshes.

        A Local profile's content for a graph dock is not restored here at all --
        it travels on that graph's own TabSpec instead
        (Workspace.restore_open_tabs, same call site as this function),
        which is also where a dock's loaded h5 result-set ids travel
        (ARCHITECTURE_DECISIONS §1.30, plan F5).
        """
        panel = self.filter_panel
        if panel is None:
            return

        panel.reset_to_builtins()

        session = self.app_context.project_session
        saved = session.project.ui_state.get(FILTER_STATE_KEY)
        if not saved:
            return
        state = read_filter_state_snapshot(saved)

        panel.restore_profile_identities(state.profiles)
        panel.selection_store.import_global_selections(state.global_selections)
        panel.set_active_profile_id_from_restore(state.active_profile_id)

        # Not per-profile (one checkbox for the whole panel, see FilterPanel);
        # set directly rather than through the profile restore calls above, and
        # without emitting -- restoring happens while the project is being opened
        # and the pool is rebuilt right afterwards anyway, same reasoning as
        # restore_profile_identities().
        blocked = panel.cb_filter_data_pool.blockSignals(True)
        panel.cb_filter_data_pool.setChecked(state.filter_data_pool)
        panel.cb_filter_data_pool.blockSignals(blocked)

        # Same treatment for the panel-wide "Show all" switch (ADR §1.32) -- one
        # checkbox for the whole panel, restored without emitting.
        panel.set_show_all(state.show_all)

    def _persist_filter_state(self, *, mark_dirty: bool = True) -> None:
        panel = self.filter_panel
        session = self.app_context.project_session

        snapshot = build_filter_state_snapshot(
            filter_data_pool=panel.filters_data_pool(),
            show_all=panel.showing_all(),
            profiles=panel.serialize_profile_identities(),
            global_selections=panel.selection_store.export_global_selections(),
            active_profile_id=panel.active_profile_id(),
        )

        if session.project.ui_state.get(FILTER_STATE_KEY) == snapshot:
            return  # nothing actually changed -- do not spuriously mark the project dirty
        session.project.ui_state[FILTER_STATE_KEY] = snapshot

        # ui_state is cosmetic (core.project_model.NVHProject.ui_state) and worth
        # saving only alongside a project that has a file. On an Untitled one,
        # mark_dirty() has no has_file guard, so ticking the Data Pool filter
        # checkbox alone turned "open the app, look at a folder, leave" into an
        # unsaved-changes prompt -- exactly what ProjectSession promises it will
        # not do.
        if mark_dirty and session.has_file:
            session.mark_dirty()

    # =========================================================================
    # WORKSPACE STATE
    # =========================================================================

    def _focused_dock(self):
        """The dock the workspace tabs currently show, or None (e.g. the startup
        placeholder, or a bare test frame with no workspace tabs at all)."""
        tabs = self.workspace_tabs
        return tabs.currentWidget() if tabs is not None else None

    def _focused_dock_traces(self) -> list:
        """The traces the focused dock is currently drawing, or [] (its model may
        not have landed yet, or there may be no dock at all)."""
        return _curves_traces(self._focused_dock())

    def _open_dock_traces(self) -> list:
        """
        Every trace drawn on any open workspace dock -- what a Global card's
        Calculated-metadata facets are built from (ADR §1.36), where a Local card
        sees only the focused dock. A tab container exposing just `currentWidget`
        (some test doubles) collapses to that one dock.
        """
        tabs = self.workspace_tabs
        if tabs is None:
            return []
        if hasattr(tabs, "count") and hasattr(tabs, "widget"):
            widgets = [tabs.widget(idx) for idx in range(tabs.count())]
        else:
            current = getattr(tabs, "currentWidget", lambda: None)()
            widgets = [current] if current is not None else []

        traces: list = []
        seen: set = set()
        for widget in widgets:
            for trace in _curves_traces(widget):
                if id(trace) not in seen:
                    seen.add(id(trace))
                    traces.append(trace)
        return traces

    def refresh_data_pool_filter(self) -> None:
        """
        Redraws the Data Pool tree so it reflects the current filter selection.

        The only implementation there is: `MainWindowFrame` carried an identical
        one until #234, and the hop through the frame it existed for is what this
        handler drops. A no-op in effect when the Data Pool filter is switched
        off -- the tree works out what to hide from the panel itself (see
        DataPoolPanel._facet_filter), so there is nothing to pass in here.
        """
        explorer = self.explorer_panel
        if explorer is not None:
            explorer.pool_panel.rebuild_tree_view()

    # =========================================================================
    # PANEL
    # =========================================================================

    def refresh_filter_panel(self, *, card_override: FilterCardConfig | None = None) -> None:
        """
        Rebuilds the Filter panel's facets from the active profile's scope (T4):
        Global always reads the whole Data Pool; Local always reads the focused
        dock's own traces -- a dock's content is per-dock (plan's "Filter na
        bežnom grafe je maska, nie query"), and since §1.30 that is true of a
        result-content dock too.

        Since §1.38 this is thin `gui/handlers` glue: read the Qt workspace state
        (traces off the docks, whether the focused dock can take a computation),
        resolve the active card, then hand it all to
        `selection.trace_filter.resolve_panel_facets` -- one `if scope`
        lives there now, not two near-identical branches here. The resolved
        `ResolvedFacets` is passed straight to `populate_facets` (§1.38
        expand--contract batch 2, ticket #59).
        """
        panel = self.filter_panel
        if panel is None:
            return

        context = self.app_context
        session = context.project_session
        schema = context.pool.schema().master

        # Which metadata/Channel/Identity columns this profile's card carries
        # decides the offering (ADR §1.32/§1.33, tickets #41/#42), and since #50
        # also the order, the widget and the column count. A never-configured card
        # of either scope resolves to `Channel` plus the user's Default pins (ADR
        # §1.56 -- no block-kind derivation); a stored card is left verbatim (no
        # refresh-driven writes, §1.27).
        profile_id = panel.active_profile_id()
        scope = "local" if panel.active_profile_scope() != "global" else "global"
        if card_override is not None and card_override.id == profile_id:
            # Configure Filters' Auto apply preview (§1.37): the working card is
            # rendered straight, never written to the project, so Cancel / a no-op /
            # a declined save revert by simply refreshing with no override.
            card = card_override
        else:
            card = resolve_card(session, profile_id, schema)

        focused_identities = _identities_for(self._focused_dock_traces(), session)
        open_dock_identities = _identities_for(self._open_dock_traces(), session)

        facets = resolve_panel_facets(
            scope, card, schema,
            project=session.project,
            pool_sources=all_pool_sources(session.project),
            focused_identities=focused_identities,
            open_dock_identities=open_dock_identities,
        )

        panel.populate_facets(facets)

    def _local_card_cardinalities(self, session, schema):
        """
        The schema-field and built-in column cardinalities Configure Filters shows
        for a Local card -- read off the focused dock's own traces and their
        resolved sources, not the pool (ADR §1.33). Returns (schema_cardinalities,
        builtin_cardinalities), both keyed the same way the pool-wide versions are.
        """
        identities = _identities_for(self._focused_dock_traces(), session)
        return local_card_cardinalities(identities, schema)

    def refresh_and_apply_for_focused_dock(
            self, *, card_override: FilterCardConfig | None = None) -> None:
        """
        Shared tail of the dock-focus-changed and profile-focus-changed triggers
        (T4): both can change which facets belong on screen (a different dock's
        Local content, or a scope flip between Global/Local), so the panel is
        rebuilt first, then the active profile's mask is (re)applied to whichever
        dock now has focus, gated on that dock's own R6' staleness key.

        `card_override` is Configure Filters' Auto apply preview (§1.37): the
        working card is rendered without ever reaching the project, so reverting is
        a plain call with no override.
        """
        dock = self._focused_dock()
        self.refresh_filter_panel(card_override=card_override)
        if dock is not None:
            self.apply_active_filter_to_dock(dock)

    # =========================================================================
    # TRIGGERS
    # =========================================================================

    def dock_focus_changed(self, dock) -> None:
        """
        Wired to workspace_tabs.currentChanged (main_window.py) -- R2'/R6'. Tells
        the Filter panel which dock just got focus, so its own Local tabs show
        that dock's own content, then rebuilds the on-screen facets and catches
        this dock up to the active profile if it was drawn stale.
        """
        panel = self.filter_panel
        if panel is None:
            return
        panel.set_current_dock_id(getattr(dock, "dock_id", None))

        explorer = self.explorer_panel
        result_pool = getattr(explorer, "result_pool_panel", None) if explorer is not None else None
        if result_pool is not None:
            result_pool.set_current_dock(dock)

        self.refresh_and_apply_for_focused_dock()

    def active_profile_focus_changed(self) -> None:
        """Wired to FilterPanel.active_profile_focus_changed -- a deliberate
        profile choice (a tab click, or a deleted/flipped profile's fallback)
        can change which facets are on screen (Global vs Local) the same way a
        dock-focus change can, so it gets the same treatment."""
        self.refresh_and_apply_for_focused_dock()

    def profiles_changed(self) -> None:
        """Wired to FilterPanel.profiles_changed (issue #400) -- a rename,
        delete, scope flip or "+". Writes the card list and the active card
        into the project's ui_state so the edit survives a reopen, and marks a
        titled project dirty (both inside _persist_filter_state, which is a
        no-op when the snapshot did not actually change). Any redraw the edit
        needs already came through active_profile_focus_changed."""
        self._persist_filter_state()

    def active_profile_chosen(self) -> None:
        """Wired to FilterPanel.active_profile_chosen -- a tab click. The
        chosen card is written into ui_state so the next save keeps it, but
        switching tabs is a view choice, not an edit: the project is not
        marked dirty."""
        self._persist_filter_state(mark_dirty=False)

    def profile_duplicated(self, source_profile_id: str, new_profile_id: str) -> None:
        """Wired to FilterPanel.profile_duplicated (ticket #47). The panel has
        already cloned the checked state onto the new profile; this carries the
        other half -- the stored column configuration -- across as a fresh
        FilterCardConfig sharing the new profile's id, and persists the new
        profile into the project's ui_state so it survives a reopen.

        A never-configured source has no stored card: the copy re-derives the same
        default from its scope and dock, so there is nothing to write."""
        session = self.app_context.project_session
        stored = session.project.filter_card_by_id(source_profile_id)
        if stored is not None:
            session.project.put_filter_card(duplicate_card(stored, new_id=new_profile_id))
        self._persist_filter_state()

    def selection_changed(self) -> None:
        """
        A facet edit does not change what facets are on offer, only what is
        checked, so only the focused dock is told to catch up (R6');
        dock_focus_changed catches up any other open dock once it regains
        focus.

        Checking a value is an unsaved change now (ARCHITECTURE_DECISIONS §1.32
        supersedes §1.27's "the selection is cosmetic"). _persist_filter_state
        writes the Global selection through; the mark_dirty below also covers a
        Local tick, whose content never reaches that snapshot. Safe against a
        refresh masquerading as an edit: populate_facets sets every checkbox
        before wiring its signal, so a rebuild never emits selection_changed.
        """
        dock = self._focused_dock()
        if dock is not None:
            self.apply_active_filter_to_dock(dock)
        self._persist_filter_state()
        session = self.app_context.project_session
        if session.has_file:
            session.mark_dirty()

    def toggle_data_pool_filter(self, enabled: bool) -> None:
        """Switches the Data Pool tree's own filter on or off (DataPoolPanel
        reads the active selection directly -- the rebuild just asks it to
        redraw); does not change what the Filter panel's facets offer."""
        context = self.app_context
        self.refresh_filter_panel()
        self.refresh_data_pool_filter()

        self._persist_filter_state()

        context.log(
            "FILTER: Data Pool filtering on -- the pool now shows only what matches these filters."
            if enabled else
            "FILTER: Data Pool filtering off -- the pool shows everything again."
        )

    def toggle_show_all(self, enabled: bool) -> None:
        """Wired to FilterPanel.show_all_toggled -- the panel-wide switch that
        blanks every mask and the Data Pool narrowing at once (ADR §1.32).

        Every open dock is force-swept, not just the focused one: showing_all() is
        in dock.curves.applied_mask_key, but a dock the user never focused has no
        stale key to compare and would otherwise keep its mask until its next focus."""
        context = self.app_context
        self.reapply_active_filter_everywhere()
        self.refresh_filter_panel()
        self.refresh_data_pool_filter()
        self._persist_filter_state()
        context.log(
            "FILTER: Show all on -- every graph and the Data Pool show everything; "
            "your checked values are kept."
            if enabled else
            "FILTER: Show all off -- filtering is active again."
        )

    def open_filter_field_selection(self) -> None:
        """
        Configure Filters: which columns sit on the card you are standing on
        (ARCHITECTURE_DECISIONS §1.32, tickets #41/#42). It configures the active
        profile's card, not the app-wide schema -- Global and Local can carry
        different columns. `usable_as_filter` still decides what the dialog is
        allowed to list (Metadata and Filter Settings' job), and still feeds the
        batch resolver; this only moves what "on the card" means into the project's
        own `filter_cards`. The dialog also needs the project itself (not just the
        schema) to show each column's live pool-wide value count and grey out a
        low-cardinality one with a reason (ticket #42), read from the same universe
        the matching facet offers values from: the focused dock for a Local card
        (§1.33), the whole Data Pool plus the open docks unioned with the Result
        Pool for a Global one (§1.36).
        """
        from gui.dialogs.filter_field_selection_dialog import FilterFieldSelectionDialog

        context = self.app_context
        session = context.project_session
        schema = context.pool.schema().master
        panel = self.filter_panel

        profile_id = panel.active_profile_id()

        # A Local card offers only what the focused dock draws, so its counts and
        # "cannot narrow" verdicts are read off that dock's traces, not the pool
        # (ADR §1.33). A never-configured card of either scope resolves the same way
        # now -- `Channel` plus the user's Default pins, no block-kind derivation
        # and no growing (ADR §1.56).
        schema_cardinalities = builtin_cardinalities = None
        if panel.active_profile_scope() != "global":
            schema_cardinalities, builtin_cardinalities = self._local_card_cardinalities(
                session, schema
            )
        else:
            # A Global card keeps the pool-wide schema-field read, but its Calculated
            # columns count the graph cards plus the Result Pool, not result sets
            # alone (ADR §1.36) -- the same universe refresh_filter_panel offers
            # values from, so a "(0)" here means the column really would narrow
            # nothing.
            open_dock_identities = _identities_for(self._open_dock_traces(), session)
            builtin_cardinalities = builtin_column_cardinalities_for_global(
                session.project, open_dock_identities
            )
        card = resolve_card(session, profile_id, schema)

        # Auto apply (§1.37): while the dialog is open, each edit is previewed on the
        # focused dock through the normal apply path -- but the working card is
        # passed as a transient override, never written to the project. Reverting on
        # Cancel, a no-op edit or a declined save is then just a refresh with no
        # override, since the project was never touched.
        def _preview_card(working_card) -> None:
            self.refresh_and_apply_for_focused_dock(card_override=working_card)

        dialog = FilterFieldSelectionDialog(
            schema, session.project, self.parent_widget,
            settings=getattr(context, "settings", None),
            card=card,
            schema_cardinalities=schema_cardinalities,
            builtin_cardinalities=builtin_cardinalities,
            on_live_change=_preview_card,
        )
        try:
            accepted = dialog.exec()
            updated = dialog.result_card() if accepted else card
        finally:
            # Parented to the main window, so nothing else would ever destroy it.
            dialog.deleteLater()

        if not accepted or updated == card:
            # Cancel, or a no-op edit (possibly previewed then undone): a no-op must
            # not prompt for a project path or dirty the project. Drop any preview
            # override and redraw from the untouched project.
            self.refresh_and_apply_for_focused_dock()
            return

        # A card configuration is a project decision (§1.32), so it needs a project
        # file to live in -- same gate the metadata schema editor uses.
        from gui.handlers.project_document import ensure_project_saved
        if not ensure_project_saved(context, self.parent_widget):
            context.log("SYSTEM: Filter configuration cancelled -- it needs a saved project to live in.")
            self.refresh_and_apply_for_focused_dock()  # drop the preview (§1.37)
            return

        for message in save_filter_card(session, updated):
            context.log(f"ERROR: {message}")

        self.refresh_and_apply_for_focused_dock()
