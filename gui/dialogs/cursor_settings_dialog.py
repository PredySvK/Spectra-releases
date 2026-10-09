# =====================================================================
# FILE: gui/dialogs/cursor_settings_dialog.py
# =====================================================================
"""
Cursor Settings: which fields the Cursor Box shows and in what order (ADR §1.149).

A trimmed Configure Filters: the same shared `PriorityGrid`, one row = a checkbox
and a Priority. A Values section (X, Y, Z, Curve name, RMS/Peak) and the metadata
sections offering the fields marked "Use as Filter" -- the same gate, so a field
meant only for the box needs that flag too. Parameter set and Channel are not
offered (the box has no value for the first; "Curve name" is the second).

The dialog edits a `CursorConfig` through the pure helpers in `core.cursor_config`.
Keys the open project does not offer (a field of another project's schema) get no
row; they are kept at the end of the result so the global choice survives a
project that lacks them. Runs on the GUI thread: it only builds a few rows.
"""
from typing import Any, Dict, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from core.cursor_config import (
    FIELD_AMPLITUDE, FIELD_CURVE, FIELD_X, FIELD_Y, FIELD_Z, CursorConfig, move_field, with_field,
    with_field_order,
)
from core.filter_card_config import (
    BUILTIN_COLUMN_LABELS, CALCULATED_BUILTIN_ORDER, COLUMN_CHANNEL, COLUMN_PARAMETER_SET, GROUP_RAW,
    IDENTITY_BUILTIN_ORDER,
)
from gui.dialogs.dialog_state import fit_width_to_scroll_content, remember_dialog_geometry
from gui.dialogs.priority_grid import PriorityGrid
from selection.trace_filter import schema_field_group

_VALUE_ROWS: Tuple[Tuple[str, str], ...] = (
    (FIELD_X, "X"), (FIELD_Y, "Y"), (FIELD_Z, "Z (spectrogram)"),
    (FIELD_CURVE, "Curve name"), (FIELD_AMPLITUDE, "RMS / Peak"),
)
_NOT_OFFERED = {COLUMN_CHANNEL, COLUMN_PARAMETER_SET}


class CursorSettingsDialog(QDialog):
    def __init__(self, schema: Dict[str, Dict[str, Any]], config: CursorConfig, parent=None, settings=None,
                 other_opacity: int = 25):
        super().__init__(parent)
        self.setWindowTitle("Cursor Settings")
        self.setMinimumWidth(560)

        sections = self._sections(schema)
        offered = {key for _title, rows in sections for key, _label in rows}
        self._kept_aside = tuple(k for k in config.fields if k not in offered)
        self._config = CursorConfig(tuple(k for k in config.fields if k in offered))
        self._grids: List[PriorityGrid] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Which fields the Cursor Box shows, top line first:"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        row = QHBoxLayout(body)
        for title, rows in sections:
            grid = PriorityGrid(
                title, [(key, label, None) for key, label in rows],
                checked_keys=set(self._config.fields), on_toggled=self._on_toggled,
                on_nudge=self._on_nudge, on_order_typed=self._on_order_typed)
            self._grids.append(grid)
            row.addWidget(grid)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self._build_opacity_row(other_opacity))
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        layout.addLayout(bottom)

        self._sync_rows()
        size = fit_width_to_scroll_content(self, scroll, (760, 460))
        remember_dialog_geometry(self, settings, "cursor_settings", default_size=size)

    def _build_opacity_row(self, percent: int) -> QWidget:
        """Slider + typed value for how visible the other curves stay while Highlight is on."""
        box = QWidget()
        box.setToolTip("Highlight: how visible the curves other than the highlighted one stay "
                       "(0 % = invisible, 100 % = not dimmed).")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Other curves opacity (Highlight):"))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setMinimumWidth(120)
        self._opacity_spin = QSpinBox()
        self._opacity_spin.setRange(0, 100)
        self._opacity_spin.setSuffix(" %")
        slider.setValue(percent)
        self._opacity_spin.setValue(percent)
        slider.valueChanged.connect(self._opacity_spin.setValue)
        self._opacity_spin.valueChanged.connect(slider.setValue)
        row.addWidget(slider)
        row.addWidget(self._opacity_spin)
        return box

    def result_other_opacity(self) -> int:
        return self._opacity_spin.value()

    @staticmethod
    def _sections(schema: Dict[str, Dict[str, Any]]) -> List[Tuple[str, List[Tuple[str, str]]]]:
        raw, excel = [], []
        for key, config in schema.items():
            if config.get("usable_as_filter", False):
                (raw if schema_field_group(config) == GROUP_RAW else excel).append(
                    (key, config.get("custom_label", key)))
        by_label = lambda item: item[1]
        builtins = lambda order: [(k, BUILTIN_COLUMN_LABELS[k]) for k in order if k not in _NOT_OFFERED]
        return [
            ("Values", list(_VALUE_ROWS)),
            ("Identity", builtins(IDENTITY_BUILTIN_ORDER)),
            ("Raw metadata", sorted(raw, key=by_label)),
            ("Excel metadata", sorted(excel, key=by_label)),
            ("Calculated metadata", builtins(CALCULATED_BUILTIN_ORDER)),
        ]

    def _on_toggled(self, key: str, checked: bool) -> None:
        self._config = with_field(self._config, key, checked)
        self._sync_rows()

    def _on_nudge(self, key: str, delta: int) -> None:
        self._config = move_field(self._config, key, delta)
        self._sync_rows()

    def _on_order_typed(self, key: str) -> None:
        spin = next(g.order_spins[key] for g in self._grids if key in g.order_spins)
        self._config = with_field_order(self._config, key, spin.value())
        self._sync_rows()

    def _sync_rows(self) -> None:
        for grid in self._grids:
            for key in grid.checkboxes:
                position = self._config.fields.index(key) + 1 if key in self._config.fields else None
                grid.set_row_order(key, position)

    def result_config(self) -> CursorConfig:
        """The chosen fields in Priority order, then any keys this project could not offer."""
        return CursorConfig(self._config.fields + self._kept_aside)
