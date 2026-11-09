"""
The small dialog step 3 opens to make a metadata field of a chip (#1032): its
name (the key of "key = value" is offered), whether it is the number in the chip
(with the unit made of the letters after it, which can be corrected) or the
whole chip, and the field kind, which is detected from the values unless the
user says one. The chip's value in every sample is listed with what the field
makes of it.
"""

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QRadioButton, QVBoxLayout,
)

from core.import_template import FIELD_KINDS, ChipRef, MetadataField
from io_modules.import_template import resolve_chip_number
from view_models.import_template import FieldOffer, build_metadata_field


def _made_of(value: str) -> str:
    found = resolve_chip_number(value)
    return f"{found[0]:g}" if found is not None else value


class FieldDialog(QDialog):
    """Name, value and kind of one metadata field; `field()` is the result once accepted."""

    def __init__(self, ref: ChipRef, offer: FieldOffer, existing: Optional[MetadataField] = None, parent=None):
        super().__init__(parent)
        self.ref, self.offer = ref, offer
        self.setWindowTitle("Metadata field")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(existing.field if existing is not None else offer.name)
        self.name.setPlaceholderText("e.g. Torque")
        form.addRow("Field name:", self.name)
        layout.addLayout(form)
        self.as_number = QRadioButton("The number in the chip")
        self.as_chip = QRadioButton("The whole chip")
        self.as_number.setEnabled(offer.is_number)
        number = offer.is_number and (existing is None or existing.is_number)
        self.as_number.setChecked(number)
        self.as_chip.setChecked(not number)
        layout.addWidget(self.as_number)
        if not offer.is_number:
            reason = QLabel(f"The number is not offered: {offer.number_problem}.")
            reason.setWordWrap(True)
            layout.addWidget(reason)
        layout.addWidget(self.as_chip)
        more = QFormLayout()
        self.unit = QLineEdit(existing.unit if existing is not None and existing.is_number else offer.unit)
        self.unit.setPlaceholderText("e.g. Nm")
        self.unit.setToolTip("Made of the letters after the number; correct it when they are more than the unit.")
        more.addRow("Unit:", self.unit)
        self.kind = QComboBox()
        self.kind.addItem("detected from the values", "")
        for kind in FIELD_KINDS:
            self.kind.addItem(kind, kind)
        if existing is not None and existing.kind:
            self.kind.setCurrentIndex(self.kind.findData(existing.kind))
        more.addRow("Kind:", self.kind)
        layout.addLayout(more)
        self.values = QLabel()
        self.values.setWordWrap(True)
        layout.addWidget(self.values)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        for widget in (self.name, self.unit):
            widget.textChanged.connect(self._refresh)
        self.as_number.toggled.connect(self._refresh)
        self._refresh()

    def field(self) -> MetadataField:
        return build_metadata_field(self.name.text(), self.ref, self.offer, as_number=self.as_number.isChecked(),
                                    unit=self.unit.text(), kind=self.kind.currentData())

    def _refresh(self) -> None:
        number = self.as_number.isChecked()
        self.unit.setEnabled(number)
        shown = [f"{value}  →  {_made_of(value)} {self.unit.text().strip()}".strip() if number else value
                 for value in self.offer.values]
        self.values.setText("<br>".join(shown))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.name.text().strip()))
