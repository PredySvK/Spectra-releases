"""
The second step: what the columns mean -- data kind, units, channel type, how the channel is
named, the order or sample rate, the source amplitude and dB -- next to the texts around the
first channel.
"""

from typing import List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.channel_types import (
    CHANNEL_TYPE_ACCELEROMETER, CHANNEL_TYPE_GENERAL_DYNAMIC, CHANNEL_TYPE_MICROPHONE,
    CHANNEL_TYPE_VOLTAGE,
)
from core.import_template import (
    DATA_KIND_ORDER_CUT, DATA_KIND_ORDER_RESIDUAL, DATA_KIND_OVERALL_LEVEL, DATA_KIND_SPECTRUM,
    DATA_KIND_TIME_SIGNAL, PICK_HEADER, ImportTemplate, TextPick,
)
from io_modules.import_template import resolve_x_units
from orchestration.import_template import WizardJobs
from view_models.import_template import ImportTemplateWizard, WizardPreview

from ._choices import AMPLITUDE_LABELS, PICK_SOURCE_LABELS, fill_combo, select_data

_DATA_KIND_LABELS = (
    (DATA_KIND_ORDER_CUT, "Order cut (amplitude of one order against speed)"),
    (DATA_KIND_SPECTRUM, "Spectrum (amplitude against frequency)"),
    (DATA_KIND_OVERALL_LEVEL, "Overall Level (band level against speed)"),
    (DATA_KIND_ORDER_RESIDUAL, "Order residual (level outside the orders against speed)"),
    (DATA_KIND_TIME_SIGNAL, "Time signal (samples against time)"),
)
_CHANNEL_TYPE_LABELS = (
    ("", "From the unit and name"),
    (CHANNEL_TYPE_ACCELEROMETER, "Accelerometer"),
    (CHANNEL_TYPE_MICROPHONE, "Microphone"),
    (CHANNEL_TYPE_VOLTAGE, "Voltage"),
    (CHANNEL_TYPE_GENERAL_DYNAMIC, "General dynamic"),
)
_FROM_HEADER = "From the header"


class _PickEditor(QWidget):
    """Where a piece of text is taken from and how it is cut out (a TextPick)."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.source = QComboBox()
        fill_combo(self.source, PICK_SOURCE_LABELS)
        self.row_above = QSpinBox()
        self.row_above.setRange(0, 50)
        self.row_above.setToolTip("Header row counted up from the heading row (0 = the heading row)")
        self.split = QLineEdit()
        self.split.setPlaceholderText("split by")
        self.split.setMaximumWidth(60)
        self.piece = QSpinBox()
        self.piece.setRange(0, 50)
        self.piece.setToolTip("Piece number after the split (0 = the first)")
        self.after = QLineEdit()
        self.after.setPlaceholderText("after")
        self.before = QLineEdit()
        self.before.setPlaceholderText("before")
        for label, widget in (("", self.source), ("row", self.row_above), ("", self.split),
                              ("piece", self.piece), ("", self.after), ("", self.before)):
            if label:
                layout.addWidget(QLabel(label))
            layout.addWidget(widget)
        self.source.currentIndexChanged.connect(self._on_source)
        for spin in (self.row_above, self.piece):
            spin.valueChanged.connect(self.changed)
        for edit in (self.split, self.after, self.before):
            edit.textChanged.connect(self.changed)

    def _on_source(self):
        self.row_above.setEnabled(self.source.currentData() == PICK_HEADER)
        self.changed.emit()

    def set_pick(self, pick: TextPick) -> None:
        widgets = (self.source, self.row_above, self.split, self.piece, self.after, self.before)
        for widget in widgets:
            widget.blockSignals(True)
        select_data(self.source, pick.source)
        self.row_above.setValue(pick.row_above)
        self.split.setText(pick.split)
        self.piece.setValue(pick.piece)
        self.after.setText(pick.after)
        self.before.setText(pick.before)
        self.row_above.setEnabled(pick.source == PICK_HEADER)
        for widget in widgets:
            widget.blockSignals(False)

    def pick(self) -> TextPick:
        return TextPick(row_above=self.row_above.value(), split=self.split.text(), piece=self.piece.value(),
                        after=self.after.text(), before=self.before.text(), source=self.source.currentData())


class _NamePartRow(QWidget):
    """One part of the channel name: literal text or a picked piece."""

    changed = Signal()
    removed = Signal(object)

    def __init__(self, part, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.kind = QComboBox()
        self.kind.addItems(["Picked text", "Literal text"])
        self.literal = QLineEdit()
        self.picker = _PickEditor()
        remove = QPushButton("✕")
        remove.setFixedWidth(28)
        layout.addWidget(self.kind)
        layout.addWidget(self.literal, 1)
        layout.addWidget(self.picker, 1)
        layout.addWidget(remove)
        if isinstance(part, TextPick):
            self.picker.set_pick(part)
        else:
            self.kind.setCurrentIndex(1)
            self.literal.setText(part)
        self._show_kind()
        self.kind.currentIndexChanged.connect(self._on_kind)
        self.literal.textChanged.connect(self.changed)
        self.picker.changed.connect(self.changed)
        remove.clicked.connect(lambda: self.removed.emit(self))

    def _show_kind(self):
        literal = self.kind.currentIndex() == 1
        self.literal.setVisible(literal)
        self.picker.setVisible(not literal)

    def _on_kind(self):
        self._show_kind()
        self.changed.emit()

    def part(self):
        return self.literal.text() if self.kind.currentIndex() == 1 else self.picker.pick()


class MeaningStep(QWidget):
    """The column meaning. `changed` is a choice made here."""

    changed = Signal()

    def __init__(self, jobs: WizardJobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self._name_rows: List[_NamePartRow] = []
        columns = QHBoxLayout(self)
        left = QFormLayout()
        columns.addLayout(left, 3)
        self.data_kind = QComboBox()
        fill_combo(self.data_kind, _DATA_KIND_LABELS)
        self.data_kind.currentIndexChanged.connect(self.changed)
        left.addRow("Data kind", self.data_kind)
        self.x_unit = QComboBox()
        self._fill_x_units(DATA_KIND_ORDER_CUT, "")
        self.x_unit.currentIndexChanged.connect(self.changed)
        left.addRow("X unit (speed or frequency)", self.x_unit)
        self.amplitude_unit = QComboBox()
        self.amplitude_unit.currentIndexChanged.connect(self.changed)
        left.addRow("Amplitude unit", self.amplitude_unit)
        self.channel_type = QComboBox()
        fill_combo(self.channel_type, _CHANNEL_TYPE_LABELS)
        self.channel_type.currentIndexChanged.connect(self.changed)
        left.addRow("Channel type", self.channel_type)

        name_box = QGroupBox("Channel name (the parts joined)")
        self.name_parts = QVBoxLayout(name_box)
        add_part = QPushButton("+ Add part")
        add_part.clicked.connect(lambda: self._add_name_part(TextPick()))
        self.name_parts.addWidget(add_part)
        left.addRow(name_box)

        axis = QWidget()
        axis_layout = QHBoxLayout(axis)
        axis_layout.setContentsMargins(0, 0, 0, 0)
        self.axis_on = QCheckBox()
        self.axis_pick = _PickEditor()
        axis_layout.addWidget(self.axis_on)
        axis_layout.addWidget(self.axis_pick, 1)
        self.axis_on.toggled.connect(self.changed)
        self.axis_pick.changed.connect(self.changed)
        left.addRow("Axis (X/Y/Z)", axis)

        order = QWidget()
        order_layout = QHBoxLayout(order)
        order_layout.setContentsMargins(0, 0, 0, 0)
        self.order_kind = QComboBox()
        self.order_kind.addItems(["Fixed number", "From text"])
        self.order_fixed = QDoubleSpinBox()
        self.order_fixed.setRange(-1000.0, 1000.0)
        self.order_fixed.setDecimals(4)
        self.order_pick = _PickEditor()
        for widget in (self.order_kind, self.order_fixed, self.order_pick):
            order_layout.addWidget(widget)
        self.order_kind.currentIndexChanged.connect(self.changed)
        self.order_fixed.valueChanged.connect(self.changed)
        self.order_pick.changed.connect(self.changed)
        self.order_row = order
        left.addRow("Order (order cut only)", order)

        self.time_column = QCheckBox("The first column is time")
        self.time_column.setChecked(True)
        self.time_column.toggled.connect(self.changed)
        left.addRow("Time signal", self.time_column)
        rate = QWidget()
        rate_layout = QHBoxLayout(rate)
        rate_layout.setContentsMargins(0, 0, 0, 0)
        self.rate_kind = QComboBox()
        self.rate_kind.addItems(["Fixed number (Hz)", "From text"])
        self.rate_fixed = QDoubleSpinBox()
        self.rate_fixed.setRange(0.0, 10_000_000.0)
        self.rate_fixed.setDecimals(3)
        self.rate_pick = _PickEditor()
        for widget in (self.rate_kind, self.rate_fixed, self.rate_pick):
            rate_layout.addWidget(widget)
        self.rate_kind.currentIndexChanged.connect(self.changed)
        self.rate_fixed.valueChanged.connect(self.changed)
        self.rate_pick.changed.connect(self.changed)
        self.rate_row = rate
        left.addRow("Sample rate (no time column)", rate)
        self.speed_channel = QLineEdit()
        self.speed_channel.setPlaceholderText("name of the channel that is the speed (rpm or tacho pulses)")
        self.speed_channel.textChanged.connect(self.changed)
        left.addRow("Speed channel (time signal)", self.speed_channel)

        origin = QWidget()
        origin_layout = QHBoxLayout(origin)
        origin_layout.setContentsMargins(0, 0, 0, 0)
        self.simulated = QRadioButton("Simulated")
        self.measured = QRadioButton("Measured")
        origin_group = QButtonGroup(self)
        for widget in (self.simulated, self.measured):
            origin_group.addButton(widget)
            origin_layout.addWidget(widget)
        origin_group.buttonToggled.connect(lambda *_: self.changed.emit())
        left.addRow("The results are", origin)
        self.bare_amplitude = QComboBox()
        fill_combo(self.bare_amplitude, AMPLITUDE_LABELS)
        self.bare_amplitude.currentIndexChanged.connect(self.changed)
        left.addRow('A bare "Amplitude" means', self.bare_amplitude)
        self.fixed_amplitude = QComboBox()
        fill_combo(self.fixed_amplitude, (("", "Recognised from the header"),) + AMPLITUDE_LABELS)
        self.fixed_amplitude.currentIndexChanged.connect(self.changed)
        left.addRow("Source amplitude", self.fixed_amplitude)
        self.values_in_db = QCheckBox("The values are in dB")
        self.values_in_db.toggled.connect(self.changed)
        left.addRow(self.values_in_db)
        self.db_reference = QLineEdit()
        self.db_reference.setPlaceholderText("usual for the amplitude unit (1e-6 m/s², 20 µPa)")
        self.db_reference.setToolTip("The value 0 dB stands for, in the amplitude unit of the linear value.")
        self.db_reference.textChanged.connect(self.changed)
        left.addRow("dB reference", self.db_reference)

        texts_box = QGroupBox("Texts around the first channel")
        texts_layout = QVBoxLayout(texts_box)
        self.source_texts = QTableWidget(0, 2)
        self.source_texts.setHorizontalHeaderLabels(["Where", "Text"])
        self.source_texts.horizontalHeader().setStretchLastSection(True)
        self.source_texts.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        texts_layout.addWidget(self.source_texts)
        columns.addWidget(texts_box, 2)
        self.changed.connect(self._show_enabled)

    def show_template(self, template: ImportTemplate) -> None:
        """The template's meaning choices; the caller keeps `changed` from reaching the wizard meanwhile."""
        select_data(self.data_kind, template.data_kind)
        self._fill_x_units(template.data_kind, template.x_unit)
        self._fill_amplitude_units("", template.amplitude_unit)
        select_data(self.channel_type, template.channel_type)
        for row in list(self._name_rows):
            self._remove_name_part(row)
        for part in template.channel_name:
            self._add_name_part(part)
        self.axis_on.setChecked(template.axis is not None)
        self.axis_pick.set_pick(template.axis or TextPick())
        fixed_order = not isinstance(template.order, TextPick)
        self.order_kind.setCurrentIndex(0 if fixed_order else 1)
        self.order_fixed.setValue(float(template.order) if fixed_order else 1.0)
        self.order_pick.set_pick(template.order if not fixed_order else TextPick())
        self.time_column.setChecked(template.time_column)
        fixed_rate = not isinstance(template.sample_rate, TextPick)
        self.rate_kind.setCurrentIndex(0 if fixed_rate else 1)
        self.rate_fixed.setValue(float(template.sample_rate) if fixed_rate else 0.0)
        self.rate_pick.set_pick(template.sample_rate if not fixed_rate else TextPick())
        self.speed_channel.setText(template.speed_channel)
        self.simulated.setChecked(template.simulated)
        self.measured.setChecked(not template.simulated)
        select_data(self.bare_amplitude, template.source_amplitude)
        select_data(self.fixed_amplitude, template.fixed_source_amplitude)
        self.values_in_db.setChecked(template.values_in_db)
        self.db_reference.setText(f"{template.db_reference:g}" if template.db_reference else "")
        self._show_enabled()

    def show_preview(self, preview: WizardPreview) -> None:
        """The texts around the first channel; the amplitude units the header's unit allows."""
        self.source_texts.setRowCount(len(preview.source_texts))
        for row, (where, text) in enumerate(preview.source_texts):
            self.source_texts.setItem(row, 0, QTableWidgetItem(where))
            self.source_texts.setItem(row, 1, QTableWidgetItem(text))
        if self.jobs.wizard is not None and not self.jobs.wizard.template.amplitude_unit and preview.channels:
            header_unit = preview.channels[0].unit
            self._fill_amplitude_units("" if header_unit == "unknown" else header_unit, "")

    def _fill_amplitude_units(self, header_unit: str, chosen: str) -> None:
        """The amplitude unit choices for the sample's header unit, `chosen` selected ("" = from the header)."""
        self.amplitude_unit.blockSignals(True)
        self.amplitude_unit.clear()
        self.amplitude_unit.addItem(f"{_FROM_HEADER} ({header_unit})" if header_unit else _FROM_HEADER, "")
        for unit in ImportTemplateWizard.resolve_amplitude_unit_options(header_unit):
            self.amplitude_unit.addItem(unit, unit)
        if chosen and self.amplitude_unit.findData(chosen) < 0:
            self.amplitude_unit.addItem(chosen, chosen)
        select_data(self.amplitude_unit, chosen)
        self.amplitude_unit.blockSignals(False)

    def _add_name_part(self, part) -> None:
        row = _NamePartRow(part)
        row.changed.connect(self.changed)
        row.removed.connect(lambda widget: (self._remove_name_part(widget), self.changed.emit()))
        self._name_rows.append(row)
        self.name_parts.insertWidget(self.name_parts.count() - 1, row)
        self.changed.emit()

    def _remove_name_part(self, row: _NamePartRow) -> None:
        self._name_rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _fill_x_units(self, data_kind: str, chosen: str) -> None:
        """The X units the data kind knows; the chosen one stays when it is one of them, else "from the header"."""
        self.x_unit.blockSignals(True)
        self.x_unit.clear()
        self.x_unit.addItem(_FROM_HEADER, "")
        for unit in resolve_x_units(data_kind):
            self.x_unit.addItem(unit, unit)
        select_data(self.x_unit, chosen)
        self.x_unit.blockSignals(False)

    def _show_enabled(self) -> None:
        self.axis_pick.setEnabled(self.axis_on.isChecked())
        self.order_row.setEnabled(self.data_kind.currentData() == DATA_KIND_ORDER_CUT)
        timed = self.data_kind.currentData() == DATA_KIND_TIME_SIGNAL
        self.time_column.setEnabled(timed)
        self.rate_row.setEnabled(timed and not self.time_column.isChecked())
        self.speed_channel.setEnabled(timed)
        for widget in (self.bare_amplitude, self.fixed_amplitude, self.values_in_db):
            widget.setEnabled(not timed)     # a time signal is read as recorded
        self.db_reference.setEnabled(self.values_in_db.isChecked() and not timed)
        self.rate_fixed.setVisible(self.rate_kind.currentIndex() == 0)
        self.rate_pick.setVisible(self.rate_kind.currentIndex() == 1)
        self._fill_x_units(self.data_kind.currentData(), self.x_unit.currentData() or "")
        fixed_order = self.order_kind.currentIndex() == 0
        self.order_fixed.setVisible(fixed_order)
        self.order_pick.setVisible(not fixed_order)

    def collect(self) -> dict:
        """The meaning choices as ImportTemplate fields."""
        return dict(
            data_kind=self.data_kind.currentData(),
            x_unit=self.x_unit.currentData() or "",
            amplitude_unit=self.amplitude_unit.currentData() or "",
            channel_type=self.channel_type.currentData() or "",
            channel_name=tuple(row.part() for row in self._name_rows),
            axis=self.axis_pick.pick() if self.axis_on.isChecked() else None,
            order=self.order_fixed.value() if self.order_kind.currentIndex() == 0 else self.order_pick.pick(),
            simulated=self.simulated.isChecked(),
            source_amplitude=self.bare_amplitude.currentData(),
            fixed_source_amplitude=self.fixed_amplitude.currentData() or "",
            values_in_db=self.values_in_db.isChecked() and self.data_kind.currentData() != DATA_KIND_TIME_SIGNAL,
            db_reference=self._read_db_reference(),
            time_column=self.time_column.isChecked() or self.data_kind.currentData() != DATA_KIND_TIME_SIGNAL,
            sample_rate=self.rate_fixed.value() if self.rate_kind.currentIndex() == 0 else self.rate_pick.pick(),
            speed_channel=self.speed_channel.text().strip(),
        )

    def _read_db_reference(self) -> float:
        """The reference typed in, 0 (the unit's usual one) when blank or not a positive number."""
        try:
            return max(0.0, float(self.db_reference.text().replace(",", ".")))
        except ValueError:
            return 0.0
