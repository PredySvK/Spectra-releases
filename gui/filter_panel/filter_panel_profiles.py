# =====================================================================
# FILE: gui/filter_panel/filter_panel_profiles.py
# =====================================================================
"""
Profile/tab lifecycle for FilterPanel: the tab bar above the facets, which
profile is active app-wide, which dock has focus, and the panel-wide "Show
all" / "Filter Data Pool" switches. See filter_panel.py's module docstring
for the full picture (ADR §1.28/§1.37/§1.68, ticket #66/#177) -- this mixin
is the Qt-reacting half of session.trace_filter.FilterProfileRegistry, kept
out of filter_panel.py itself only because it is a large, mostly
self-contained slice of that class's behaviour (ticket #148 layering pass).

Mixed into FilterPanel rather than built as a collaborator: every method here
still reaches into the same widgets (`self._tab_bar`, `self.cb_show_all`, ...)
and the same profile registry that FilterPanel's __init__ sets up -- splitting
that would cost more indirection than the file-length problem it would solve.
"""
from typing import Any, Callable, List, Optional, Set

from PySide6.QtWidgets import QInputDialog, QMenu

from core.project_model import FilterProfile
from session.trace_filter import BUILTIN_LOCAL_ID, OWNER_FROM_FOCUS

_NEW_PROFILE_NAME = "New Filter"


class ProfileTabsMixin:
    """Mixed into FilterPanel -- see module docstring."""

    def _init_profile_state(self) -> None:
        self._tab_order: List[str] = []

    # ---- profiles: the tab bar's data model --------------------------------

    # Read-only mirrors onto self._profile_registry -- most of this widget's
    # existing code reads these three names directly; keeping them as
    # properties (rather than rewriting every call site) means a stray
    # assignment anywhere outside the registry itself now raises instead of
    # silently drifting the two apart.
    @property
    def _profiles(self) -> List[FilterProfile]:
        return self._profile_registry.profiles

    @property
    def _active_profile_id(self) -> Optional[str]:
        return self._profile_registry.active_profile_id

    @property
    def _current_dock_id(self) -> Optional[str]:
        return self._profile_registry.current_dock_id

    def _active_profile(self) -> FilterProfile:
        return self._profile_registry.active_profile()

    def _profile_by_id(self, profile_id: Optional[str]) -> Optional[FilterProfile]:
        return self._profile_registry.profile_by_id(profile_id)

    def active_profile_scope(self) -> str:
        """"global" or "local" -- which universe refresh_filter_panel builds the
        facets from (ARCHITECTURE_DECISIONS §1.30 for Local, §1.36 for Global)."""
        return self._active_profile().scope

    def current_dock_id(self) -> Optional[str]:
        return self._profile_registry.current_dock_id

    def active_profile_id(self) -> Optional[str]:
        """Public accessor for gui.handlers.filter_routing -- which profile's
        selection to read for a dock that may not be the one in focus."""
        return self._profile_registry.active_profile_id

    @property
    def selection_store(self):
        """The Qt-free checked-state half (ADR §1.39), read-only for outside
        callers (ADR §1.51): gui.handlers.filter_routing and
        gui.workspace.workspace go straight to it -- paired with
        active_profile_id() -- to resolve, export and import a dock's selection,
        rather than through a forwarding method per call. Mutation still happens
        only through the store's own methods."""
        return self._selection_store

    def _activate_profile(self, profile_id: str, emit: bool = True, replay: bool = True) -> None:
        """
        The only place the active profile id changes -- a tab click, a
        freshly added profile, the fallback once the active one is removed,
        or a restore (`emit=False`: the project is still being opened,
        nothing downstream should react yet, matching restore_selection()).
        `replay=False` suppresses replaying the last facets during a dock-focus
        change (ADR §1.92, #401), where the newly focused dock will be
        populated with its own actual facets immediately afterwards.
        App-wide: unlike the S1-S4 design this replaces, there is no per-dock
        pointer to update. A dock-focus change calls this only to apply the
        §1.37 fallback / restore (see set_current_dock_id), never to track a
        per-dock tab selection.
        """
        if not self._profile_registry.set_active_profile_id(profile_id):
            return
        self._update_data_pool_checkbox_enabled()
        self._update_profile_scope_checkbox()
        if replay:
            self._replay_last_populate()
        if emit:
            self.active_profile_focus_changed.emit()

    def _update_data_pool_checkbox_enabled(self) -> None:
        # Available for either scope now: a Global filter builds its facets from
        # the pool anyway, but "Filter Data Pool" is about narrowing the Data
        # Pool *tree* to the matching measurements, which is a separate visible
        # effect the user may want under a Global profile too.
        self.cb_filter_data_pool.setEnabled(not self.cb_show_all.isChecked())
        self.cb_filter_data_pool.setToolTip(
            "Narrows the Data Pool tree to the measurements and channels matching these filters.\n"
            "While this is on, the pool's own measurements also contribute filter values, so the "
            "filters work without any result set having been computed yet."
        )

    def _update_profile_scope_checkbox(self) -> None:
        """Keeps cb_profile_scope in sync with the active profile -- checked
        for "global", and hidden entirely for either builtin (their scope is
        fixed, so a disabled checkbox would just be noise; same rule as the tab
        bar's context menu not offering "Make Global"/"Make Local" for them).
        Disabled when "global" and no dock has focus: there is no dock to own
        it if flipped to local (#404)."""
        profile = self._active_profile()
        has_dock = self._current_dock_id is not None
        can_change_scope = not profile.builtin and (profile.scope != "global" or has_dock)
        blocked = self.cb_profile_scope.blockSignals(True)
        self.cb_profile_scope.setChecked(profile.scope == "global")
        self.cb_profile_scope.setEnabled(can_change_scope)
        self.cb_profile_scope.setVisible(not profile.builtin)
        self.cb_profile_scope.blockSignals(blocked)
        if profile.builtin:
            tooltip = "The two fixed tabs cannot change scope."
        elif profile.scope == "global" and not has_dock:
            tooltip = "Focus a graph to make this filter local to it."
        else:
            tooltip = (
                "Whether this filter is shared across every graph (Global) or specific to whichever "
                "graph currently has focus (Local) -- same as the tab's right-click menu."
            )
        self.cb_profile_scope.setToolTip(tooltip)

    def _on_scope_checkbox_toggled(self, checked: bool) -> None:
        if self._active_profile().builtin:
            return
        self.set_profile_scope(self._active_profile_id, "global" if checked else "local")

    def set_current_dock_id(self, dock_id: Optional[str]) -> None:
        """
        Tells the panel which dock currently has focus -- wired to real dock
        focus via gui.handlers.filter_routing.FilterRoutingHandler.dock_focus_changed
        (workspace_tabs.currentChanged).

        Changes self._active_profile_id only via the fallback / restore rules
        in the module docstring (ADR §1.37): the app-wide invariant (§1.28)
        still holds, the per-dock dict is only a memory for restoring a dock's
        own custom Local card on return.

        Does not replay the last facets on focus change (#401): the real refresh
        with the newly focused dock's actual facets follows immediately via
        refresh_and_apply_for_focused_dock(). Replaying here would seed the new
        dock with the previous dock's facets and break §1.29 defaulting.
        """
        if dock_id == self._profile_registry.current_dock_id:
            return
        self._profile_registry.set_current_dock_id(dock_id)

        self._resolve_active_for_focused_dock()
        # A custom Local card's tab visibility is per dock now (§1.37), so the
        # bar itself is rebuilt on focus change -- not just the facets behind it.
        self._rebuild_tab_bar()
        self._update_add_profile_enabled()
        self._update_profile_scope_checkbox()

    def _resolve_active_for_focused_dock(self) -> None:
        """Pick the active card for the dock that just gained focus (ADR §1.37,
        ticket #66) -- session.trace_filter.FilterProfileRegistry.resolve_active_for_focused_dock
        decides which; this only reacts if that names a different card."""
        target = self._profile_registry.resolve_active_for_focused_dock()
        if target is not None:
            self._activate_profile(target, replay=False)

    def _add_profile(self, name: str, scope: str = "local", make_active: bool = False,
                     builtin: bool = False, profile_id: Optional[str] = None,
                     owner_dock_id: Any = OWNER_FROM_FOCUS) -> FilterProfile:
        profile = self._profile_registry.add_profile(
            name, scope=scope, builtin=builtin, profile_id=profile_id, owner_dock_id=owner_dock_id)
        # Activate (if applicable) before rebuilding the tab bar, not after --
        # _rebuild_tab_bar positions the widget's current index from
        # self._active_profile_id, so rebuilding first would leave the widget
        # pointing at the old tab while the internal pointer already moved on.
        if make_active or self._active_profile_id is None:
            self._activate_profile(profile.id)
        self._rebuild_tab_bar()
        return profile

    def set_profile_scope(self, profile_id: str, new_scope: str) -> None:
        """
        Flips a custom profile's scope -- the tab bar's context menu's "Make
        Global"/"Make Local" (not offered for either builtin, see
        _on_tab_bar_context_menu). session.trace_filter.FilterProfileRegistry
        carries the profile's current checked state over to its new storage
        location in the selection store (keyed by the now-focused dock)
        rather than starting it over empty, so flipping never looks like it
        discarded a pick.
        """
        if not self._profile_registry.set_profile_scope(profile_id, new_scope):
            if profile_id == self._active_profile_id:
                self._update_profile_scope_checkbox()
            return
        is_active = profile_id == self._active_profile_id
        if is_active:
            self._update_data_pool_checkbox_enabled()
            self._update_profile_scope_checkbox()
        self._rebuild_tab_bar()
        if is_active:
            # The active card's facets now come from the other universe
            # (Global vs Local), so the focused dock needs the same redraw a
            # tab click gets.
            self.active_profile_focus_changed.emit()
        self.profiles_changed.emit()

    def _update_add_profile_enabled(self) -> None:
        """Greys the "+" button out while no graph has focus (§1.37): a fresh
        custom Local card is owned by the focused dock, and there is no dock to
        own it."""
        has_focus = self._current_dock_id is not None
        self._btn_add_profile.setEnabled(has_focus)
        self._btn_add_profile.setToolTip(
            "Add a new filter profile."
            if has_focus else
            "Focus a graph to add a filter for it."
        )

    def _on_add_profile_clicked(self) -> None:
        # Local by default -- a custom filter starts out specific to the
        # graph the user is looking at; "Make Global" is one context-menu
        # click (or the cb_profile_scope checkbox) away once they decide it
        # should apply everywhere.
        profile = self._add_profile(_NEW_PROFILE_NAME, scope="local", make_active=True)
        # Prompt for a name right away -- "New Filter" is a placeholder, not
        # a name anyone wants to keep, and renaming it later means finding
        # the tab's double-click or context menu again.
        self._on_tab_bar_double_clicked(self._tab_order.index(profile.id))
        # The new card is an edit even when the name prompt was cancelled.
        self.profiles_changed.emit()

    def rename_profile(self, profile_id: str, new_name: str) -> None:
        if not self._profile_registry.rename_profile(profile_id, new_name):
            return
        self._rebuild_tab_bar()
        self.profiles_changed.emit()

    def remove_profile(self, profile_id: str) -> None:
        """
        Refuses to remove a builtin -- "Global" and "Local" always exist.
        Removing the active custom profile falls back to the "Local" builtin
        specifically (not just "whatever is first"):
        it is always there to land on, the same way closing a custom view
        returns you to a default one.
        """
        was_active = self._profile_registry.remove_profile(profile_id)
        if was_active is None:
            return  # unknown profile or a builtin -- remove_profile() was a no-op
        if was_active:
            self._activate_profile(BUILTIN_LOCAL_ID)
        self._rebuild_tab_bar()
        self.profiles_changed.emit()

    def _drop_owned_local_cards(self, is_orphan: Callable[[Optional[str]], bool]) -> None:
        """Removes every custom Local card whose `owner_dock_id` satisfies
        `is_orphan` (and with it, via FilterProfileRegistry.remove_profile,
        its selections and offerings). The two callers below differ only in
        that predicate."""
        if self._profile_registry.drop_owned_local_cards(is_orphan):
            self._activate_profile(BUILTIN_LOCAL_ID)
        self._rebuild_tab_bar()

    def forget_dock(self, dock_id: str) -> None:
        """
        Drops the custom Local cards owned by `dock_id` -- called from
        gui.workspace.workspace.Workspace.close_specific_tab
        when a GraphDock closes (§1.37). No open dock carries that id any
        more, so its cards would otherwise linger forever, invisible.
        """
        self._drop_owned_local_cards(lambda owner: owner == dock_id)
        # The dock is gone, so its restore memory is dead weight -- and
        # _drop_owned_local_cards already pruned any entries that pointed at
        # its now-removed cards.
        self._profile_registry.drop_dock_memory(dock_id)

    def prune_orphan_dock_cards(self, open_dock_ids: Set[str]) -> None:
        """
        Drops custom Local cards whose owner dock is not among `open_dock_ids`
        -- called once after a project's workspace has been restored
        (gui.handlers.project_document.ProjectDocumentHandler.open_project). A
        restored dock takes back the id it was saved with (§1.94), so only a
        card whose owner did not come back -- its recipe was skipped, or the
        project predates saved dock ids -- is silently discarded (§1.37).
        """
        open_ids = set(open_dock_ids)
        self._drop_owned_local_cards(lambda owner: owner not in open_ids)

    def duplicate_profile(self, source_profile_id: str) -> Optional[str]:
        """
        Adds a profile that copies `source_profile_id`'s scope, column
        configuration and checked state, and makes it active -- the tab bar
        context menu's "Duplicate" (ticket #47). The copy is never `builtin`,
        even when the source is: it can be renamed and deleted like any custom
        profile, while "Global" and "Local" themselves stay protected.

        The column configuration lives in the project, not on this panel, so
        the copy of that half is left to gui.handlers.filter_routing via
        `profile_duplicated`; the checked state is cloned here, before the copy
        is activated, so the redraw the activation triggers reads a whole
        profile rather than half of one.
        """
        # Added inactive, then activated only after profile_duplicated has run:
        # its handler puts the copied FilterCardConfig into the project, and the
        # redraw _activate_profile triggers must see that card, not re-derive a
        # default one.
        copy = self._profile_registry.duplicate_profile_identity(source_profile_id)
        if copy is None:
            return None
        # Clone the source's FilterSelections, offerings and seen marks under
        # the same dock keys before the copy is activated, so the redraw the
        # activation triggers reads a whole profile rather than half of one
        # (ADR §1.39, §1.44).
        self._selection_store.copy_selections(source_profile_id, copy.id)
        self.profile_duplicated.emit(source_profile_id, copy.id)

        self._activate_profile(copy.id)
        self._rebuild_tab_bar()
        return copy.id

    def _visible_profiles(self) -> List[FilterProfile]:
        """
        The profiles whose tabs show for the focused dock, in tab order
        (§1.37): the two builtins, then every custom Global card, then only
        those custom Local cards owned by the focused dock. A custom Local
        card whose `owner_dock_id` is some other dock is simply absent from
        the bar until that dock has focus again.
        """
        return self._profile_registry.visible_profiles()

    def _rebuild_tab_bar(self) -> None:
        """
        Redraws the tab bar from _visible_profiles() -- a custom Local card's
        tab shows only for its owner dock now (§1.37); everything else is
        app-wide. The active profile is always visible by the time this runs --
        set_current_dock_id resolves the fallback / restore first (ticket #66).
        """
        blocked = self._tab_bar.blockSignals(True)
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(0)

        visible = self._visible_profiles()
        self._tab_order = [p.id for p in visible]
        for profile in visible:
            self._tab_bar.addTab(profile.name)

        if self._active_profile_id in self._tab_order:
            self._tab_bar.setCurrentIndex(self._tab_order.index(self._active_profile_id))
        self._tab_bar.blockSignals(blocked)

    def _on_tab_bar_current_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._tab_order):
            return
        new_active_id = self._tab_order[index]
        if new_active_id == self._active_profile_id:
            return
        self._activate_profile(new_active_id)
        self.active_profile_chosen.emit()

    def _on_tab_bar_double_clicked(self, index: int) -> None:
        if index < 0 or index >= len(self._tab_order):
            return
        profile_id = self._tab_order[index]
        profile = next(p for p in self._profiles if p.id == profile_id)
        new_name, accepted = QInputDialog.getText(self, "Rename Filter", "Name:", text=profile.name)
        if accepted:
            self.rename_profile(profile_id, new_name)

    def _on_tab_bar_context_menu(self, pos) -> None:
        index = self._tab_bar.tabAt(pos)
        if index < 0 or index >= len(self._tab_order):
            return
        profile_id = self._tab_order[index]
        profile = self._profile_by_id(profile_id)

        menu = QMenu(self)
        action_rename = menu.addAction("Rename…")
        action_duplicate = menu.addAction("Duplicate")
        action_scope = None
        action_delete = None
        if not profile.builtin:
            action_scope = menu.addAction("Make Local" if profile.scope == "global" else "Make Global")
            if profile.scope == "global" and self._current_dock_id is None:
                action_scope.setEnabled(False)
            action_delete = menu.addAction("Delete")
        chosen = menu.exec(self._tab_bar.mapToGlobal(pos))
        if chosen is action_rename:
            self._on_tab_bar_double_clicked(index)
        elif chosen is action_duplicate:
            self.duplicate_profile(profile_id)
        elif action_scope is not None and chosen is action_scope:
            self.set_profile_scope(profile_id, "local" if profile.scope == "global" else "global")
        elif action_delete is not None and chosen is action_delete:
            self.remove_profile(profile_id)

    def _replay_last_populate(self) -> None:
        """Re-renders the facet groups' checked state for the now-active profile."""
        if self.facet_grid.last_facets is not None:
            self.populate_facets(self.facet_grid.last_facets, _is_replay=True)

    # ---- panel-wide switches: "Show all" / "Filter Data Pool" -------------

    def filters_data_pool(self) -> bool:
        return self.cb_filter_data_pool.isChecked()

    def showing_all(self) -> bool:
        """Whether "Show all" is on -- every mask and the Data Pool narrowing
        are off, but the checked values are all still remembered."""
        return self.cb_show_all.isChecked()

    def set_show_all(self, enabled: bool, *, emit: bool = False) -> None:
        """Set the "Show all" switch from a restore. `emit=False` matches
        restore_profile_identities(): the project is still opening and the sweep
        over open docks happens right afterwards anyway."""
        blocked = self.cb_show_all.blockSignals(not emit)
        self.cb_show_all.setChecked(bool(enabled))
        self.cb_show_all.blockSignals(blocked)
        self._apply_show_all_enabled_state()

    def _on_show_all_toggled(self, enabled: bool) -> None:
        self._apply_show_all_enabled_state()
        self.show_all_toggled.emit(enabled)

    def _apply_show_all_enabled_state(self) -> None:
        """Grey out the cards and the two narrowing controls while "Show all"
        is on -- their checked state is untouched, disabling only stops a
        click that would have no effect until the switch is flipped back."""
        suppressed = self.cb_show_all.isChecked()
        self.facet_grid.set_facets_enabled(not suppressed)
        self.cb_filter_data_pool.setEnabled(not suppressed)

    # ---- persisting/restoring profiles + their selections (T5) -------------

    def serialize_profile_identities(self) -> List[dict]:
        """
        Custom profiles' identity only, JSON-safe -- the two builtins are
        recreated fresh by __init__ every time rather than round-tripped,
        since their identity (id, name, scope) never changes. No selection
        here: a Global profile's content comes from
        selection_store.export_global_selections(), a Local one's from whichever
        TabSpec holds it -- see the module docstring.
        """
        return self._profile_registry.serialize_profile_identities()

    def reset_to_builtins(self) -> None:
        """
        Back to a freshly built panel -- the two builtins, nothing checked,
        "Local" active, "Filter Data Pool" and "Show all" off -- so the next
        project starts clean (issue #372). Called by
        gui.handlers.filter_routing.restore_filter_state before it layers a
        saved state on top. Never emits, like the restore calls it precedes.
        """
        self._profile_registry.reset_to_builtins()
        blocked = self.cb_filter_data_pool.blockSignals(True)
        self.cb_filter_data_pool.setChecked(False)
        self.cb_filter_data_pool.blockSignals(blocked)
        self.set_show_all(False)
        self._activate_profile(BUILTIN_LOCAL_ID, emit=False)
        self._rebuild_tab_bar()

    def restore_profile_identities(self, raw_profiles: List[dict]) -> None:
        """
        Adds back the custom profiles (identity only) from a saved list
        (gui.handlers.filter_routing.restore_filter_state, called once right
        after a project opens -- never on an ordinary refresh) alongside the two
        builtins __init__ always creates. No-op if nothing was saved. Call
        before selection_store.import_global_selections() /
        import_local_selections_for_dock(): both need the profile to already
        exist to key into. Signals are not emitted here: the project is still
        being opened, nothing downstream should react yet.
        """
        self._profile_registry.restore_profile_identities(raw_profiles)
        self._rebuild_tab_bar()

    def set_active_profile_id_from_restore(self, profile_id: Optional[str]) -> None:
        """
        Restores which tab was active app-wide, falling back to the Local
        builtin when `profile_id` names no known profile -- an older save's
        differently-shaped pointer, or simply nothing saved. Call after
        restore_profile_identities() so custom profiles are already
        registered. Never emits (matches restore_profile_identities()): the
        project is still being opened.
        """
        target = self._profile_registry.resolve_restore_target(profile_id)
        self._activate_profile(target, emit=False)
        self._rebuild_tab_bar()
