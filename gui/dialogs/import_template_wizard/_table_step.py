"""
The wizard's step 2, "Table": one summary line per setting with its
choices open under it (nothing collapsed) -- the heading row and data start
(set by a click on a row number in the preview), the sheets, the column
layout, the units "Detected: …" and a text file's format "Detected: …".
"""

from typing import Optional

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QHBoxLayout, QLabel, QRadioButton, QScrollArea, QSpinBox, QVBoxLayout,
    QWidget,
)

from core.import_template import (
    LAYOUT_SHARED_X, LAYOUT_SINGLE_CURVE, LAYOUT_XY_PAIRS, SHEETS_ALL, SHEETS_FIRST_N, SHEETS_LISTED,
    SHEETS_WITHOUT_LAST_N,
)
from io_modules.import_template import resolve_x_units
from orchestration.import_template import TemplateWizardJobs
from view_models.import_template import SamplePreview, TemplateWizard, resolve_amplitude_unit_options

from ._choices import DECIMAL_LABELS, DELIMITER_LABELS, ENCODING_LABELS, select_data
from ._sample_grid import RED, muted_color

_LAYOUTS = (
    (LAYOUT_XY_PAIRS, "X/Y pairs", "X Y │ X Y │ X Y"),
    (LAYOUT_SHARED_X, "Shared X", "X │ Y Y Y Y"),
    (LAYOUT_SINGLE_CURVE, "One curve per sheet", "X Y │ (the rest is not read)"),
)
_SHEET_RULES = (
    (SHEETS_ALL, "All (a sheet without the heading row is skipped)"), (SHEETS_FIRST_N, "The first N"),
    (SHEETS_WITHOUT_LAST_N, "Without the last N"), (SHEETS_LISTED, "Listed by name"),
)
_FROM_HEADINGS = "From the headings"


def _summary() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    return label


def _set_combo(combo: QComboBox, value) -> None:
    """`select_data` without telling the jobs: the combo shows the wizard's choice, it does not make one."""
    with QSignalBlocker(combo):
        select_data(combo, value)


class TableStep(QWidget):
    """Step 2. `show_wizard` and `show_preview` draw; every widget hands its choice to `jobs` at once."""

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

        self.heading_summary = _summary()
        self.heading_summary.setObjectName("WizardHeading")  # Help figure target
        layout.addWidget(self.heading_summary)
        by = QWidget()
        by_layout = QHBoxLayout(by)
        by_layout.setContentsMargins(24, 0, 0, 0)
        self.by_group = QButtonGroup(by)
        self.by_text, self.by_number = QRadioButton(), QRadioButton()
        for radio, by_number in ((self.by_text, False), (self.by_number, True)):
            radio.toggled.connect(lambda on, number=by_number: on and self.jobs.find_heading_by_number(number))
            self.by_group.addButton(radio)
            by_layout.addWidget(radio)
        by_layout.addStretch(1)
        layout.addWidget(by)

        self.sheets_box = QWidget()
        self.sheets_box.setObjectName("WizardSheets")  # Help figure target
        sheets = QVBoxLayout(self.sheets_box)
        sheets.setContentsMargins(0, 0, 0, 0)
        self.sheets_summary = _summary()
        sheets.addWidget(self.sheets_summary)
        rules = QWidget()
        rules_layout = QHBoxLayout(rules)
        rules_layout.setContentsMargins(24, 0, 0, 0)
        self.sheet_rule = QComboBox()
        for value, label in _SHEET_RULES:
            self.sheet_rule.addItem(label, value)
        self.sheet_rule.currentIndexChanged.connect(self._on_sheet_rule)
        rules_layout.addWidget(self.sheet_rule)
        self.sheet_count = QSpinBox()
        self.sheet_count.setRange(1, 999)
        self.sheet_count.valueChanged.connect(lambda value: self.jobs.choose_table(sheet_count=value))
        rules_layout.addWidget(self.sheet_count)
        self.listed = QHBoxLayout()
        rules_layout.addLayout(self.listed)
        rules_layout.addStretch(1)
        sheets.addWidget(rules)
        layout.addWidget(self.sheets_box)

        layouts = QWidget()
        layouts.setObjectName("WizardColumns")  # Help figure target
        layouts_line = QHBoxLayout(layouts)
        layouts_line.setContentsMargins(0, 0, 0, 0)
        layouts_line.addWidget(QLabel("<b>Columns:</b>"))
        self.layout_group = QButtonGroup(layouts)
        self.layout_buttons = {}
        for value, label, sketch in _LAYOUTS:
            radio = QRadioButton(f"{label}   [ {sketch} ]")
            radio.setProperty("label", f"{label}   [ {sketch} ]")
            radio.toggled.connect(lambda on, chosen=value: on and self.jobs.choose_table(layout=chosen))
            self.layout_group.addButton(radio)
            layouts_line.addWidget(radio)
            self.layout_buttons[value] = radio
        layouts_line.addStretch(1)
        layout.addWidget(layouts)

        self.units_summary = _summary()
        self.units_summary.setObjectName("WizardUnits")  # Help figure target
        layout.addWidget(self.units_summary)
        units = QWidget()
        units_layout = QHBoxLayout(units)
        units_layout.setContentsMargins(24, 0, 0, 0)
        self.x_unit, self.amplitude_unit = QComboBox(), QComboBox()
        for label, combo, field in (("X", self.x_unit, "x_unit"), ("Amplitude", self.amplitude_unit, "amplitude_unit")):
            units_layout.addWidget(QLabel(label))
            combo.currentIndexChanged.connect(
                lambda _index, box=combo, name=field: self.jobs.choose_table(**{name: box.currentData() or ""}))
            units_layout.addWidget(combo)
        units_layout.addStretch(1)
        layout.addWidget(units)

        self.text_box = QWidget()
        text = QVBoxLayout(self.text_box)
        text.setContentsMargins(0, 0, 0, 0)
        self.text_summary = _summary()
        text.addWidget(self.text_summary)
        formats = QWidget()
        formats_layout = QHBoxLayout(formats)
        formats_layout.setContentsMargins(24, 0, 0, 0)
        self.encoding, self.delimiter, self.decimal = QComboBox(), QComboBox(), QComboBox()
        for label, combo, choices, field in (("Encoding", self.encoding, ENCODING_LABELS, "encoding"),
                                             ("Delimiter", self.delimiter, DELIMITER_LABELS, "delimiter"),
                                             ("Decimal", self.decimal, DECIMAL_LABELS, "decimal_separator")):
            formats_layout.addWidget(QLabel(label))
            for value, name in choices:
                combo.addItem(name, value)
            combo.currentIndexChanged.connect(
                lambda _index, box=combo, name=field: self.jobs.choose_table(**{name: box.currentData() or ""}))
            formats_layout.addWidget(combo)
        formats_layout.addStretch(1)
        text.addWidget(formats)
        layout.addWidget(self.text_box)
        layout.addStretch(1)
        self._units_kind = None

    # ---- drawing ------------------------------------------------------------------------

    def show_wizard(self, wizard: TemplateWizard) -> None:
        """The choices as the state has them; no widget reports a change meanwhile."""
        table = wizard.table
        for radio, on in ((self.by_text, not table.find_by_number), (self.by_number, table.find_by_number)):
            radio.blockSignals(True)
            radio.setChecked(on)
            radio.blockSignals(False)
        anchor_problem = wizard.resolve_anchor_problem(table.heading_text)
        self.by_text.setText(f"by the text of its first cell ('{table.heading_text}')" if table.heading_text
                             else "by the text of its first cell")
        self.by_text.setEnabled(not anchor_problem)
        self.by_text.setToolTip(f"Not possible: {anchor_problem}." if anchor_problem else "")
        self.by_number.setText(f"by its number ({table.heading_number})")

        is_text = all(sample.detected_text_format is not None for sample in wizard.samples)
        self.sheets_box.setVisible(not is_text)
        _set_combo(self.sheet_rule, table.sheet_rule)
        self.sheet_count.blockSignals(True)
        self.sheet_count.setValue(table.sheet_count)
        self.sheet_count.blockSignals(False)
        self.sheet_count.setVisible(table.sheet_rule in (SHEETS_FIRST_N, SHEETS_WITHOUT_LAST_N))
        self._show_listed(wizard)

        for value, radio in self.layout_buttons.items():
            radio.blockSignals(True)
            radio.setChecked(value == table.layout)
            radio.setText(radio.property("label") + ("  (guess)" if value == wizard.layout_guess else ""))
            radio.blockSignals(False)

        if self._units_kind != wizard.answers.data_kind:
            self._units_kind = wizard.answers.data_kind
            self._fill(self.x_unit, list(resolve_x_units(wizard.answers.data_kind)))
            self._fill(self.amplitude_unit, resolve_amplitude_unit_options(""))
        for combo, value in ((self.x_unit, table.x_unit), (self.amplitude_unit, table.amplitude_unit)):
            if value and combo.findData(value) < 0:
                combo.addItem(value, value)
            _set_combo(combo, value)

        self.text_box.setVisible(is_text)
        for combo, value in ((self.encoding, table.encoding), (self.delimiter, table.delimiter),
                             (self.decimal, table.decimal_separator)):
            _set_combo(combo, value)
        detected = wizard.detected_text_format
        if detected is not None:
            delimiter = dict(DELIMITER_LABELS).get(detected.delimiter, repr(detected.delimiter)).lower()
            decimal = dict(DECIMAL_LABELS).get(detected.decimal, detected.decimal).lower()
            self.text_summary.setText(f"<b>Text format:</b> detected {detected.encoding}, delimiter {delimiter}, "
                                      f"decimal {decimal}")

    def show_preview(self, wizard: TemplateWizard, preview: Optional[SamplePreview]) -> None:
        """The summaries the preview knows: where the headings are, how many sheets are read, the units found."""
        table = wizard.table
        muted = muted_color().name()
        if preview is None:
            return
        if not preview.channels:
            self.heading_summary.setText(f"<span style='color:{RED}'><b>Headings:</b> no channel is read — click "
                                         f"the row number of the heading row in the preview.</span>")
        else:
            where = (f"the row number {table.heading_number}" if table.find_by_number
                     else f"the row starting with '{table.heading_text}'")
            below = "right below it" if table.data_offset == 1 else f"{table.data_offset} rows below it"
            self.heading_summary.setText(f"<b>Headings:</b> {where}, data {below}  "
                                         f"<span style='color:{muted}'>— click a row number to change</span>")
        read = sum(1 for sheet in preview.sheets if not sheet.skipped)
        rule = dict(_SHEET_RULES)[table.sheet_rule].split(" (")[0].lower()
        self.sheets_summary.setText(f"<b>Sheets:</b> {rule} — {read} of {len(preview.sheets)} read")

        x_problem, amplitude_problem = wizard.resolve_unit_problems(preview)
        x_units = sorted({unit for units in preview.units for unit in units.x_units})
        amplitude_units = sorted({unit for units in preview.units for unit in units.amplitude_units})
        text = (f"<b>Units:</b> detected X in {', '.join(x_units) or '—'}, "
                f"amplitude in {', '.join(amplitude_units) or '—'}")
        problems = " ".join(problem for problem in (x_problem, amplitude_problem) if problem)
        self.units_summary.setText(f"<span style='color:{RED}'>{text}. {problems}</span>" if problems else text)

    # ---- inside -----------------------------------------------------------------------------

    @staticmethod
    def _fill(combo: QComboBox, units) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_FROM_HEADINGS, "")
        for unit in units:
            combo.addItem(unit, unit)
        combo.blockSignals(False)

    def _show_listed(self, wizard: TemplateWizard) -> None:
        while self.listed.count():
            item = self.listed.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if wizard.table.sheet_rule != SHEETS_LISTED:
            return
        names = list(dict.fromkeys(name for sample in wizard.samples for name in sample.sheet_names))
        for name in names:
            check = QCheckBox(name)
            check.setChecked(name in wizard.table.sheets)
            check.toggled.connect(lambda _on, all_names=tuple(names): self._on_listed(all_names))
            self.listed.addWidget(check)

    def _on_listed(self, names) -> None:
        checked = {self.listed.itemAt(index).widget().text() for index in range(self.listed.count())
                   if self.listed.itemAt(index).widget().isChecked()}
        self.jobs.choose_table(sheets=tuple(name for name in names if name in checked))

    def _on_sheet_rule(self, _index: int) -> None:
        rule = self.sheet_rule.currentData()
        wizard = self.jobs.wizard
        if rule == SHEETS_LISTED and wizard is not None and not wizard.table.sheets:
            preview = self.jobs.preview
            read = tuple(dict.fromkeys(sheet.sheet for sheet in preview.sheets if not sheet.skipped)) if preview else ()
            self.jobs.choose_table(sheet_rule=rule, sheets=read)
        else:
            self.jobs.choose_table(sheet_rule=rule)
