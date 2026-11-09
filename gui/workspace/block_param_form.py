# =====================================================================
# FILE: gui/workspace/block_param_form.py
# =====================================================================
"""
Draws one block's Properties form from a `view_models.workflow.BlockForm`.

Which rows the form has, what each offers and how its entries become params are
decided in `view_models/workflow` without Qt (#898); this widget only draws the
rows and hands back what is in them (`entries`).

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Any, Dict, Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLineEdit, QSpinBox, QWidget,
)

from view_models.workflow import (
    WIDGET_CHECK, WIDGET_CHOICE, WIDGET_DECIMAL, WIDGET_INTEGER, BlockForm, BlockFormField,
)

# Wide enough for any FFT size / step the DSP configs carry, without
# pretending to know a real range -- the params rule refuses what is out of
# place. This form is a mirror, not a validator.
_INT_LIMIT = 10_000_000
_FLOAT_LIMIT = 1.0e9


def _make_widget(row: BlockFormField) -> QWidget:
    if row.widget == WIDGET_CHOICE:
        w = QComboBox()
        for label, data in row.choices:
            w.addItem(label, data)
        w.setCurrentIndex(max(w.findData(row.value), 0))
        return w
    if row.widget == WIDGET_CHECK:
        w = QCheckBox()
        w.setChecked(bool(row.value))
        return w
    if row.widget == WIDGET_INTEGER:
        w = QSpinBox()
        w.setRange(-_INT_LIMIT, _INT_LIMIT)
        try:
            w.setValue(int(row.value))
        except (TypeError, ValueError):
            pass
        return w
    if row.widget == WIDGET_DECIMAL:
        w = QDoubleSpinBox()
        w.setDecimals(4)
        w.setRange(-_FLOAT_LIMIT, _FLOAT_LIMIT)
        try:
            w.setValue(float(row.value))
        except (TypeError, ValueError):
            pass
        return w
    return QLineEdit(str(row.value))


def _entry(widget: QWidget) -> Any:
    if isinstance(widget, QComboBox):
        return widget.currentData()
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
        return widget.value()
    return widget.text()


class BlockParamForm(QWidget):
    """`show_form(form, read_only=...)` draws one row per `BlockForm` field;
    `entries()` hands back what the rows hold, for
    `resolve_block_form_params`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._form = QFormLayout(self)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._widgets: Dict[str, Tuple[BlockFormField, QWidget]] = {}
        self._block_form: Optional[BlockForm] = None

    def clear(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._widgets = {}
        self._block_form = None

    def show_form(self, form: BlockForm, *, read_only: bool = False) -> None:
        self.clear()
        self._block_form = form
        for row in form.fields:
            widget = _make_widget(row)
            widget.setEnabled(not read_only)
            self._form.addRow(row.label, widget)
            self._widgets[row.name] = (row, widget)

    def entries(self) -> Dict[str, Any]:
        return {name: _entry(widget) for name, (_, widget) in self._widgets.items()}

    @property
    def block_form(self) -> Optional[BlockForm]:
        return self._block_form
