# =====================================================================
# FILE: gui/filter_panel/filter_panel.py
# =====================================================================
"""
Filter panel: the faceted filter picker docked next to the File Explorer.

What it draws is one Filter card (core.filter_card_config.FilterCardConfig,
ARCHITECTURE_DECISIONS §1.32): a flat list of columns in the card's own order,
spread over the card's 2 or 3 columns, each drawn with the widget the card
gives it -- a checkbox list or a multi-select summary button, or a min..max
range when the field's kind says so (§1.34: the kind picks the predicate
family, the card only picks a rendering inside it). The four sections
(Identity / Raw / Excel / Calculated) exist in Configure Filters only; here
there is one list. populate_facets() without a card falls back to the fixed
single-column order the panel drew before ticket #50.

Builds and displays the facets computed by selection.source_facets --
from the whole Data Pool for a Global profile, or from whatever the focused
dock is actually drawing for a Local one (selection.trace_filter.
facets_from_traces, ARCHITECTURE_DECISIONS §1.30) -- one group box per
opted-in metadata field (opted in from Metadata and Filter Settings' "Use as
Filter" column; this panel's own "Configure Filters…" can only narrow that
set further, not opt a new field in), a Channel group (opt-in exclusively
through "Configure Filters…", since Channel has no row in Metadata and Filter
Settings), and an Order group -- both read straight off whatever traces are on
a dock (selection.trace_filter.facets_from_traces), a result-content
dock's included, no separate Compare-only path any more. A Parameter Set
group (io_modules.parameter_sets) existed for the pre-§1.30 Compare tab's own
project-wide selection; deriving it from a dock's loaded traces the same way
is plan F3's follow-up (F4), not done yet.

The checked state of every facet lives here, not just in the checkboxes --
populate_facets() tears down and rebuilds the widgets on every call (facets
change whenever the checked result sets change), and without remembering
what was checked independently of the widgets, every rebuild would silently
reset the user's picks. This is also what makes restore across a reopen
possible: gui.handlers.filter_routing.restore_filter_state seeds the
remembered state once from the project's saved ui_state (via
selection_store.import_global_selections), and every future rebuild
pre-checks from it same as a live session would.

Remembering more than is on screen is the point, but it is also the trap: a
narrower scope offers fewer facet values, and the picks left over from the
wider one used to keep filtering from behind a group box that no longer
existed. So the panel also records what the last populate_facets() actually
offered, and every get_selected_* reading narrows the remembered state to
that -- while _persist_filter_state still writes all of it through
(selection_store.export_global_selections), so widening the scope again
brings the old picks back (BUGS.md F1 / F2).

The panel holds a list of named core.project_model.FilterProfile, shown as
tabs above the facets (plus a "+" button to add a custom one) -- see
plans/2026-09-05_filtre-maska-nad-kazdym-grafom.md T1. Two fixed tabs always
exist -- "Global" (global scope) and "Local" (local scope) -- and custom ones
can be added, renamed, deleted and flipped between the two scopes (tab
right-click menu, or the cb_profile_scope checkbox next to "Filter Data
Pool"; that checkbox is hidden for the two fixed tabs, whose scope cannot
change). Exactly one profile is
active *app-wide* at a time: unlike the S1-S4 design this replaces, picking a
tab is not a per-dock choice. A dock-focus change leaves it alone *unless*
the active card is not visible for the new dock (a custom Local card owned
by the dock just left): then it falls back to the "Local" builtin, and a
per-dock memory remembers the card so returning focus to its owner dock
restores it without a manual click (ADR §1.37, ticket #66). That memory is a
restore memory, not a second active pointer -- §1.28's "exactly one active
card app-wide" still holds.

The profile list, the active pointer, the focused-dock id and that per-dock
restore memory are all Qt-free, so they live in
session.trace_filter.FilterProfileRegistry (ADR §1.68 / #177), held here as
self._profile_registry. This panel calls it and reacts on the Qt side (tab
bar, checkboxes, signals) -- `self._profiles` / `self._active_profile_id` /
`self._current_dock_id` below are read-only properties onto it, kept so the
bulk of this file did not need rewriting call site by call site.

Which tabs are *shown*, though, is per dock (ADR §1.37): a custom "local"
card carries owner_dock_id and its tab appears only while that dock has focus
(_visible_profiles / _rebuild_tab_bar, re-run from set_current_dock_id). The
two builtins and every custom "global" card stay app-wide. The "+" button is
disabled while no graph has focus -- a fresh custom local card would have no
owner (_update_add_profile_enabled).

What differs by dock is the *content* behind a "local" tab, not which tab is
selected: the five `checked_*` fields (now core.project_model.FilterSelection)
live in one of two dicts owned by self._selection_store (ADR §1.39, the Qt-free
state half) -- one FilterSelection shared by every dock for a "global" card, one
per (card, dock) for "local" -- rather than on the profile itself.
`self._sel` (FacetGrid.filter_selection) is the one property every facet
method reads and mutates its `checked_*` fields through, resolving to whichever selection
self._active_profile_id + self._current_dock_id currently name
(store.active_selection). The store is told
each card's scope by _add_profile / set_profile_scope / remove_profile; it is
stateless about which card is active. `_offered_*` stays panel-level -- only one
selection is ever on screen at once. Which sources a profile's facets are
built from -- all_pool_sources() for a Global card's measurement facets (its
Calculated columns come from the open docks plus the Result Pool, ADR §1.36),
the focused dock's own traces for Local (ARCHITECTURE_DECISIONS §1.30) -- is
decided by gui.handlers.filter_routing.refresh_filter_panel, via
active_profile_scope() below.

set_current_dock_id() re-renders the on-screen facets whenever the focused
dock changes (a "local" tab's content may differ for the new dock). It changes
self._active_profile_id only through _activate_profile(), and only when the
active card is not visible for the new dock (fall back to "Local") or the new
dock has a remembered custom Local card to restore (ADR §1.37). A tab click, a
freshly added/removed profile, or restoring a saved list also go through
_activate_profile(). gui.handlers.filter_routing.apply_active_filter_to_dock is what
actually turns the active profile into a redraw on a given dock -- the same
in-memory mask for every dock now (T4); this panel just tracks and exposes
the selection it reads. The "did this dock
already see this content" bookkeeping that used to live here as
_last_applied_snapshot now lives on the dock's curves (dock.curves.applied_mask_key) --
state bound to a dock's own lifetime, not the panel's.

The store itself is reached from outside through the read-only `selection_store`
property (ADR §1.51): gui.handlers.filter_routing and
gui.workspace.workspace resolve the active profile's selection for an
arbitrary dock id -- store.active_selection(panel.active_profile_id(), dock_id),
unlike `self._sel` below which always resolves against self._current_dock_id --
to build/compare a mask for a dock that is not necessarily in focus, and to
export/import a dock's Local content across a save/reopen.

Persistence (T5): identity and Global content are the only pieces that live in
gui.handlers.filter_routing's FILTER_STATE_KEY -- serialize_profile_identities()/
restore_profile_identities() round-trip custom profiles' (id, name, scope) only,
and selection_store.export_global_selections()/import_global_selections() round-trip
every Global-scope profile's one shared FilterSelection. A Local profile's content is
per-dock and travels with the dock's own recipe instead
(session.open_tabs.TabSpec.filter_selections,
selection_store.export_local_selections_for_dock()/import_local_selections_for_dock())
-- the recipe and its Local content travel together. A result-content dock
(ARCHITECTURE_DECISIONS
§1.30) has no TabSpec of its own yet (deferred to plan F5) -- its own Local
content is simply not restored across a save/reopen for now.

Implementation-wise the class below is split in two (ticket #148 layering
pass): this file keeps the module docstring above, __init__, init_ui and the
facet forwarders; gui.filter_panel.filter_panel_profiles.ProfileTabsMixin,
mixed in, carries the profile/tab lifecycle and the "Show all"/"Filter Data
Pool" switches. The facets themselves -- Configure, populate_facets, every
per-family `_build_*_group` builder and the get_selected_* readers -- are a
collaborator, gui.filter_panel.facet_grid.FacetGrid (`self.facet_grid`, #460),
so the Selection editor can draw the same grid over its own store (ADR
§1.131). The panel hands it self._selection_store and a key that follows the
active profile and the focused dock.
"""
from PySide6.QtCore import Qt, Signal
from typing import Dict, List

from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QPushButton, QTabBar, QVBoxLayout, QWidget,
)

from session.trace_filter import BUILTIN_GLOBAL_ID, BUILTIN_LOCAL_ID, FilterProfileRegistry, FilterSelectionStore

from core.models import ChannelIdentity
from core.project_model import FilterSelection
from selection.trace_filter import OfferedFacets, PoolQuery, ResolvedFacets

from gui.filter_panel.facet_grid import FacetGrid
from gui.filter_panel.filter_panel_profiles import ProfileTabsMixin


class FilterPanel(ProfileTabsMixin, QWidget):
    """Rebuilt from scratch on every populate_facets() call -- see module docstring for why checked state is
    tracked independently of the widgets rather than read back from them."""

    selection_changed = Signal()

    # Fired whenever self._active_profile_id changes (_activate_profile) --
    # a tab click, a freshly added/removed profile, or a restore. gui.handlers
    # .filter_routing listens for this to redraw the focused dock when that
    # choice was made while it already had focus (R6').
    active_profile_focus_changed = Signal()

    # Whether the facets below also narrow the Data Pool tree. Its own signal
    # rather than selection_changed: turning it on repopulates the pool tree,
    # not just the facets already on screen.
    data_pool_filter_toggled = Signal(bool)

    # Whether the panel-wide "Show all" switch was just flipped. gui.handlers
    # .filter_routing listens for this to blank (or restore) the mask on every
    # open dock and the Data Pool narrowing at once.
    show_all_toggled = Signal(bool)

    # A card was duplicated from its tab's context menu -- (source id, new id).
    # The panel side (a copy of the checked state) is already done by the time
    # this fires; gui.handlers.filter_routing listens for it to carry the other
    # half across -- the stored FilterCardConfig, which lives in the project,
    # not here -- and to persist the new profile into the project's ui_state.
    profile_duplicated = Signal(str, str)

    # The user edited the card list -- a rename, delete, scope flip or "+"
    # (issue #400). gui.handlers.filter_routing listens for this to persist the
    # profiles into the project's ui_state. Never fired by a restore or by a
    # dock-focus change's §1.37 fallback / restore: those are refreshes, not edits.
    profiles_changed = Signal()

    # The user clicked another card's tab. Remembered in the project's ui_state
    # so it rides along with the next save, but it is a view choice, not an
    # edit -- it never marks the project unsaved on its own.
    active_profile_chosen = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_profile_state()

        # The Qt-free checked-state half (ADR §1.39): one shared FilterSelection
        # per profile for "global", one per (profile, dock) for "local" --
        # lazily created on first access (store.active_selection).
        self._selection_store = FilterSelectionStore()

        # The list of filter profiles (two fixed builtins, plus any custom
        # ones), which one is active app-wide -- one pointer, not a per-dock
        # choice, see the module docstring for why T1 replaced the S1-S4
        # two-pointer resolution with this -- which dock has focus, and the
        # per-dock active-card restore memory (ADR §1.37, ticket #66). All
        # Qt-free, so it lives in session.trace_filter.FilterProfileRegistry
        # (ADR §1.68 / #177); this panel calls it and reacts on the Qt side
        # (tab bar, checkboxes, signals).
        self._profile_registry = FilterProfileRegistry(self._selection_store)

        self.init_ui()

        self._add_profile("Global", scope="global", builtin=True, profile_id=BUILTIN_GLOBAL_ID)
        self._add_profile("Local", scope="local", builtin=True, profile_id=BUILTIN_LOCAL_ID,
                          make_active=True)
        self._update_add_profile_enabled()

    def init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        self._tab_bar = QTabBar()
        self._tab_bar.setExpanding(False)
        self._tab_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tab_bar.currentChanged.connect(self._on_tab_bar_current_changed)
        self._tab_bar.tabBarDoubleClicked.connect(self._on_tab_bar_double_clicked)
        self._tab_bar.customContextMenuRequested.connect(self._on_tab_bar_context_menu)

        self._btn_add_profile = QPushButton("+")
        self._btn_add_profile.setFixedWidth(28)
        self._btn_add_profile.setToolTip("Add a new filter profile.")
        self._btn_add_profile.clicked.connect(self._on_add_profile_clicked)

        # One panel-wide switch, not per card: the active card is always a
        # single one (ADR §1.32), so a per-card on/off would visibly do nothing
        # on the other N-1 cards. Ticked, it blanks the mask on every open
        # graph and the Data Pool narrowing at once, while every checkbox keeps
        # its state so one click brings the filtering back. It rides the tab row
        # (far right) so no half-empty strip sits under the tabs.
        self.cb_show_all = QCheckBox("Show all")
        self.cb_show_all.setToolTip(
            "Temporarily turn every active filter off -- all masks on every graph and "
            "the Data Pool narrowing. The checked values are kept; untick to filter again."
        )
        self.cb_show_all.toggled.connect(self._on_show_all_toggled)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(2)
        tab_row.addWidget(self._tab_bar, stretch=1)
        tab_row.addWidget(self._btn_add_profile)
        tab_row.addWidget(self.cb_show_all)
        outer.addLayout(tab_row)

        self.facet_grid = FacetGrid(
            self._selection_store, lambda: (self._active_profile_id, self._current_dock_id))
        self.facet_grid.selection_changed.connect(self.selection_changed)
        self.btn_configure_filters = self.facet_grid.btn_configure
        outer.addWidget(self.facet_grid, stretch=1)

        self.cb_filter_data_pool = QCheckBox("Filter Data Pool")
        self.cb_filter_data_pool.setToolTip(
            "Narrows the Data Pool tree to the measurements and channels matching these filters.\n"
            "While this is on, the pool's own measurements also contribute filter values, so the "
            "filters work without any result set having been computed yet."
        )
        self.cb_filter_data_pool.toggled.connect(self.data_pool_filter_toggled.emit)

        # A second, always-visible way to flip the active custom profile's
        # scope -- the tab bar's right-click "Make Global"/"Make Local" (T1)
        # does the same thing but is easy to miss. Disabled for the two fixed
        # tabs, which cannot change scope.
        self.cb_profile_scope = QCheckBox("Global")
        self.cb_profile_scope.toggled.connect(self._on_scope_checkbox_toggled)

        data_pool_row = QHBoxLayout()
        data_pool_row.addWidget(self.cb_filter_data_pool)
        data_pool_row.addWidget(self.cb_profile_scope)
        data_pool_row.addStretch()

        # Only ever carries text in the "nothing to filter" case; kept out of the
        # tab row so an empty string does not widen the header.
        self.label_status = QLabel("Check result sets in the Result Pool tab to see filters.")
        self.label_status.setWordWrap(True)

        # Between Configure and the facets, where they sat before the grid
        # became its own widget -- the panel looks the same (#460).
        self.facet_grid.header_layout.addLayout(data_pool_row)
        self.facet_grid.header_layout.addWidget(self.label_status)

    # ---- the facets: forwarded to self.facet_grid ---------------------------

    @property
    def _sel(self) -> FilterSelection:
        """The FilterSelection the active profile + focused dock resolve to."""
        return self.facet_grid.filter_selection

    @property
    def _offering(self) -> OfferedFacets:
        return self.facet_grid.offered_facets

    def populate_facets(self, facets: ResolvedFacets, *, _is_replay: bool = False) -> None:
        """Draws `facets` (see FacetGrid.populate_facets) and words the
        "nothing to filter" status for this panel's scope."""
        render = self.facet_grid.populate_facets(facets, is_replay=_is_replay)
        if render.nothing_to_filter:
            scope = ("the Data Pool" if self.filters_data_pool()
                     else "the checked result set(s)")
            self.label_status.setText(
                f"No filterable metadata found for {scope}. "
                "Mark a field \"Use as Filter\" in Metadata and Filter Settings, or add "
                "a column in \"⚙ Configure Filters…\"."
            )
        else:
            self.label_status.setText("")

    def ensure_channel_checked(self, identity: ChannelIdentity) -> None:
        self.facet_grid.ensure_channel_checked(identity)

    def pool_query(self) -> PoolQuery:
        return self.facet_grid.pool_query()

    def get_selected_metadata_values(self) -> Dict[str, List[str]]:
        return self.facet_grid.get_selected_metadata_values()

    def get_selected_identity_values(self) -> Dict[str, List[str]]:
        return self.facet_grid.get_selected_identity_values()

    def get_selected_channel_identities(self) -> List[ChannelIdentity]:
        return self.facet_grid.get_selected_channel_identities()

    def get_selected_orders(self) -> List[float]:
        return self.facet_grid.get_selected_orders()

    def get_selected_parameter_set_indices(self) -> List[int]:
        return self.facet_grid.get_selected_parameter_set_indices()

    def get_selected_result_kinds(self) -> List[str]:
        return self.facet_grid.get_selected_result_kinds()
