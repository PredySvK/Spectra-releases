# =====================================================================
# FILE: gui/dialogs/filter_field_selection_dialog.py
# =====================================================================
"""
Configure Filters: which columns sit on the Filter card you are standing on,
in what order, drawn as which widget, and how many columns fit side by side
(ARCHITECTURE_DECISIONS §1.32, tickets #41/#42/#49).

Four sections, so the dialog can be searched by what a column *is* rather
than scrolled alphabetically: Identity (Channel, Direction, Channel type,
File name, Data Pool label, Result set), Raw metadata (facts read straight
off the measurement file), Excel metadata (the metadata spreadsheet) and
Calculated metadata (Analysis type, Order, Parameter set). The Identity and
Calculated built-ins have no schema row, so they are always offered, in the
fixed order core.filter_card_config.IDENTITY_BUILTIN_ORDER /
CALCULATED_BUILTIN_ORDER lists them.

Two gates, not one. Opting an Excel/Raw metadata field into "is_active"
is Metadata and Filter Settings' job alone (its "Active Status" column,
ADR §1.188) -- this dialog only lists fields already opted in there, so it
can add one to the active card or drop it, but not turn a brand-new field on.

Every checkbox's label carries "(N)" -- how many distinct values that column
has right now (selection.source_facets.FieldCardinality / selection.trace_filter.
resolve_card_cardinalities), not only the greyed ones. For a
Global card that count is pool-wide; for a Local one it is read off the focused
dock's own traces, since that is all a Local card can filter. The
dialog never counts anything itself: the caller hands the resolver's
`CardCardinalities` in, so a count cannot drift from the facet it describes. A column whose cardinality
means it cannot narrow anything down -- one value, or a value unique to every
measurement -- is greyed out on top of that, but stays checkable: the app never
decides this for the user, and the verdict flips back on its own once the scope
grows.

Ticket #49: the dialog is a live editor over one `core.filter_card_config.
FilterCardConfig`, not a set of checkboxes. Each checked row carries an order
number (spin box + up/down arrows, also type-in), and a widget picker
prefilled from the schema field's `kind`; the dialog as a whole carries the
card's column count (1 to 4, §1.37). Every edit rebuilds the working card through the
pure `core.filter_card_config` helpers -- collision handling and renumbering
live there, tested without Qt. `result_card()` hands back the finished config,
and since #50 `gui.filter_panel.filter_panel.populate_facets` draws the card
exactly as configured.

Ticket #44 / ADR §1.56: each checked row also carries a "Default" checkbox --
built-in or schema field, the columns ticked there are pinned onto every new
graph's card, on top of the one column an unedited card always carries (Channel).

The widget picker offers three renderings, not five (§1.34): `checkbox` and
`text_search` are gone. It is also dead on a numeric/date column, because the
predicate family follows the field's `kind` and not the card -- the tooltip
names the one path that changes that (Metadata and Filter Settings -> Type ->
Text).

All internal documentation strings and variable labels are standardly written
in English.
"""
from dataclasses import replace
from typing import Any, Callable, Collection, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
)

from core.filter_card_config import (
    WIDGET_CHECKBOX_LIST, WIDGET_MULTI_SELECT,
    WIDGET_RANGE, WIDGETS, FilterCardConfig, default_widget_for_kind,
    kind_is_ranged, renumbered, with_column_count, with_column_widget,
)
from selection.source_facets import FieldCardinality

from gui.dialogs.auto_apply import make_auto_apply_check
from gui.dialogs.dialog_state import fit_width_to_scroll_content, remember_dialog_geometry
from gui.dialogs.priority_grid import PriorityGrid, PriorityGridSection
from selection.field_offer import OfferedField, build_field_offer
from selection.trace_filter import CardCardinalities, build_column_for_key

# Display label per widget id -- the ids and their picker order are
# core.filter_card_config.WIDGETS' to own, this only names them for the combo.
_WIDGET_LABELS: Dict[str, str] = {
    WIDGET_CHECKBOX_LIST: "Checkbox list",
    WIDGET_RANGE: "Range (min..max)",
    WIDGET_MULTI_SELECT: "Multi-select",
}
_WIDGET_CHOICES: Tuple[Tuple[str, str], ...] = tuple(
    (widget_id, _WIDGET_LABELS[widget_id]) for widget_id in WIDGETS
)

_WIDGET_TOOLTIP = "How this column is drawn on the card."

# Why the picker is dead on a numeric/date column, and the one way out of it
# (§1.34). The path is Metadata and Filter Settings' Type column, which is the
# app's single gate on "is this field a quantity or a label" -- greying the
# control and naming the path is the pattern this dialog already uses for a
# column that cannot narrow anything down (#42).
_RANGED_WIDGET_TOOLTIP = (
    "A numeric or date column always filters as a range, so there is nothing to choose here.\n"
    "To pick its values from a list instead, switch the field's Type to Text in "
    "Metadata and Filter Settings."
)

# An entry the dialog can render as one row: dialog key, its label
# (without the count), and the cardinality behind it.
_Entry = Tuple[str, str, FieldCardinality]

_NO_CARDINALITY = FieldCardinality(distinct_count=0, reason=None)

# The column header this dialog adds over every section's grid (§1.37), left of the
# grid's own "Default". "Shown as" used to be a per-row label; pulling it up here
# lines the rows up and frees the width.
_EXTRA_HEADERS: Tuple[str, ...] = ("Shown as",)
_DEFAULT_TOOLTIP = "Put this column on every new graph's card, on top of Channel."

_AUTO_APPLY_SETTINGS_KEY = "filter_field_selection/auto_apply"
_AUTO_APPLY_TOOLTIP = (
    "Apply every change to the focused graph as you make it, so you can see the "
    "mask move. Cancel puts the card back the way it was."
)


class FilterFieldSelectionDialog(QDialog):
    def __init__(self, schema: Dict[str, Dict[str, Any]], parent=None, settings=None,
                 card: Optional[FilterCardConfig] = None,
                 cardinalities: Optional[CardCardinalities] = None,
                 on_live_change: Optional[Callable[[FilterCardConfig], None]] = None,
                 excluded_columns: Collection[str] = ()):
        super().__init__(parent)
        self.setWindowTitle("Configure Filters")
        self.setMinimumWidth(760)
        self._schema = schema
        self._settings = settings
        # Called after every edit while Auto apply is on (§1.37) -- the caller
        # previews the working card on the focused dock and reverts on Cancel.
        self._on_live_change = on_live_change
        # Columns this card may never carry, so they get no row at all -- the
        # Selection editor's grid has no result columns (#460, ADR §1.131).
        self._excluded_columns = frozenset(excluded_columns)
        self._widget_combos: Dict[str, QComboBox] = {}

        # The working card every edit rebuilds (ticket #49) -- the active
        # profile's stored card, or an empty one for a profile that has never
        # been configured.
        self._card = card if card is not None else FilterCardConfig()

        # The counts and "cannot narrow" verdicts, resolved by the caller from
        # the same universe the facets are; None counts nothing.
        self._cardinalities = cardinalities or CardCardinalities({}, {})
        # Which section a schema field landed in, and why a field is greyed --
        # kept as plain dicts (not re-derived from the widget tree) so a test
        # can assert on the dialog's *output* rather than its layout.
        self._raw_field_keys: Set[str] = set()
        self._excel_field_keys: Set[str] = set()
        self._greyed_reasons: Dict[str, str] = {}
        self._build_ui(schema)
        self._sync_widget_combos()
        size = fit_width_to_scroll_content(
            self, self.findChild(QScrollArea, "FilterColumnSections"), (800, 520))
        remember_dialog_geometry(self, settings, "filter_field_selection", default_size=size)

    def _build_ui(self, schema: Dict[str, Dict[str, Any]]) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Which columns sit on this card:"))

        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("Columns side by side:"))
        self._column_count_combo = QComboBox()
        self._column_count_combo.setObjectName("FilterColumnCountCombo")
        for value in (1, 2, 3, 4):
            self._column_count_combo.addItem(str(value), value)
        index = self._column_count_combo.findData(self._card.column_count)
        self._column_count_combo.setCurrentIndex(index if index >= 0 else 0)
        self._column_count_combo.currentIndexChanged.connect(self._on_column_count_changed)
        count_row.addWidget(self._column_count_combo)
        count_row.addStretch()
        layout.addLayout(count_row)

        scroll = QScrollArea()
        scroll.setObjectName("FilterColumnSections")
        scroll.setWidgetResizable(True)

        schema_cardinalities = self._cardinalities.schema_fields
        builtin_cardinalities = self._cardinalities.builtins
        offer = build_field_offer(schema, excluded=self._excluded_columns)
        raw_fields = {key for key, _label in offer.raw}
        excel_fields = {key for key, _label in offer.excel}
        self._raw_field_keys = raw_fields
        self._excel_field_keys = excel_fields
        self._greyed_reasons = {
            key: cardinality.reason for key, cardinality in schema_cardinalities.items()
            if cardinality.reason is not None and (key in raw_fields or key in excel_fields)
        }
        self._greyed_reasons.update({
            key: cardinality.reason
            for key, cardinality in builtin_cardinalities.items()
            if cardinality.reason is not None
        })

        # Ticks, Priority and the Default column are the shared grid's (shell §1.301); every
        # change of them rebuilds the working card (`_on_grid_changed`).
        ordered = self._card.ordered_columns
        self.grid = PriorityGrid(
            [
                self._section("Identity", self._entries(offer.identity, builtin_cardinalities)),
                self._section("Raw metadata", self._entries(offer.raw, schema_cardinalities)),
                self._section("Excel metadata", self._entries(offer.excel, schema_cardinalities)),
                self._section("Calculated metadata", self._entries(offer.calculated, builtin_cardinalities)),
            ],
            [column.key for column in ordered],
            defaults=[column.key for column in ordered if column.default],
            default_tooltip=_DEFAULT_TOOLTIP,
            extra_headers=_EXTRA_HEADERS, add_extra_cells=self._add_extra_cells,
        )
        self.grid.changed.connect(self._on_grid_changed)

        scroll.setWidget(self.grid)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        # Without this the button box expands and pins OK/Cancel to the far right,
        # leaving a gap between them and the Auto apply checkbox.
        buttons.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        # Turning it on mid-dialog catches the dock up to whatever is already
        # edited; turning it off leaves the last preview in place -- Cancel still
        # reverts, OK still keeps.
        self._auto_apply_check = make_auto_apply_check(
            self._settings, _AUTO_APPLY_SETTINGS_KEY, _AUTO_APPLY_TOOLTIP, self._notify_live)
        self._auto_apply_check.setObjectName("FilterAutoApply")

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self._auto_apply_check)   # §1.37: beside OK / Cancel
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

    # -- section builders -----------------------------------------------

    @staticmethod
    def _entries(fields: Tuple[OfferedField, ...],
                 cardinalities: Dict[str, FieldCardinality]) -> List[_Entry]:
        return [(key, label, cardinalities.get(key, _NO_CARDINALITY)) for key, label in fields]

    @staticmethod
    def _section(title: str, entries: List[_Entry]) -> PriorityGridSection:
        return title, [(key, f"{label} ({cardinality.distinct_count})", cardinality.reason)
                       for key, label, cardinality in entries]

    def _add_extra_cells(self, grid: QGridLayout, row: int, key: str) -> None:
        combo = QComboBox()
        for widget_id, widget_label in _WIDGET_CHOICES:
            combo.addItem(widget_label, widget_id)
        combo.setToolTip(_WIDGET_TOOLTIP)
        combo.currentIndexChanged.connect(lambda _index, k=key: self._on_widget_changed(k))
        self._widget_combos[key] = combo
        grid.addWidget(combo, row, 2)

    # -- editing the working card (ticket #49) --------------------------

    def _on_grid_changed(self) -> None:
        """Rebuild the working card from the grid: its ticked keys in Priority order (a column
        already on the card keeps its widget, a newly ticked one is built from the schema),
        renumbered dense, Default flags from the grid's Default column."""
        by_key = {column.key: column for column in self._card.columns}
        columns = [by_key.get(key) or build_column_for_key(key, self._schema) for key in self.grid.fields]
        self._card = replace(self._card, columns=renumbered(columns))
        self._sync_default_flags()
        self._sync_widget_combos()
        self._notify_live()

    def _sync_default_flags(self) -> None:
        defaults = set(self.grid.defaults or ())
        self._card = replace(self._card, columns=tuple(
            column if column.default == (column.key in defaults) else replace(column, default=column.key in defaults)
            for column in self._card.columns))

    def _on_widget_changed(self, key: str) -> None:
        # No _sync_widget_combos() here, unlike a grid edit: the widget
        # choice does not renumber, and re-driving the combo we just read
        # would recurse.
        column_key = key
        if self._card.has_column(column_key):
            self._card = with_column_widget(
                self._card, column_key, self._widget_combos[key].currentData()
            )
            self._notify_live()

    def _on_column_count_changed(self) -> None:
        self._card = with_column_count(self._card, self._column_count_combo.currentData())
        self._notify_live()

    def _notify_live(self) -> None:
        if self._on_live_change is not None and self._auto_apply_check.isChecked():
            self._on_live_change(self._card)

    def _sync_widget_combos(self) -> None:
        """Redraw every row's "Shown as" picker from the working card (ticks, Priority and
        Default are the grid's)."""
        for key, combo in self._widget_combos.items():
            on_card = self._card.has_column(key)
            column = self._card.column(key) if on_card else None
            # A ranged field's widget is not the user's to pick (§1.34): the
            # predicate family follows the field's Type, so the combo is dead
            # and says where the one gate is instead.
            kind = self._schema.get(key, {}).get("kind")
            ranged = kind_is_ranged(kind)
            combo.setEnabled(on_card and not ranged)
            combo.setToolTip(_RANGED_WIDGET_TOOLTIP if ranged else _WIDGET_TOOLTIP)
            blocked = combo.blockSignals(True)
            wanted = column.widget if on_card else default_widget_for_kind(kind)
            index = combo.findData(wanted)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(blocked)

    # -- output --------------------------------------------------------

    def result_card(self) -> FilterCardConfig:
        """The finished configuration -- what Configure Filters stores on the
        project (ticket #49). Equal to the card handed in when nothing
        was edited, so the caller can skip a no-op save. The grid's Default
        column is read here: a Default toggle changes no preview, so it emits nothing."""
        self._sync_default_flags()
        return self._card
