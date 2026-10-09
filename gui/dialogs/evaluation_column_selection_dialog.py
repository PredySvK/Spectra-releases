# FILE: gui/dialogs/evaluation_column_selection_dialog.py
# =====================================================================
"""
Dialog for selecting which metadata and identity columns appear in the
Evaluation table (Issue #139).

Offers fields from four distinct groups:
1. Identity: Channel, Direction, Channel type, File name, Data Pool label, Result set
   (core.filter_card_config.IDENTITY_BUILTIN_ORDER).
2. Raw metadata: Schema fields read directly from measurement files (layer == "channel").
3. Excel metadata: Schema fields from metadata spreadsheets (layer != "channel").
4. Calculated metadata: Analysis type, Order, Parameter set
   (core.filter_card_config.CALCULATED_BUILTIN_ORDER).

Strict active-only rule (Issue #6, ADR §1.64 point 10):
Only schema fields with `is_active == True` (or defaulted True, not False) are
offered. Fields disabled in the Metadata Editor MUST NOT be offered.

Dialog geometry is remembered between invocations via dialog_state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QGroupBox, QLabel,
    QScrollArea, QVBoxLayout, QWidget,
)

from core.filter_card_config import (
    BUILTIN_COLUMN_LABELS, CALCULATED_BUILTIN_ORDER,
    GROUP_RAW, IDENTITY_BUILTIN_ORDER,
)
from gui.dialogs.dialog_state import remember_dialog_geometry
from selection.trace_filter import schema_field_group


class EvaluationColumnSelectionDialog(QDialog):
    """Modal dialog to choose metadata and identity columns for the Evaluation table."""

    def __init__(
        self,
        schema: Mapping[str, Mapping[str, Any]],
        selected_columns: Sequence[str] = (),
        parent: Optional[QWidget] = None,
        settings: Optional[Any] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Evaluation Columns")

        self._schema = schema
        self._checkboxes: Dict[str, QCheckBox] = {}

        # Collect available fields per group
        # 1. Identity
        identity_fields = [(key, BUILTIN_COLUMN_LABELS.get(key, key)) for key in IDENTITY_BUILTIN_ORDER]

        # 2. Raw & 3. Excel (strictly active only)
        raw_fields: List[Tuple[str, str]] = []
        excel_fields: List[Tuple[str, str]] = []

        for key, field_cfg in schema.items():
            # Check is_active (rule from Issue #6 and ADR §1.64 point 10)
            if field_cfg.get("is_active", True) is False:
                continue

            label = field_cfg.get("custom_label") or field_cfg.get("field_name") or key
            group = schema_field_group(dict(field_cfg))
            if group == GROUP_RAW:
                raw_fields.append((key, label))
            else:
                excel_fields.append((key, label))

        # Sort schema fields alphabetically by label
        raw_fields.sort(key=lambda item: item[1].casefold())
        excel_fields.sort(key=lambda item: item[1].casefold())

        # 4. Calculated
        calculated_fields = [(key, BUILTIN_COLUMN_LABELS.get(key, key)) for key in CALCULATED_BUILTIN_ORDER]

        # Valid keys that are offered
        valid_offered_keys = {k for k, _ in identity_fields + raw_fields + excel_fields + calculated_fields}

        # Initialize selected keys, preserving input order and pruning unoffered keys
        self._selected_keys: List[str] = [k for k in selected_columns if k in valid_offered_keys]

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # Scrollable area
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(8)

        # Add section groups
        content_layout.addWidget(self._build_group("Identity", identity_fields))
        content_layout.addWidget(self._build_group("Raw metadata", raw_fields))
        content_layout.addWidget(self._build_group("Excel metadata", excel_fields))
        content_layout.addWidget(self._build_group("Calculated metadata", calculated_fields))
        content_layout.addStretch()

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        # Dialog buttons (OK / Cancel)
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        remember_dialog_geometry(self, settings, "evaluation_column_selection", default_size=(450, 550))

    def _build_group(self, title: str, fields: List[Tuple[str, str]]) -> QGroupBox:
        box = QGroupBox(title, self)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(6, 6, 6, 6)
        box_layout.setSpacing(4)

        if not fields:
            empty_lbl = QLabel("(No active fields)", box)
            empty_lbl.setStyleSheet("color: #808080; font-style: italic;")
            box_layout.addWidget(empty_lbl)
            return box

        for key, label in fields:
            cb = QCheckBox(label, box)
            cb.setChecked(key in self._selected_keys)
            cb.toggled.connect(lambda checked, k=key: self._on_checkbox_toggled(checked, k))
            self._checkboxes[key] = cb
            box_layout.addWidget(cb)

        return box

    def _on_checkbox_toggled(self, checked: bool, key: str) -> None:
        if checked:
            if key not in self._selected_keys:
                self._selected_keys.append(key)
        else:
            if key in self._selected_keys:
                self._selected_keys.remove(key)

    def selected_columns(self) -> Tuple[str, ...]:
        """Returns the ordered tuple of chosen column keys."""
        return tuple(self._selected_keys)
