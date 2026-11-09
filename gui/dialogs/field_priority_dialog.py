# =====================================================================
# FILE: gui/dialogs/field_priority_dialog.py
# =====================================================================
"""
Cursor Settings: which fields the Cursor Box shows and in what order;
the same window as Track cursor Settings for the Track table's columns (§1.278).

A trimmed Configure Filters: the same shared `PriorityGrid`, one row = a checkbox
and a Priority. A Values section (X, Y, Z, Curve name, RMS/Peak) and the metadata
sections offering the fields with "Active Status" ticked -- the same gate, so a field
meant only for the box needs that flag too. Parameter set is not offered (the
box has no value for it); Channel is, beside "Curve name", as in Configure Filters.

The rows, their Priority, the Default column and the keys the open project does
not offer (a field of another project's schema: no row, kept at the end of the
result so the global choice survives a project that lacks them) are the shared
`PriorityGrid`'s (shell §1.301); the dialog adds the window around it. Runs on
the GUI thread: it only builds a few rows.

What sets one tool's window apart -- its Values rows, the window text, the
remembered-geometry key, the Table background slider and Auto apply -- is one
`FieldPrioritySpec` (`CURSOR_SETTINGS`, the default, or `TRACK_CURSOR_SETTINGS`),
so a second tool opens the same window over its own `CursorConfig`. The
selection, Priority, the Field offer and the kept-aside keys are the same for
every caller.

Every window shows "Other curves opacity", the one dim amount the Highlight
uses (cursors §1.293); each slider is a block, caption on top, slider and number
centred under it, in the bottom row left of Auto apply and the buttons.

Restore Defaults (shell §1.292) puts the window back to the spec's
`default_fields` and the opacity sliders to their settings' defaults; keys kept
aside for another project are dropped with it, so OK saves exactly the defaults.

Legend Settings (`LEGEND_SETTINGS`, plot §1.296) is the same window over one
graph's `LegendConfig`: its own rows (`build_sections` -- the whole Field offer,
Parameter set included, plus Unit and Result name), no opacity slider, and
the result comes back as the type of config it was opened with.
"""
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from core.cursor_config import (
    DEFAULT_CURSOR_FIELDS, DEFAULT_TRACK_TABLE_FIELDS, FIELD_AMPLITUDE, FIELD_CURVE, FIELD_X, FIELD_Y,
    FIELD_Z, CursorConfig,
)
from core.filter_card_config import COLUMN_PARAMETER_SET
from core.legend_config import DEFAULT_LEGEND_FIELDS, FIELD_RESULT_NAME, FIELD_UNIT
from core.settings import SETTING_DEFINITIONS
from gui.dialogs.auto_apply import make_auto_apply_check
from gui.dialogs.dialog_state import fit_width_to_scroll_content, remember_dialog_geometry
from gui.dialogs.priority_grid import PriorityGrid
from gui.dialogs.restore_defaults import add_restore_defaults_button
from selection.field_offer import build_field_offer

CURSOR_VALUE_ROWS: Tuple[Tuple[str, str], ...] = (
    (FIELD_X, "X"), (FIELD_Y, "Y"), (FIELD_Z, "Z (spectrogram)"),
    (FIELD_CURVE, "Curve name"), (FIELD_AMPLITUDE, "RMS / Peak"),
)
# Track cursor Settings: X is always above the Track table and Z is a spectrogram's.
TRACK_TABLE_VALUE_ROWS: Tuple[Tuple[str, str], ...] = (
    (FIELD_Y, "Y"), (FIELD_CURVE, "Curve name"), (FIELD_AMPLITUDE, "RMS / Peak"),
)
_NOT_OFFERED = {COLUMN_PARAMETER_SET}
_AUTO_APPLY_TOOLTIP = ("Apply every change to the graphs as you make it, so you can see it. "
                       "Cancel puts everything back the way it was.")

Sections = List[Tuple[str, List[Tuple[str, str]]]]


@dataclass(frozen=True)
class FieldPrioritySpec:
    """One tool's Settings window: title, intro, rows, defaults, geometry key, sliders, Auto apply.

    `build_sections` (schema -> titled rows) replaces the Values section and the
    Field offer when a tool offers rows of its own; `value_rows` is then unused.
    """

    title: str
    intro: str
    value_rows: Tuple[Tuple[str, str], ...]
    default_fields: Tuple[str, ...]
    geometry_key: str
    table_opacity_slider: bool = False
    auto_apply: bool = False
    other_opacity_slider: bool = True
    default_column: bool = False
    build_sections: Optional[Callable[[Dict[str, Dict[str, Any]]], Sections]] = None


CURSOR_SETTINGS = FieldPrioritySpec(
    title="Cursor Settings",
    intro="Which fields the Cursor Box shows, top line first:",
    value_rows=CURSOR_VALUE_ROWS,
    default_fields=DEFAULT_CURSOR_FIELDS,
    geometry_key="cursor_settings",
)
TRACK_CURSOR_SETTINGS = FieldPrioritySpec(
    title="Track cursor Settings",
    intro="Which columns the Track table shows, by Priority (X is always above the table):",
    value_rows=TRACK_TABLE_VALUE_ROWS,
    default_fields=DEFAULT_TRACK_TABLE_FIELDS,
    geometry_key="track_cursor_settings",
    table_opacity_slider=True,
    auto_apply=True,
)


def _legend_sections(schema: Dict[str, Dict[str, Any]]) -> Sections:
    """Everything Configure Filters offers, nothing excluded, plus the two legend-only
    rows: Unit in Identity and Result name in Calculated (plot §1.296, #1022)."""
    offer = build_field_offer(schema)
    return [
        ("Identity", list(offer.identity) + [(FIELD_UNIT, "Unit")]),
        ("Raw metadata", list(offer.raw)),
        ("Excel metadata", list(offer.excel)),
        ("Calculated metadata", list(offer.calculated) + [(FIELD_RESULT_NAME, "Result name")]),
    ]


LEGEND_SETTINGS = FieldPrioritySpec(
    title="Legend Settings",
    intro="Which parts this graph's Curve names are made of, by Priority:",
    value_rows=(),
    default_fields=DEFAULT_LEGEND_FIELDS,
    geometry_key="legend_settings",
    auto_apply=True,
    other_opacity_slider=False,
    default_column=True,
    build_sections=_legend_sections,
)


class FieldPriorityDialog(QDialog):
    def __init__(self, schema: Dict[str, Dict[str, Any]], config: CursorConfig, parent=None, settings=None,
                 other_opacity: int = 25, spec: FieldPrioritySpec = CURSOR_SETTINGS,
                 table_opacity: int = 90,
                 on_live_change: Optional[Callable[[Any, Optional[int], Optional[int]], None]] = None,
                 default_fields: Tuple[str, ...] = ()):
        super().__init__(parent)
        self.setWindowTitle(spec.title)
        self.setMinimumWidth(560)
        self._default_fields = spec.default_fields
        # Called with the working fields, table and other curves opacity after every edit while Auto apply is on;
        # the caller previews them on the graphs and takes the preview back on Cancel.
        self._on_live_change = on_live_change

        sections = spec.build_sections(schema) if spec.build_sections else self._sections(schema, spec.value_rows)
        # A CursorConfig or a LegendConfig: the result keeps its type (`result_config`).
        self._config = config
        # The Default column (a spec with `default_column`): the keys a new graph starts with (plot §1.298).
        self.grid = PriorityGrid(
            [(title, [(key, label, None) for key, label in rows]) for title, rows in sections],
            config.fields,
            defaults=tuple(default_fields) if spec.default_column else None,
            default_tooltip="Start every new graph's legend with this part, in the Priority order.")
        self.grid.changed.connect(self._notify_live)
        self._has_default_column = spec.default_column

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(spec.intro))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        add_restore_defaults_button(buttons, self.restore_defaults)
        bottom = QHBoxLayout()
        self._table_opacity_spin: Optional[QSpinBox] = None
        self._opacity_spin: Optional[QSpinBox] = None
        if spec.other_opacity_slider:
            box, self._opacity_spin = self._build_opacity_block(
                other_opacity, "Other curves opacity:",
                "How visible the dimmed curves stay, in every graph (0 % = invisible, 100 % = not dimmed).",
                self._notify_live)
            bottom.addWidget(box)
        if spec.table_opacity_slider:
            box, self._table_opacity_spin = self._build_opacity_block(
                table_opacity, "Table background opacity:",
                "How opaque the Track table's background is (0 % = transparent, 100 % = solid).",
                self._notify_live)
            bottom.addWidget(box)
        bottom.addStretch(1)
        self._auto_apply_check = None
        if spec.auto_apply and on_live_change is not None:
            self._auto_apply_check = make_auto_apply_check(
                settings, f"{spec.geometry_key}/auto_apply", _AUTO_APPLY_TOOLTIP, self._notify_live)
            bottom.addWidget(self._auto_apply_check)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        size = fit_width_to_scroll_content(self, scroll, (760, 460))
        remember_dialog_geometry(self, settings, spec.geometry_key, default_size=size)

    def result_default_fields(self) -> Tuple[str, ...]:
        """The Default column: the flagged ticked rows in Priority order, then the flagged keys
        that no ticked row shows (a part of another graph or project)."""
        return self.grid.defaults or ()

    @staticmethod
    def _build_opacity_block(percent: int, label: str, tooltip: str, on_change=None) -> Tuple[QWidget, QSpinBox]:
        """A percent slider block: the caption on top, slider + typed value centred under it."""
        box = QWidget()
        box.setToolTip(tooltip)
        block = QVBoxLayout(box)
        block.setContentsMargins(0, 0, 0, 0)
        block.addWidget(QLabel(label), 0, Qt.AlignmentFlag.AlignHCenter)
        row = QHBoxLayout()
        block.addLayout(row)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setMinimumWidth(120)
        spin = QSpinBox()
        spin.setRange(0, 100)
        spin.setSuffix(" %")
        slider.setValue(percent)
        spin.setValue(percent)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        if on_change is not None:
            spin.valueChanged.connect(lambda _value: on_change())
        row.addStretch(1)
        row.addWidget(slider)
        row.addWidget(spin)
        row.addStretch(1)
        return box, spin

    def result_other_opacity(self) -> Optional[int]:
        """The "Other curves opacity" slider's value (%); `None` when the window has no such slider."""
        return self._opacity_spin.value() if self._opacity_spin is not None else None

    def result_table_opacity(self) -> Optional[int]:
        """The Track table background slider's value; `None` when the window has no such slider."""
        return self._table_opacity_spin.value() if self._table_opacity_spin is not None else None

    @staticmethod
    def _sections(schema: Dict[str, Dict[str, Any]],
                  value_rows: Tuple[Tuple[str, str], ...]) -> Sections:
        offer = build_field_offer(schema, excluded=_NOT_OFFERED)
        return [
            ("Values", list(value_rows)),
            ("Identity", list(offer.identity)),
            ("Raw metadata", list(offer.raw)),
            ("Excel metadata", list(offer.excel)),
            ("Calculated metadata", list(offer.calculated)),
        ]

    def _notify_live(self) -> None:
        if (self._on_live_change is not None and self._auto_apply_check is not None
                and self._auto_apply_check.isChecked()):
            self._on_live_change(self.result_config(), self.result_table_opacity(), self.result_other_opacity())

    def restore_defaults(self) -> None:
        """Show the defaults: the spec's fields ticked in their order, the sliders at their settings' defaults."""
        defaults = self._default_fields
        self.grid.reset(defaults, defaults if self._has_default_column else None)
        if self._opacity_spin is not None:
            self._opacity_spin.setValue(SETTING_DEFINITIONS["highlight_other_opacity"].default)
        if self._table_opacity_spin is not None:
            self._table_opacity_spin.setValue(SETTING_DEFINITIONS["track_table_opacity"].default)
        self._notify_live()

    def result_config(self) -> Any:
        """The chosen fields in Priority order, then any keys this project could not offer --
        of the config type the window was opened with."""
        return replace(self._config, fields=self.grid.fields)
