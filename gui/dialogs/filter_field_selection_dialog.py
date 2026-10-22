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
from typing import Any, Callable, Collection, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QSpinBox, QToolButton,
    QVBoxLayout, QWidget,
)

from core.filter_card_config import (
    WIDGET_CHECKBOX_LIST, WIDGET_MULTI_SELECT,
    WIDGET_RANGE, WIDGETS, FilterCardConfig, add_column, default_widget_for_kind,
    kind_is_ranged, move_column, remove_column, with_column_count, with_column_default,
    with_column_order, with_column_widget,
)
from selection.source_facets import FieldCardinality

from gui.dialogs.dialog_state import fit_width_to_scroll_content, remember_dialog_geometry
from gui.dialogs.priority_grid import PriorityGrid
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

# The column headers over every section's grid (§1.37). "Default" and "Shown as"
# used to be a per-row label; pulling them up here lines the rows up and frees
# the width.
_EXTRA_HEADERS: Tuple[str, ...] = ("Shown as", "Default")

_AUTO_APPLY_SETTINGS_KEY = "filter_field_selection/auto_apply"
_AUTO_APPLY_TOOLTIP = (
    "Apply every change to the focused graph as you make it, so you can see the "
    "mask move. Cancel puts the card back the way it was."
)


def _read_auto_apply(settings) -> bool:
    """The remembered Auto apply state (§1.37), defaulting on."""
    if settings is None:
        return True
    return settings.value(_AUTO_APPLY_SETTINGS_KEY, True, type=bool)


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
        self._checkboxes: Dict[str, QCheckBox] = {}
        self._order_spins: Dict[str, QSpinBox] = {}
        self._up_buttons: Dict[str, QToolButton] = {}
        self._down_buttons: Dict[str, QToolButton] = {}
        self._widget_combos: Dict[str, QComboBox] = {}
        self._default_checks: Dict[str, QCheckBox] = {}
        self._sections: List[PriorityGrid] = []

        # The working card every edit rebuilds (ticket #49) -- the active
        # profile's stored card, or an empty one for a profile that has never
        # been configured. `_on_card_keys` is which checkboxes start ticked.
        self._card = card if card is not None else FilterCardConfig()
        self._on_card_keys = {column.key for column in self._card.columns}

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
        self._sync_rows()
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
        columns = QWidget()
        columns_layout = QHBoxLayout(columns)

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

        columns_layout.addWidget(self._section(
            "Identity", self._entries(offer.identity, builtin_cardinalities)))
        columns_layout.addWidget(self._section(
            "Raw metadata", self._entries(offer.raw, schema_cardinalities)))
        columns_layout.addWidget(self._section(
            "Excel metadata", self._entries(offer.excel, schema_cardinalities)))
        columns_layout.addWidget(self._section(
            "Calculated metadata", self._entries(offer.calculated, builtin_cardinalities)))

        scroll.setWidget(columns)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        # Without this the button box expands and pins OK/Cancel to the far right,
        # leaving a gap between them and the Auto apply checkbox.
        buttons.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._auto_apply_check = QCheckBox("Auto apply")
        self._auto_apply_check.setObjectName("FilterAutoApply")
        self._auto_apply_check.setToolTip(_AUTO_APPLY_TOOLTIP)
        self._auto_apply_check.setChecked(_read_auto_apply(self._settings))
        self._auto_apply_check.toggled.connect(self._on_auto_apply_toggled)

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

    def _section(self, title: str, entries: List[_Entry]) -> PriorityGrid:
        section = PriorityGrid(
            title,
            [(key, f"{label} ({cardinality.distinct_count})", cardinality.reason)
             for key, label, cardinality in entries],
            checked_keys=self._on_card_keys,
            on_toggled=self._on_checkbox_toggled, on_nudge=self._nudge,
            on_order_typed=self._on_order_typed,
            extra_headers=_EXTRA_HEADERS, add_extra_cells=self._add_extra_cells,
        )
        self._checkboxes.update(section.checkboxes)
        self._order_spins.update(section.order_spins)
        self._up_buttons.update(section.up_buttons)
        self._down_buttons.update(section.down_buttons)
        self._sections.append(section)
        return section

    def _add_extra_cells(self, grid: QGridLayout, row: int, key: str) -> None:
        combo = QComboBox()
        for widget_id, widget_label in _WIDGET_CHOICES:
            combo.addItem(widget_label, widget_id)
        combo.setToolTip(_WIDGET_TOOLTIP)
        combo.currentIndexChanged.connect(lambda _index, k=key: self._on_widget_changed(k))
        self._widget_combos[key] = combo
        grid.addWidget(combo, row, 2)

        default_check = QCheckBox()
        default_check.setToolTip(
            "Put this column on every new graph's card, on top of Channel."
        )
        default_check.toggled.connect(lambda checked, k=key: self._on_default_toggled(k, checked))
        self._default_checks[key] = default_check
        grid.addWidget(default_check, row, 3, alignment=Qt.AlignmentFlag.AlignCenter)

    # -- editing the working card (ticket #49) --------------------------

    def _on_checkbox_toggled(self, key: str, checked: bool) -> None:
        column_key = key
        if checked and not self._card.has_column(column_key):
            self._card = add_column(self._card, build_column_for_key(column_key, self._schema))
        elif not checked and self._card.has_column(column_key):
            self._card = remove_column(self._card, column_key)
        self._sync_rows()
        self._notify_live()

    def _nudge(self, key: str, delta: int) -> None:
        column_key = key
        if self._card.has_column(column_key):
            self._card = move_column(self._card, column_key, delta)
            self._sync_rows()
            self._notify_live()

    def _on_order_typed(self, key: str) -> None:
        column_key = key
        if self._card.has_column(column_key):
            self._card = with_column_order(self._card, column_key, self._order_spins[key].value())
            self._sync_rows()
            self._notify_live()

    def _on_widget_changed(self, key: str) -> None:
        # No _sync_rows() here, unlike every other edit handler: the widget
        # choice does not renumber, and re-driving the combo we just read
        # would recurse.
        column_key = key
        if self._card.has_column(column_key):
            self._card = with_column_widget(
                self._card, column_key, self._widget_combos[key].currentData()
            )
            self._notify_live()

    def _on_default_toggled(self, key: str, checked: bool) -> None:
        # No _sync_rows(): the Default flag does not renumber or reorder, and
        # re-driving the checkbox we just read would recurse. A column has to be
        # on the card before it can be pinned onto fresh graphs -- ticking
        # Default alone does not add it.
        column_key = key
        if self._card.has_column(column_key):
            self._card = with_column_default(self._card, column_key, checked)

    def _on_column_count_changed(self) -> None:
        self._card = with_column_count(self._card, self._column_count_combo.currentData())
        self._notify_live()

    def _on_auto_apply_toggled(self, checked: bool) -> None:
        if self._settings is not None:
            self._settings.setValue(_AUTO_APPLY_SETTINGS_KEY, checked)
        # Turning it on mid-dialog catches the dock up to whatever is already
        # edited; turning it off leaves the last preview in place -- Cancel still
        # reverts, OK still keeps.
        if checked:
            self._notify_live()

    def _notify_live(self) -> None:
        if self._on_live_change is not None and self._auto_apply_check.isChecked():
            self._on_live_change(self._card)

    def _sync_rows(self) -> None:
        """Redraw every row's order / arrow / widget state from the working
        card -- an edit anywhere renumbers the whole card, so all rows follow."""
        for key, checkbox in self._checkboxes.items():
            column_key = key
            on_card = self._card.has_column(column_key)
            column = self._card.column(column_key) if on_card else None

            default_check = self._default_checks[key]
            default_check.setEnabled(on_card)
            blocked = default_check.blockSignals(True)
            default_check.setChecked(bool(on_card and column.default))
            default_check.blockSignals(blocked)

            for section in self._sections:
                if key in section.checkboxes:
                    section.set_row_order(key, column.order if on_card else None)

            # A ranged field's widget is not the user's to pick (§1.34): the
            # predicate family follows the field's Type, so the combo is dead
            # and says where the one gate is instead.
            kind = self._schema.get(key, {}).get("kind")
            ranged = kind_is_ranged(kind)
            combo = self._widget_combos[key]
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
        project (ticket #49). Unchanged from the card handed in when nothing
        was edited, so the caller can skip a no-op save."""
        return self._card
