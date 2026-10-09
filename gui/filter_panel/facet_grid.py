# =====================================================================
# FILE: gui/filter_panel/facet_grid.py
# =====================================================================
"""
The facet column grid: the "⚙ Configure…" button over one selection.
trace_filter.ResolvedFacets drawn as group boxes (checkbox list, multi-select
button or min..max range, §1.34), the checked state behind them, and the
get_selected_* readers for the mask/query paths.

Its own widget (#460, ADR §1.131) so two owners can draw it without a second
copy of the facet logic: FilterPanel (tabs, profiles, Data Pool switches
around it) and the Selection editor (#4). Neither owner's checked state lives
here -- the grid reads and writes one FilterSelection in a session.
trace_filter.FilterSelectionStore the owner hands in, under whichever
(card id, dock id) the owner's `selection_key` callable names right now.
FilterPanel's key follows the active profile and the focused dock; an editor
with one card of its own passes a fixed key and its own store.

The card (column configuration) arrives with the facets (ResolvedFacets.
card), so an owner draws its own columns by resolving its own card.
`excluded_columns` are never drawn whatever the card says, and the owner
passes the same set to Configure (FilterFieldSelectionDialog's
`excluded_columns`) so they are not offered either. Clicking Configure only
emits `btn_configure.clicked`: opening the dialog, previewing and saving the
card is the owner's business (gui.handlers.filter_routing for the panel).
"""
from contextlib import contextmanager
from dataclasses import replace
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Set, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from core.filter_card_config import (
    BUILTIN_COLUMN_LABELS, COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_ORDER,
    COLUMN_PARAMETER_SET, IDENTITY_BUILTIN_ORDER, WIDGET_CHECKBOX_LIST, WIDGET_MULTI_SELECT,
    FilterCardConfig, effective_widget,
)
from core.models import ChannelIdentity
from core.project_model import FilterSelection
from io_modules.metadata_schema import parse_value
from selection.trace_filter import (
    EMPTY_FACET_VALUE, OfferedFacets, PanelRender, PoolQuery, ResolvedFacets,
    facet_value_availability, format_result_kind, resolve_panel_render, resolve_pool_query,
)
from selection.channel_identity import format_channel_identity
from selection.source_facets import channel_identity_sort_key
from view_models.parameter_sets import format_parameter_set_details
from selection.parameter_sets import ParameterSet, signature_matches_any, signatures_match
from session.trace_filter import FilterSelectionStore

from gui.filter_panel.filter_panel_widgets import (
    _Control, _FacetEntry, _MultiSelectMenu, _TrimmedDoubleSpinBox,
    _facet_entries, _format_order, _style_dead_control,
)

# How many checkbox rows a facet may take before it scrolls inside its own box
# (§1.34). File name has 219 distinct values on the reference dataset, which
# without a ceiling is the whole card. Nothing about *what* is filtered changes
# -- every value is still there, and still checkable.
_SCROLL_AFTER_ROWS = 12


class FacetGrid(QWidget):
    """Rebuilt from scratch on every populate_facets() call -- the checked state
    lives in the owner's store, not in the widgets (see module docstring)."""

    selection_changed = Signal()

    def __init__(self, selection_store: FilterSelectionStore,
                 selection_key: Callable[[], Tuple[str, Optional[str]]], *,
                 excluded_columns: Iterable[str] = (), parent=None):
        super().__init__(parent)
        self._selection_store = selection_store
        self._selection_key = selection_key
        self.excluded_columns = frozenset(excluded_columns)
        self._init_facet_state()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self.btn_configure = QPushButton("⚙ Configure Filters…")
        self.btn_configure.setToolTip(
            "Toggle which fields already marked \"Use as Filter\" in Metadata and Filter Settings "
            "(and whether Channel) show up as filters here."
        )
        outer.addWidget(self.btn_configure)

        # Where an owner puts its own controls between Configure and the facets
        # (FilterPanel: the Data Pool row and its status line). Empty by default.
        self.header_layout = QVBoxLayout()
        self.header_layout.setSpacing(4)
        outer.addLayout(self.header_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._facets_host = QWidget()
        self._facets_layout = QVBoxLayout(self._facets_host)
        self._facets_layout.setContentsMargins(2, 2, 2, 2)
        self._facets_layout.setSpacing(6)
        self._facets_layout.addStretch()
        scroll.setWidget(self._facets_host)
        outer.addWidget(scroll, stretch=1)

    def set_facets_enabled(self, enabled: bool) -> None:
        """Grey out the facets and Configure together, keeping their checked
        state -- FilterPanel's "Show all"."""
        self._facets_host.setEnabled(enabled)
        self.btn_configure.setEnabled(enabled)

    def _init_facet_state(self) -> None:
        # Every set-mask facet's per-value control, kept so a caller can drive
        # or read one by value. Typed as _Control, not QCheckBox: a column drawn
        # as a multi-select holds checkable QActions instead (§1.34), and
        # isChecked/setChecked/text are all anyone here ever wanted from them.
        self._metadata_checkboxes: Dict[str, List[_Control]] = {}
        # Built-in Identity facets other than Channel (ADR §1.33): column key ->
        # {value: control}.
        self._identity_value_checkboxes: Dict[str, Dict[str, _Control]] = {}
        self._channel_checkboxes: List[Tuple[ChannelIdentity, _Control]] = []
        self._order_checkboxes: Dict[float, _Control] = {}
        self._parameter_set_checkboxes: Dict[int, QCheckBox] = {}
        self._result_kind_checkboxes: Dict[str, _Control] = {}
        # Column key -> its dead values as of the last recompute
        # (panel_facets.PanelRender.dead_values on a real populate,
        # _refresh_dead_state() on every checkbox toggle in between) -- read by
        # the group builders to grey a control that currently has zero effect.
        self._dead_values: Dict[str, Set[Any]] = {}
        # Column key -> {value: control}, one entry per facet family/column
        # currently on screen -- the read side _refresh_dead_state() needs to
        # restyle live controls after a toggle without tearing the panel down
        # and rebuilding it (which populate_facets does, and which would lose
        # scroll position and multi-select menu state for a single click).
        # Kept alongside (not instead of) each family's own storage above,
        # which several call sites and tests already read in that family's own
        # shape (ADR §1.34's "one control type, many per-family containers").
        self._live_controls: Dict[str, Dict[Any, _Control]] = {}
        # (lo widget, hi widget, kind) per ranged field currently on screen --
        # kind decides how _on_range_changed reads the widgets back (float
        # spin boxes vs. ISO-date line edits, ARCHITECTURE_DECISIONS §1.32).
        self._range_widgets: Dict[str, Tuple[QWidget, QWidget, str]] = {}
        # Original (lo, hi) data span per ranged field currently on screen --
        # used by _on_range_changed so touching only one side preserves the
        # exact untouched bound rather than rounding it to the spinbox's decimals (#350).
        self._range_spans: Dict[str, Tuple[Any, Any]] = {}

        # The offering the §1.29 pruning reads through -- Channel / Order /
        # Result Kind / Parameter Set / Identity -- has one home:
        # FilterSelectionStore._offered, keyed by the active (profile, dock).
        # The `_offering` property below is a read-through onto it, not a second
        # copy: §1.44 left a panel-side copy that could drift from the store and
        # forced ensure_channel_checked to write both. Metadata is the
        # exception -- it never feeds the heuristic, only
        # get_selected_metadata_values' pruning -- so it stays a panel-side dict.
        self._offered_metadata_values: Dict[str, Set[str]] = {}

        # The "populated for real at least once" set also lives in
        # FilterSelectionStore now (ADR §1.44), keyed by the same Global->None
        # fold as the selections themselves.

        # The last populate_facets() ResolvedFacets, replayed by FilterPanel when
        # the active profile changes so the on-screen checkboxes reflect the
        # newly active profile's own remembered picks instead of the old one's.
        self.last_facets: Optional[ResolvedFacets] = None

        # Coalescing for a gesture that flips many values at once (a
        # multi-select menu's All / None) -- see _emit_selection_changed.
        self._selection_signal_depth = 0
        self._selection_signal_pending = False

    def _refresh_dead_state(self) -> None:
        """
        Recomputes which facet values currently have zero effect and restyles
        the live controls in place -- called from `_emit_selection_changed()`
        (and its `_batched_selection_changes` flush), so it runs after every
        checkbox/range edit, not just on the next full populate_facets()
        rebuild. Without this, a value only turned grey (or came back to life)
        once the panel next repopulated for real (a tab switch, "Configure
        Filters..." Apply, a dock focus change) -- a plain checkbox click never
        triggers any of those, so greying looked like it needed an unrelated
        extra step. Living in `_emit_selection_changed` rather than each
        individual toggle handler gets it the same All/None coalescing for
        free -- a menu gesture recomputes once, not once per flipped value.

        Deliberately not a rebuild: tearing the panel down and calling
        populate_facets() for every click would reset scroll position and
        close any open multi-select menu mid-gesture. `self._live_controls`
        (populated once per facet by `_fill_facet_box`/`_build_parameter_set_
        group`, the same two places that build the controls in the first
        place) is exactly the value -> control map this needs and nothing
        else keeps.
        """
        facets = self.last_facets
        if facets is None or facets.identities is None:
            return
        self._dead_values = facet_value_availability(
            facets.identities, self._sel, facets.schema, self._offering)
        for key, controls in self._live_controls.items():
            dead = self._dead_values.get(key, set())
            for value, control in controls.items():
                _style_dead_control(control, value in dead)

    # ---- checked state: the owner's (card, dock) selection -----------------

    @property
    def filter_selection(self) -> FilterSelection:
        """
        The one FilterSelection the owner's `selection_key` currently resolves
        to (store.active_selection, ADR §1.39) -- the single path from this grid
        to its checked state. Every build_*/populate/get_selected_* method reads
        and mutates its `checked_*` fields in place; for FilterPanel a Global
        profile shares one across every dock, a Local one has its own per dock.
        """
        return self._selection_store.active_selection(*self._selection_key())

    # Short internal alias -- every builder below reads it.
    _sel = filter_selection

    @property
    def offered_facets(self) -> OfferedFacets:
        """
        What the current (card, dock) was last offered for real -- the mask
        the remembered picks are read through so nothing invisible can filter
        (§1.29). Read-through onto FilterSelectionStore._offered (ADR §1.44);
        empty until populate_facets has run for real for this combo, which is
        what lets a freshly opened dock draw its own curves.
        """
        return self._selection_store.offered_facets(*self._selection_key()) or OfferedFacets()

    _offering = offered_facets

    def ensure_channel_checked(self, identity: ChannelIdentity) -> None:
        """
        Programmatically checks a channel facet value -- used when a channel
        dropped from the File Explorer is added to the comparison, so the
        filter state reflects it even if the checkbox does not exist yet
        (the facet is rebuilt afterwards and will pick this up).

        Counts as offered as well as checked: the caller is asserting the
        identity exists in the current scope, and without that the selection
        pruning would drop it right back out until the rebuild caught up.
        """
        self._sel.checked_channel_identities.add(tuple(identity))
        offered = self._offering
        self._selection_store.record_offering(
            *self._selection_key(),
            replace(offered, channel_identities=offered.channel_identities | {tuple(identity)}),
        )
        checkbox = dict(self._channel_checkboxes).get(identity)
        if checkbox is not None and not checkbox.isChecked():
            checkbox.setChecked(True)  # triggers selection_changed via the normal handler

    # ---- populating -----------------------------------------------------

    def populate_facets(self, facets: ResolvedFacets, *, is_replay: bool = False) -> PanelRender:
        """
        `facets` is the single `selection.trace_filter.ResolvedFacets`
        that `gui.handlers.filter_routing.refresh_filter_panel` resolves from
        the workspace state (ADR §1.38) -- one flat, named record in place of
        the positional facet tuple this used to take. The field notes below
        describe what each part carries.

        `metadata_facets` is selection.source_facets.build_metadata_facets's
        output (field key -> sorted distinct values); `channel_facet` is
        build_channel_facet's output; `schema` supplies each field's
        custom_label so the group box titles match the Metadata Editor.
        `parameter_sets` is io_modules.parameter_sets.build_parameter_sets's
        output for a Global profile, or selection.trace_filter.
        facets_from_traces's dock-local one for a Local profile (plan F4) --
        drawn as a plain mask facet like any other card column (§1.56, the
        "primary" radio is gone). `order_facet` and
        `kind_facet` (plan F4, "Result Kind") are facets_from_traces's output
        for a Local profile and selection.trace_filter.global_calculated_facets's (open
        docks unioned with the Result Pool, ADR §1.36) for a Global one.
        `range_facets`
        is build_range_facets's output (field key -> (lo, hi) spanning the
        current pool/dock) for the opted-in numeric/date fields
        (ARCHITECTURE_DECISIONS §1.32) -- a field the user has already moved
        (self._sel.checked_ranges) keeps its own bounds instead of the freshly
        computed span. `identity_facets` (ADR §1.33) is the built-in Identity
        facets other than Channel -- column key (core.filter_card_config
        COLUMN_*) -> sorted distinct values -- from the pool for a Global card
        (selection.source_facets.build_identity_facets_from_sources) or the
        dock's traces for a Local one (trace_filter.identity_facets_from_traces),
        gated the same §1.29 way as Channel.

        `card` (ticket #50) is the active profile's own
        `core.filter_card_config.FilterCardConfig`, resolved by
        gui.handlers.filter_routing.refresh_filter_panel: the facets are drawn
        as a flat list in `card.ordered_columns` order, spread over
        `card.column_count` columns, each column with the widget the card gives
        it (§1.34). It stays optional -- without one the panel falls back to the
        fixed single-column order it drew before #50, which is what every
        caller that has no card and most of the
        tests rely on.

        `is_replay` is set only by FilterPanel._replay_last_populate() (a tab
        switch, not a real change of scope); it is passed straight to
        resolve_panel_render, which is where the §1.29 default-everything
        heuristic needs to know the difference (ADR §1.42).

        Returns that round's PanelRender, so the owner can word its own
        "nothing to filter" status (FilterPanel names its scope there).
        """
        schema = facets.schema
        card = facets.card

        # Replayed by FilterPanel._replay_last_populate() when the active
        # profile changes, so switching tabs re-renders checkboxes against the
        # new profile's picks without the caller having to re-fetch the facets.
        self.last_facets = facets

        # Every decision this round -- which boxes in what order, which offered
        # values to tick, whether to record the offering, the preserved range
        # bounds -- is resolve_panel_render, a
        # pure function (ADR §1.48; §1.29 heuristic rationale in its docstring).
        # The grid hands it the two lookups it is blind to (both from
        # FilterSelectionStore, ADR §1.44) and then only renders.
        active_id, dock_id = self._selection_key()
        render = resolve_panel_render(
            facets, self._sel,
            previously_offered=self._selection_store.offered_facets(active_id, dock_id),
            already_seen=self._selection_store.has_seen(active_id, dock_id),
            is_replay=is_replay,
        )
        self._selection_store.mark_seen(active_id, dock_id)
        if render.record_offering:
            self._selection_store.record_offering(active_id, dock_id, render.offering)
        # `self._offering` is a read-through onto the store record above (ADR
        # §1.45). The metadata half of the offering stays panel-side: it never
        # feeds the heuristic, only get_selected_metadata_values' pruning.
        self._offered_metadata_values = {
            key: {v for v in values if v != EMPTY_FACET_VALUE}
            for key, values in facets.metadata.items()
        }

        # Tear the old widgets down before landing the new checked state, so the
        # write-back is never interleaved with deleteLater() (ADR §1.48).
        while self._facets_layout.count() > 1:
            item = self._facets_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()  # deleteLater() is deferred; a second populate in the same turn would overlap it
                widget.deleteLater()

        self._metadata_checkboxes = {}
        self._identity_value_checkboxes = {}
        self._channel_checkboxes = []
        self._order_checkboxes = {}
        self._parameter_set_checkboxes = {}
        self._range_widgets = {}
        self._range_spans = {}
        self._result_kind_checkboxes = {}
        self._live_controls = {}

        self._sel.checked_channel_identities = render.checked_channel_identities
        self._sel.checked_orders = render.checked_orders
        self._sel.checked_result_kinds = render.checked_result_kinds
        self._sel.checked_parameter_set_signatures = render.checked_parameter_set_signatures
        self._sel.checked_identity_values = render.checked_identity_values
        self._sel.checked_metadata_values = render.checked_metadata_values
        self._sel.checked_empty_buckets = render.checked_empty_buckets
        self._dead_values = render.dead_values

        boxes = [
            self._build_facet_box(key, render)(self._widget_for_column(card, key, schema))
            for key in render.ordered_columns if key not in self.excluded_columns
        ]
        self._insert_facet_grid(boxes, card.column_count if card is not None else 1)
        return render

    # ---- laying the facets out (ticket #50) ------------------------------

    def _build_facet_box(self, key: str, render: PanelRender) -> Callable[[str], QGroupBox]:
        """
        The builder for one facet box, chosen by its Filter card column key, as
        "give me the widget, take a group box". Called only for keys in
        `render.ordered_columns` -- the presence test that decides which facets
        have something to offer lives once, in `ResolvedFacets.ordered_columns`
        (ADR §1.48), not a second time here. The card picks both the order the
        boxes are built in and which widget each one gets (§1.34).
        """
        facets = render.facets
        schema = facets.schema

        if key == COLUMN_PARAMETER_SET:
            # The one facet whose rendering the card does not choose: each row
            # carries the full settings list in a hover tooltip rather than a
            # plain label, which has no place in a summary button.
            return lambda _widget: self._build_parameter_set_group(
                facets.parameter_sets or [],
                offers_empty=facets.parameter_set_has_empty)
        if key == COLUMN_ANALYSIS_TYPE:
            return lambda widget: self._build_result_kind_group(facets.result_kinds or [], widget)
        if key == COLUMN_CHANNEL:
            return lambda widget: self._build_channel_group(facets.channel, widget)
        if key == COLUMN_ORDER:
            return lambda widget: self._build_order_group(facets.orders or [], widget)
        if key in IDENTITY_BUILTIN_ORDER:
            return lambda widget: self._build_identity_value_group(
                key, BUILTIN_COLUMN_LABELS[key], (facets.identity or {})[key], widget)
        if key in facets.metadata:
            return lambda widget: self._build_metadata_group(
                key, schema.get(key, {}).get("custom_label", key), facets.metadata[key], widget)

        # A range field: resolve_panel_render already resolved its bounds -- the
        # user's own (FilterSelection.checked_ranges) where they moved one, the
        # freshly computed span otherwise (ADR §1.42/§1.48).
        span = (facets.ranges or {}).get(key, render.range_bounds[key])
        return lambda _widget: self._build_range_group(
            key, schema.get(key, {}).get("custom_label", key), render.range_bounds[key],
            schema.get(key, {}).get("kind", "float"), span=span)

    def _widget_for_column(self, card: Optional[FilterCardConfig], key: str,
                           schema: Dict[str, dict]) -> str:
        """
        Which widget draws the column `key` -- the card's choice, corrected by
        the field's own kind (core.filter_card_config.effective_widget, §1.34:
        the kind picks the predicate family, the card only picks a rendering
        inside it). A key the card does not carry falls back to the checkbox
        list, which is what every facet was before #50.
        """
        if card is None or not card.has_column(key):
            return WIDGET_CHECKBOX_LIST
        return effective_widget(schema.get(key, {}).get("kind"), card.column(key).widget)

    def _insert_facet_grid(self, boxes: List[QGroupBox], column_count: int) -> None:
        """
        Lays the finished facet boxes into `column_count` columns, filled row
        by row so that reading them left to right, top to bottom is reading
        `card.ordered_columns` in order.
        """
        if not boxes:
            return
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for position, box in enumerate(boxes):
            grid.addWidget(box, position // column_count, position % column_count,
                           alignment=Qt.AlignmentFlag.AlignTop)
        for column in range(column_count):
            grid.setColumnStretch(column, 1)
        self._facets_layout.insertWidget(self._facets_layout.count() - 1, host)

    # ---- one facet, drawn as a checkbox list or a multi-select -----------

    def _fill_facet_box(self, key: str, box: QGroupBox, widget: str, entries: List[_FacetEntry],
                        is_checked: Callable[[Any], bool],
                        on_toggled: Callable[[Any, bool], None],
                        dead: Optional[Set[Any]] = None) -> Dict[Any, _Control]:
        """
        Fills `box` with one set-mask facet and returns value -> its control.

        The two widgets are the same filter (§1.34): same values, same checked
        state, same mask, an empty pick hides everything either way. Which is
        why the controls come back through one dict -- a QCheckBox and a
        checkable QAction answer isChecked()/setChecked()/text() alike, so
        everything reading them back (including ensure_channel_checked, and the
        tests) does not care which one it got.

        Every control is put into its checked state *before* its signal is
        wired, so rebuilding the grid never looks like an edit (see filter_panel.py's module
        docstring). `dead` (facet_value_availability) greys a
        value's control -- still fully interactive -- when it currently has no
        effect on what is on screen. `key` is recorded into
        `self._live_controls` alongside the return value -- the one spot every
        facet family that goes through this method registers itself for
        `_refresh_dead_state()`'s later restyling, so a new facet family gets
        that for free rather than needing its own builder to remember a second
        assignment (only `_build_parameter_set_group`, which never calls this,
        still does its own).
        """
        dead = dead or set()
        controls: Dict[Any, _Control] = {}
        outer = QVBoxLayout(box)
        outer.setSpacing(2)

        if widget == WIDGET_MULTI_SELECT:
            outer.addWidget(self._multi_select_button(entries, is_checked, on_toggled, controls, dead))
            self._live_controls[key] = controls
            return controls

        rows_host = QWidget()
        rows = QVBoxLayout(rows_host)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(2)
        for value, label in entries:
            checkbox = QCheckBox(label)
            checkbox.setChecked(is_checked(value))
            checkbox.toggled.connect(lambda checked, v=value: on_toggled(v, checked))
            _style_dead_control(checkbox, value in dead)
            rows.addWidget(checkbox)
            controls[value] = checkbox

        if len(entries) > _SCROLL_AFTER_ROWS:
            row_height = next(iter(controls.values())).sizeHint().height() + rows.spacing()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setMaximumHeight(_SCROLL_AFTER_ROWS * row_height + 8)
            scroll.setWidget(rows_host)
            outer.addWidget(scroll)
        else:
            outer.addWidget(rows_host)
        self._live_controls[key] = controls
        return controls

    def _multi_select_button(self, entries: List[_FacetEntry], is_checked, on_toggled,
                             controls: Dict[Any, _Control], dead: Set[Any]) -> QToolButton:
        """One row's worth of the same facet: a summary button ("3 / 17") over a
        menu of checkable items, plus All / None."""
        button = QToolButton()
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        menu = _MultiSelectMenu(button)

        def refresh_summary() -> None:
            checked = sum(1 for action in controls.values() if action.isChecked())
            button.setText(f"{checked} / {len(controls)}")

        for value, label in entries:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(is_checked(value))
            action.toggled.connect(lambda checked, v=value: on_toggled(v, checked))
            action.toggled.connect(lambda _checked: refresh_summary())
            _style_dead_control(action, value in dead)
            controls[value] = action

        menu.addSeparator()
        menu.addAction("All").triggered.connect(
            lambda: self._set_all_checked(list(controls.values()), True))
        menu.addAction("None").triggered.connect(
            lambda: self._set_all_checked(list(controls.values()), False))

        button.setMenu(menu)
        button.setToolTip("Pick which values stay visible.")
        refresh_summary()
        return button

    def _set_all_checked(self, controls: List[_Control], checked: bool) -> None:
        with self._batched_selection_changes():
            for control in controls:
                control.setChecked(checked)

    def _emit_selection_changed(self) -> None:
        """
        The one place a facet toggle emits selection_changed -- and, since a
        toggle is exactly what can change which values are dead, the one place
        that refreshes their styling too. Both stay coalesced the same way: a
        menu's All / None flips every value in a single gesture, and each flip
        runs the same per-value handler -- recomputing facet_value_availability
        and emitting once per value would run the whole reapply-the-mask/
        restyle/persist chain seventeen times for one click, on the GUI thread.
        """
        if self._selection_signal_depth:
            self._selection_signal_pending = True
            return
        self._refresh_dead_state()
        self.selection_changed.emit()

    @contextmanager
    def _batched_selection_changes(self):
        self._selection_signal_depth += 1
        try:
            yield
        finally:
            self._selection_signal_depth -= 1
        if not self._selection_signal_depth and self._selection_signal_pending:
            self._selection_signal_pending = False
            self._refresh_dead_state()
            self.selection_changed.emit()

    def _build_range_group(self, key: str, label: str, bounds: Tuple[Any, Any], kind: str,
                           span: Optional[Tuple[Any, Any]] = None) -> QGroupBox:
        """
        A numeric/date facet's `min..max` widget (ARCHITECTURE_DECISIONS §1.32).

        `bounds` is what plan_populate resolved for this field (ADR §1.42): the
        current pool/dock's own span until the user edits either side, then
        their own bounds -- `self._sel.checked_ranges` gaining a key for it is
        the "touched" flag (FilterSelection.checked_ranges), and an untouched
        field's bounds simply track the live span on every repopulation.
        """
        if span is None:
            span = bounds
        self._range_spans[key] = span

        box = QGroupBox(label)
        layout = QHBoxLayout(box)
        layout.setSpacing(4)

        lo, hi = bounds
        is_date = kind == "date"
        if is_date:
            lo_widget: QWidget = QLineEdit(str(lo))
            hi_widget: QWidget = QLineEdit(str(hi))
            lo_widget.setToolTip("YYYY-MM-DD")
            hi_widget.setToolTip("YYYY-MM-DD")
            lo_widget.editingFinished.connect(lambda k=key: self._on_range_changed(k, side="lo"))
            hi_widget.editingFinished.connect(lambda k=key: self._on_range_changed(k, side="hi"))
        else:
            lo_spin = _TrimmedDoubleSpinBox()
            hi_spin = _TrimmedDoubleSpinBox()
            for spin in (lo_spin, hi_spin):
                spin.setRange(-1.0e12, 1.0e12)
                spin.setDecimals(0 if kind == "int" else 4)
            lo_spin.setValue(float(lo))
            hi_spin.setValue(float(hi))
            lo_spin.valueChanged.connect(lambda _value, k=key: self._on_range_changed(k, side="lo"))
            hi_spin.valueChanged.connect(lambda _value, k=key: self._on_range_changed(k, side="hi"))
            lo_widget, hi_widget = lo_spin, hi_spin

        layout.addWidget(QLabel("Min"))
        layout.addWidget(lo_widget)
        layout.addWidget(QLabel("Max"))
        layout.addWidget(hi_widget)
        self._range_widgets[key] = (lo_widget, hi_widget, kind)
        return box

    def _on_range_changed(self, key: str, side: Literal["lo", "hi"]) -> None:
        """Store one edited side; the other keeps its exact stored or span value (#350).

        A date bound is rewritten to YYYY-MM-DD (#402), the form measurements
        store, so a later string compare stays chronological. An unparsable
        date is not stored: the line edit snaps back to the last valid value.
        """
        lo_widget, hi_widget, kind = self._range_widgets[key]
        current_lo, current_hi = self._sel.checked_ranges.get(key, self._range_spans[key])
        widget = lo_widget if side == "lo" else hi_widget

        if kind == "date":
            value = parse_value(widget.text(), "date")
            if value is None:
                widget.setText(str(current_lo if side == "lo" else current_hi))
                return
            widget.setText(value)
        else:
            value = widget.value()

        bounds = (value, current_hi) if side == "lo" else (current_lo, value)
        self._sel.checked_ranges[key] = bounds
        self._emit_selection_changed()

    def _toggle_empty_bucket(self, token: str, checked: bool) -> None:
        """Check / uncheck one gating facet's "(Empty)" row (ADR §1.56). `token`
        is the family name for the scalar families (`order`, `result_kind`) or
        the column key for the keyed ones (Identity / metadata)."""
        if checked:
            self._sel.checked_empty_buckets.add(token)
        else:
            self._sel.checked_empty_buckets.discard(token)
        self._emit_selection_changed()

    def _with_empty_row(self, token: str, is_checked: Callable[[Any], bool],
                        on_toggled: Callable[[Any, bool], None]
                        ) -> Tuple[Callable[[Any], bool], Callable[[Any, bool], None]]:
        """Wrap a facet's `is_checked` / `on_toggled` so the EMPTY_FACET_VALUE
        entry routes to `checked_empty_buckets[token]` instead of the family's
        own checked collection -- the "(Empty)" row is one checkbox in the same
        list as every other value (ADR §1.56)."""
        def checked(value: Any) -> bool:
            if value == EMPTY_FACET_VALUE:
                return token in self._sel.checked_empty_buckets
            return is_checked(value)

        def toggled(value: Any, is_on: bool) -> None:
            if value == EMPTY_FACET_VALUE:
                self._toggle_empty_bucket(token, is_on)
            else:
                on_toggled(value, is_on)

        return checked, toggled

    def _build_metadata_group(self, key: str, label: str, values: List[str],
                              widget: str = WIDGET_CHECKBOX_LIST) -> QGroupBox:
        box = QGroupBox(label)
        remembered = self._sel.checked_metadata_values.get(key, set())
        is_checked, on_toggled = self._with_empty_row(
            key, lambda value: value in remembered,
            lambda value, checked: self._on_metadata_toggled(key, value, checked),
        )
        controls = self._fill_facet_box(
            # Categorical text, labelled literally (#405): numeric fields are
            # ranges, so a number-looking value here ('0815') is not a number.
            key, box, widget, _facet_entries(values, str), is_checked, on_toggled,
            dead=self._dead_values.get(key),
        )
        self._metadata_checkboxes[key] = list(controls.values())
        return box

    def _on_metadata_toggled(self, key: str, value: str, checked: bool) -> None:
        bucket = self._sel.checked_metadata_values.setdefault(key, set())
        if checked:
            bucket.add(value)
        else:
            bucket.discard(value)
        self._emit_selection_changed()

    def _build_identity_value_group(self, key: str, label: str, values: List[str],
                                    widget: str = WIDGET_CHECKBOX_LIST) -> QGroupBox:
        """
        One built-in Identity facet other than Channel (Direction, Channel type,
        File name, Data Pool label, Result set -- ADR §1.33). Gates exactly like
        the Channel group: an offered-but-unchecked value hides the traces
        carrying it.
        """
        box = QGroupBox(label)
        remembered = self._sel.checked_identity_values.get(key, set())
        is_checked, on_toggled = self._with_empty_row(
            key, lambda value: value in remembered,
            lambda value, checked: self._on_identity_value_toggled(key, value, checked),
        )
        controls = self._fill_facet_box(
            key, box, widget, [(value, value) for value in values], is_checked, on_toggled,
            dead=self._dead_values.get(key),
        )
        self._identity_value_checkboxes[key] = dict(controls)
        return box

    def _on_identity_value_toggled(self, key: str, value: str, checked: bool) -> None:
        bucket = self._sel.checked_identity_values.setdefault(key, set())
        if checked:
            bucket.add(value)
        else:
            bucket.discard(value)
        self._emit_selection_changed()

    def _build_parameter_set_group(self, parameter_sets: List[ParameterSet],
                                   offers_empty: bool = False) -> QGroupBox:
        """
        One row per Parameter Set: a mask checkbox whose hover tooltip carries
        the full settings list, not a per-row label -- the same text twice was
        only clutter (ARCHITECTURE_DECISIONS §1.37). The "primary" radio is gone
        (§1.56): a dropped channel is computed with `default_primary_index`.
        """
        box = QGroupBox("Parameter Set")
        layout = QVBoxLayout(box)
        layout.setSpacing(4)
        dead = self._dead_values.get(COLUMN_PARAMETER_SET, set())
        live: Dict[Any, _Control] = {}

        for ps in parameter_sets:
            cb = QCheckBox(ps.label)
            cb.setChecked(signature_matches_any(ps.signature, self._sel.checked_parameter_set_signatures))
            cb.stateChanged.connect(lambda _state, p=ps: self._on_parameter_set_toggled(p))
            cb.setToolTip(format_parameter_set_details(ps.params, ps.kind))
            _style_dead_control(cb, ps.index in dead)
            layout.addWidget(cb)
            self._parameter_set_checkboxes[ps.index] = cb
            live[ps.index] = cb

        if offers_empty:
            # A trace whose settings match no offered set (ADR §1.56) -- one
            # more checkbox in the same list, routed to checked_empty_buckets.
            empty_cb = QCheckBox(EMPTY_FACET_VALUE)
            empty_cb.setChecked("parameter_set" in self._sel.checked_empty_buckets)
            empty_cb.toggled.connect(
                lambda checked: self._toggle_empty_bucket("parameter_set", checked))
            _style_dead_control(empty_cb, EMPTY_FACET_VALUE in dead)
            layout.addWidget(empty_cb)
            live[EMPTY_FACET_VALUE] = empty_cb

        self._live_controls[COLUMN_PARAMETER_SET] = live
        return box

    def _on_parameter_set_toggled(self, ps: ParameterSet) -> None:
        checkbox = self._parameter_set_checkboxes[ps.index]
        if checkbox.isChecked():
            self._sel.checked_parameter_set_signatures.add(ps.signature)
        else:
            checked = self._sel.checked_parameter_set_signatures
            checked.difference_update(
                [signature for signature in checked if signatures_match(signature, ps.signature)])
        self._emit_selection_changed()

    def _build_result_kind_group(self, kinds: List[str],
                                 widget: str = WIDGET_CHECKBOX_LIST) -> QGroupBox:
        box = QGroupBox("Result Kind")
        checked = set(self._sel.checked_result_kinds)
        is_checked, on_toggled = self._with_empty_row(
            "result_kind", lambda kind: kind in checked, self._on_result_kind_toggled,
        )
        controls = self._fill_facet_box(
            COLUMN_ANALYSIS_TYPE, box, widget, _facet_entries(kinds, format_result_kind),
            is_checked, on_toggled, dead=self._dead_values.get(COLUMN_ANALYSIS_TYPE),
        )
        self._result_kind_checkboxes = dict(controls)
        return box

    def _on_result_kind_toggled(self, kind: str, checked: bool) -> None:
        if checked:
            self._sel.checked_result_kinds.add(kind)
        else:
            self._sel.checked_result_kinds.discard(kind)
        self._emit_selection_changed()

    def _build_channel_group(self, identities: List[ChannelIdentity],
                             widget: str = WIDGET_CHECKBOX_LIST) -> QGroupBox:
        box = QGroupBox("Channel")
        checked = set(self._sel.checked_channel_identities)
        controls = self._fill_facet_box(
            COLUMN_CHANNEL, box, widget,
            [(identity, format_channel_identity(identity)) for identity in identities],
            lambda identity: identity in checked, self._on_channel_toggled,
            dead=self._dead_values.get(COLUMN_CHANNEL),
        )
        self._channel_checkboxes = list(controls.items())
        return box

    def _on_channel_toggled(self, identity: ChannelIdentity, checked: bool) -> None:
        if checked:
            self._sel.checked_channel_identities.add(identity)
        else:
            self._sel.checked_channel_identities.discard(identity)
        self._emit_selection_changed()

    def _build_order_group(self, orders: List[float],
                           widget: str = WIDGET_CHECKBOX_LIST) -> QGroupBox:
        box = QGroupBox("Order")
        checked = set(self._sel.checked_orders)
        is_checked, on_toggled = self._with_empty_row(
            "order", lambda order: order in checked, self._on_order_toggled,
        )
        controls = self._fill_facet_box(
            COLUMN_ORDER, box, widget, _facet_entries(orders, _format_order), is_checked, on_toggled,
            dead=self._dead_values.get(COLUMN_ORDER),
        )
        self._order_checkboxes = dict(controls)
        return box

    def _on_order_toggled(self, order: float, checked: bool) -> None:
        if checked:
            self._sel.checked_orders.add(order)
        else:
            self._sel.checked_orders.discard(order)
        self._emit_selection_changed()

    # ---- reading the current selection ----------------------------------

    # Everything below reports only what the panel is currently offering --
    # see filter_panel.py's module docstring for why the remembered state is wider.

    def pool_query(self) -> PoolQuery:
        """What "Filter Data Pool" narrows the pool by -- only the columns that
        are a real narrowing of what this card offers (resolve_pool_query)."""
        return resolve_pool_query(self._sel, self._offering, self._offered_metadata_values)

    def get_selected_metadata_values(self) -> Dict[str, List[str]]:
        """field key -> the checked values, when they are a real narrowing.

        The batch / Data Pool query path (source_facets.apply_metadata_facets)
        keeps the pre-§1.56 "a field's selection narrows, it never hides
        everything" model; the dock mask reads `checked_metadata_values`
        directly. The asymmetry is deliberate (§1.56, §1.107).
        """
        return self.pool_query().metadata_values

    def get_selected_identity_values(self) -> Dict[str, List[str]]:
        """column key -> checked values, narrowed to what is currently offered
        (§1.29). A column with nothing checked is omitted."""
        selected = {}
        for key, offered in self._offering.identity_values.items():
            values = self._sel.checked_identity_values.get(key, set()) & offered
            if values:
                selected[key] = sorted(values)
        return selected

    def get_selected_channel_identities(self) -> List[ChannelIdentity]:
        """Every checked channel still on offer -- a positive list (what a
        MeasurementSelection stores), not the pool's narrowing (pool_query)."""
        return sorted(self._sel.checked_channel_identities & self._offering.channel_identities,
                      key=channel_identity_sort_key)

    def get_selected_orders(self) -> List[float]:
        return sorted(self._sel.checked_orders & set(self._offering.orders))

    def get_selected_parameter_set_indices(self) -> List[int]:
        return sorted(ps.index for ps in self._offering.parameter_sets
                      if signature_matches_any(ps.signature, self._sel.checked_parameter_set_signatures))

    def get_selected_result_kinds(self) -> List[str]:
        return sorted(self._sel.checked_result_kinds & self._offering.result_kinds)
