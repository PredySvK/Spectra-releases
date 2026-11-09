"""
The wizard's step 1, "Samples and what it is": the sample list (add,
remove, the offer of the folder's further files of the same suffix) and the
questions the files cannot answer. A question that does not apply to the data
kind is hidden, not greyed; Simulation / Measurement and the amplitude in the
file start unanswered.
"""

import os
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from core.import_template import (
    AMPLITUDE_FROM_HEADER, DATA_KIND_ORDER_CUT, DATA_KIND_ORDER_RESIDUAL, DATA_KIND_OVERALL_LEVEL, DATA_KIND_SPECTRUM,
    DATA_KIND_TIME_SIGNAL,
)
from orchestration.import_template import TemplateWizardJobs
from view_models.import_template import (
    QUESTION_AMPLITUDE, QUESTION_ORIGIN, QUESTION_TIME, QUESTION_VALUES, TIME_FIXED_RATE, TIME_FROM_COLUMN,
    TIME_RATE_FROM_TEXT, SamplePreview, TemplateWizard,
)

from ._choices import AMPLITUDE_LABELS, CHANNEL_TYPE_LABELS
from ._sample_grid import RED, muted_color

_DATA_KIND_LABELS = (
    (DATA_KIND_ORDER_CUT, "Order cut — the amplitude of one order against speed"),
    (DATA_KIND_SPECTRUM, "Spectrum — the amplitude against frequency"),
    (DATA_KIND_OVERALL_LEVEL, "Overall Level — the level of a band against speed"),
    (DATA_KIND_ORDER_RESIDUAL, "Order residual — the level outside the orders against speed"),
    (DATA_KIND_TIME_SIGNAL, "Time signal — samples against time; a measurement, computed from"),
)
_ORIGINS = ((True, "Simulation (MASTA, ANSYS…)"), (False, "Measurement processed by another tool"))
_TIME_SOURCES = ((TIME_FROM_COLUMN, "The first column is time"), (TIME_FIXED_RATE, "No time column, sample rate:"),
                 (TIME_RATE_FROM_TEXT, "The sample rate is in a text (picked on step 3)"))
_ROW_LABELS = {QUESTION_ORIGIN: "Origin", QUESTION_VALUES: "Values", QUESTION_AMPLITUDE: "Amplitude in the file",
               QUESTION_TIME: "Time"}
_SINGLE_SAMPLE_HINT ="One sample cannot show what changes between files. Add another file if you have one."


def _grey(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color:{muted_color().name()};")
    return label


def _radios(choices, on_choice) -> "tuple[QWidget, QButtonGroup, Dict]":
    """A row of radio buttons; `on_choice(value)` when one is picked. None checked until `_check` says."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    group = QButtonGroup(box)
    buttons = {}
    for value, label in choices:
        radio = QRadioButton(label)
        radio.toggled.connect(lambda on, chosen=value: on and on_choice(chosen))
        group.addButton(radio)
        layout.addWidget(radio)
        buttons[value] = radio
    layout.addStretch(1)
    return box, group, buttons


def _check(group: QButtonGroup, buttons: Dict, value) -> None:
    """Checks the button of `value`, none when no button has it (unanswered), without signals."""
    group.setExclusive(False)
    for key, button in buttons.items():
        button.blockSignals(True)
        button.setChecked(key == value)
        button.blockSignals(False)
    group.setExclusive(True)


class SamplesStep(QWidget):
    """Step 1. `show_wizard` draws the state; every widget hands its choice to `jobs` at once."""

    def __init__(self, jobs: TemplateWizardJobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        inner = QWidget()
        scroll.setWidget(inner)
        layout = QVBoxLayout(inner)

        layout.addWidget(QLabel("<h3>Samples</h3>"))
        self.sample_list = QVBoxLayout()
        layout.addLayout(self.sample_list)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add files…")
        self.add_button.setObjectName("WizardAddFiles")  # Help figure target
        self.add_button.clicked.connect(self._ask_files)
        buttons.addWidget(self.add_button)
        self.offer_button = QPushButton()
        self.offer_button.setFlat(True)
        self.offer_button.setStyleSheet("text-decoration: underline;")
        self.offer_button.clicked.connect(self.add_offered)
        buttons.addWidget(self.offer_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.refusals = QLabel()
        self.refusals.setWordWrap(True)
        self.refusals.setStyleSheet(f"color:{RED};")
        layout.addWidget(self.refusals)
        self.single_hint = _grey(_SINGLE_SAMPLE_HINT)
        layout.addWidget(self.single_hint)

        layout.addWidget(QLabel("<h3>What it is</h3>"))
        self.form = form = QFormLayout()
        layout.addLayout(form)
        layout.addStretch(1)

        kind_box = QWidget()
        kind_box.setObjectName("WizardDataKind")  # Help figure target
        kind_layout = QVBoxLayout(kind_box)
        kind_layout.setContentsMargins(0, 0, 0, 0)
        self.kind_group = QButtonGroup(kind_box)
        self.kind_buttons = {}
        for value, label in _DATA_KIND_LABELS:
            radio = QRadioButton(label)
            radio.toggled.connect(lambda on, chosen=value: on and self.jobs.answer(data_kind=chosen))
            self.kind_group.addButton(radio)
            kind_layout.addWidget(radio)
            self.kind_buttons[value] = radio
        self.kind_guess = _grey()
        kind_layout.addWidget(self.kind_guess)
        form.addRow("Data kind", kind_box)

        self.origin_row, self.origin_group, self.origin_buttons = _radios(
            _ORIGINS, lambda simulated: self.jobs.answer(simulated=simulated))
        self.origin_row.setObjectName("WizardOrigin")  # Help figure target
        form.addRow(_ROW_LABELS[QUESTION_ORIGIN], self.origin_row)

        self.values_row = QWidget()
        self.values_row.setObjectName("WizardValues")  # Help figure target
        values = QHBoxLayout(self.values_row)
        values.setContentsMargins(0, 0, 0, 0)
        box, self.values_group, self.values_buttons = _radios(
            ((False, "Linear"), (True, "In dB")), lambda in_db: self.jobs.answer(values_in_db=in_db))
        values.addWidget(box)
        self.db_reference = QDoubleSpinBox()
        self.db_reference.setDecimals(9)
        self.db_reference.setRange(0.0, 1e9)
        self.db_reference.setSpecialValueText("the usual reference of the unit (1e-6 m/s², 20 µPa)")
        self.db_reference.setMinimumWidth(320)
        self.db_reference.valueChanged.connect(lambda value: self.jobs.answer(db_reference=value))
        values.addWidget(QLabel("reference"))
        values.addWidget(self.db_reference)
        values.addStretch(1)
        form.addRow(_ROW_LABELS[QUESTION_VALUES], self.values_row)

        self.amplitude_row = QWidget()
        self.amplitude_row.setObjectName("WizardAmplitude")  # Help figure target
        amplitude = QVBoxLayout(self.amplitude_row)
        amplitude.setContentsMargins(0, 0, 0, 0)
        box, self.amplitude_group, self.amplitude_buttons = _radios(
            tuple(AMPLITUDE_LABELS) + ((AMPLITUDE_FROM_HEADER, "From the header"),),
            lambda chosen: self.jobs.answer(amplitude=chosen))
        amplitude.addWidget(box)
        self.header_reason = _grey()
        amplitude.addWidget(self.header_reason)
        form.addRow(_ROW_LABELS[QUESTION_AMPLITUDE], self.amplitude_row)

        self.channel_type = QComboBox()
        self.channel_type.setObjectName("WizardChannelType")  # Help figure target
        self.channel_type.addItem("Automatic", "")
        for channel_type, label in CHANNEL_TYPE_LABELS:
            self.channel_type.addItem(label, channel_type)
        self.channel_type.currentIndexChanged.connect(
            lambda _index: self.jobs.answer(channel_type=self.channel_type.currentData() or ""))
        form.addRow("Channel type", self.channel_type)

        self.time_row = QWidget()
        time = QHBoxLayout(self.time_row)
        time.setContentsMargins(0, 0, 0, 0)
        box, self.time_group, self.time_buttons = _radios(
            _TIME_SOURCES, lambda chosen: self.jobs.answer(time_source=chosen))
        time.addWidget(box)
        self.sample_rate = QDoubleSpinBox()
        self.sample_rate.setRange(0.0, 1e7)
        self.sample_rate.setDecimals(3)
        self.sample_rate.setSuffix(" Hz")
        self.sample_rate.valueChanged.connect(lambda value: self.jobs.answer(sample_rate=value))
        box.layout().insertWidget(2, self.sample_rate)
        form.addRow(_ROW_LABELS[QUESTION_TIME], self.time_row)

    # ---- drawing ----------------------------------------------------------------------

    def show_wizard(self, wizard: TemplateWizard) -> None:
        """The samples and the answers as the state has them; no widget reports a change meanwhile."""
        self._show_samples(wizard)
        answers = wizard.answers
        _check(self.kind_group, self.kind_buttons, answers.data_kind)
        kind, cell = wizard.data_kind_guess
        self.kind_guess.setText(f"guessed from '{cell}'" if kind and kind == answers.data_kind else "")
        self.kind_guess.setVisible(bool(self.kind_guess.text()))
        _check(self.origin_group, self.origin_buttons, answers.simulated)
        _check(self.values_group, self.values_buttons, answers.values_in_db)
        _check(self.amplitude_group, self.amplitude_buttons, answers.amplitude or None)
        _check(self.time_group, self.time_buttons, answers.time_source)
        for widget, value in ((self.db_reference, answers.db_reference), (self.sample_rate, answers.sample_rate)):
            if widget.value() != value:
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        self.db_reference.setVisible(answers.values_in_db)
        self.sample_rate.setEnabled(answers.time_source == TIME_FIXED_RATE)
        self.channel_type.blockSignals(True)
        index = self.channel_type.findData(answers.channel_type)
        self.channel_type.setCurrentIndex(index if index >= 0 else 0)
        self.channel_type.blockSignals(False)
        questions = wizard.resolve_questions()
        unanswered = wizard.resolve_unanswered_questions()
        for question, row in ((QUESTION_ORIGIN, self.origin_row), (QUESTION_VALUES, self.values_row),
                              (QUESTION_AMPLITUDE, self.amplitude_row), (QUESTION_TIME, self.time_row)):
            self.form.setRowVisible(row, question in questions)
            label = self.form.labelForField(row)
            label.setTextFormat(Qt.TextFormat.RichText)
            text = _ROW_LABELS[question]
            label.setText(f"{text} <span style='color:{RED}'>*</span>" if question in unanswered else text)
            label.setToolTip("Not answered yet: Next stays off until it is." if question in unanswered else "")

    def show_preview(self, wizard: TemplateWizard, preview: Optional[SamplePreview]) -> None:
        """What only the preview knows: whether "From the header" fits, and the automatic channel type."""
        reason = wizard.resolve_header_amplitude_problem(preview)
        header = self.amplitude_buttons[AMPLITUDE_FROM_HEADER]
        header.setEnabled(not reason)
        header.setToolTip(reason)
        self.header_reason.setText(f"'From the header' does not fit: {reason}." if reason else "")
        self.header_reason.setVisible(bool(reason))
        automatic = "Automatic"
        if preview is not None and preview.automatic_channel_type:
            label = dict(CHANNEL_TYPE_LABELS).get(preview.automatic_channel_type, preview.automatic_channel_type)
            automatic = f"Automatic ({label}, from {preview.automatic_channel_unit})"
        self.channel_type.setItemText(0, automatic)

    def _show_samples(self, wizard: TemplateWizard) -> None:
        while self.sample_list.count():
            item = self.sample_list.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for sample in wizard.samples:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            count = len(sample.sheet_names)
            kind = "text file" if sample.detected_text_format is not None else f"{count} sheet{'s' if count != 1 else ''}"
            line.addWidget(QLabel(f"📄 <b>{os.path.basename(sample.path)}</b>  ·  {kind}"))
            remove = QToolButton()
            remove.setText("✕")
            remove.setToolTip("Remove this sample")
            remove.setEnabled(len(wizard.samples) > 1)
            remove.clicked.connect(lambda _checked=False, path=sample.path: self.jobs.remove_sample(path))
            line.addWidget(remove)
            line.addStretch(1)
            self.sample_list.addWidget(row)
        offered = wizard.offered_samples
        self.offer_button.setVisible(bool(offered))
        if offered:
            self.offer_button.setText(f"{len(offered)} more {wizard.suffix} file{'s' if len(offered) > 1 else ''} "
                                      f"in this folder — add them")
            self.offer_button.setToolTip("\n".join(os.path.basename(path) for path in offered))
        self.refusals.setText("\n".join(wizard.refusals))
        self.refusals.setVisible(bool(wizard.refusals))
        self.single_hint.setVisible(wizard.is_single_sample)

    # ---- adding -------------------------------------------------------------------------

    def add_offered(self) -> None:
        if self.jobs.wizard is not None:
            self.jobs.add_samples(self.jobs.wizard.offered_samples)

    def _ask_files(self) -> None:
        wizard = self.jobs.wizard
        if wizard is None:
            return
        folder = os.path.dirname(wizard.sample_paths[0]) if wizard.samples else ""
        pattern = f"Table files (*{wizard.suffix})" if wizard.suffix else "Table files (*.xlsx *.txt *.csv)"
        paths, _ = QFileDialog.getOpenFileNames(self, "Further samples", folder, f"{pattern};;All files (*)")
        if paths:
            self.jobs.add_samples(paths)
