"""
The first step: which sheets are read, where the heading row is, where the data starts, how the
columns are laid out and, for a text file, its encoding, delimiter and decimal separator.
"""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QWidget,
)

from core.import_template import (
    LAYOUT_SHARED_X, LAYOUT_SINGLE_CURVE, LAYOUT_XY_PAIRS, SHEETS_ALL, SHEETS_FIRST_N, SHEETS_LISTED,
    SHEETS_WITHOUT_LAST_N, ImportTemplate,
)
from orchestration.import_template import WizardJobs

from ._choices import fill_combo, select_data

_LAYOUT_LABELS = (
    (LAYOUT_XY_PAIRS, "X/Y pairs, each channel with its own X"),
    (LAYOUT_SHARED_X, "One shared X column, then one column per channel"),
    (LAYOUT_SINGLE_CURVE, "One curve per sheet (first two columns)"),
)
_SHEET_RULE_LABELS = (
    (SHEETS_ALL, "All"), (SHEETS_FIRST_N, "First N"), (SHEETS_WITHOUT_LAST_N, "Without last N"),
    (SHEETS_LISTED, "Select sheets"),
)
_DETECTED = "Detected"
_ENCODING_LABELS = (
    ("", _DETECTED), ("utf-8", "UTF-8"), ("cp1252", "Windows-1252"), ("cp1250", "Windows-1250"),
    ("latin-1", "Latin-1"), ("utf-16", "UTF-16"),
)
_DELIMITER_LABELS = (
    ("", _DETECTED), ("\t", "Tab"), (";", "Semicolon"), (",", "Comma"), ("|", "Pipe"), (" ", "Space"),
)
_DECIMAL_LABELS = (("", _DETECTED), (".", "Point"), (",", "Comma"))


class _SheetCombo(QComboBox):
    """A drop-down of sheets with a check box each; a click ticks an entry and keeps the list open."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setModel(QStandardItemModel(self))
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.view().viewport().installEventFilter(self)
        self.model().itemChanged.connect(self._on_item_changed)

    def clear_sheets(self) -> None:
        self.model().clear()
        self._show_summary()

    def add_sheet(self, name: str, checked: bool) -> None:
        item = QStandardItem(name)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.model().appendRow(item)
        self._show_summary()

    def item(self, row: int) -> QStandardItem:
        return self.model().item(row)

    def checked_names(self) -> tuple:
        return tuple(self.item(row).text() for row in range(self.count())
                     if self.item(row).checkState() == Qt.CheckState.Checked)

    def eventFilter(self, obj, event):
        if obj is self.view().viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            item = self.model().itemFromIndex(self.view().indexAt(event.position().toPoint()))
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                                   else Qt.CheckState.Checked)
            return True
        return super().eventFilter(obj, event)

    def _on_item_changed(self, _item) -> None:
        self._show_summary()
        self.changed.emit()

    def _show_summary(self) -> None:
        self.lineEdit().setText(", ".join(self.checked_names()))


class StructureStep(QWidget):
    """The file structure. `changed` is a choice made here, `shown_sheet_changed` the sheet to preview instead."""

    changed = Signal()
    shown_sheet_changed = Signal(str)

    def __init__(self, jobs: WizardJobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.form = form = QFormLayout(self)
        self.sheet_rule_combo = QComboBox()
        fill_combo(self.sheet_rule_combo, _SHEET_RULE_LABELS)
        self.sheet_rule_combo.setToolTip("Sheet names often differ from export to export")
        self.sheet_rule_combo.currentIndexChanged.connect(self.changed)
        self.sheet_count = QSpinBox()
        self.sheet_count.setRange(1, 1000)
        self.sheet_count.valueChanged.connect(self.changed)
        self.sheet_list = _SheetCombo()
        self.sheet_list.changed.connect(self.changed)
        self.sheets_box = QWidget()
        sheets_layout = QHBoxLayout(self.sheets_box)
        sheets_layout.setContentsMargins(0, 0, 0, 0)
        sheets_layout.addWidget(self.sheet_rule_combo)
        sheets_layout.addWidget(self.sheet_count)
        sheets_layout.addWidget(self.sheet_list, 1)
        form.addRow("Sheets to read", self.sheets_box)
        self.shown_sheet = QComboBox()
        self.shown_sheet.currentIndexChanged.connect(
            lambda *_: self.shown_sheet_changed.emit(self.shown_sheet.currentText()))
        form.addRow("Show sheet", self.shown_sheet)
        heading = QWidget()
        heading_layout = QHBoxLayout(heading)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        self.by_anchor = QRadioButton("Row whose first cell is")
        self.anchor_text = QLineEdit()
        self.by_row = QRadioButton("Row number")
        self.heading_row = QSpinBox()
        self.heading_row.setRange(1, 1_000_000)
        group = QButtonGroup(self)
        for widget in (self.by_anchor, self.by_row):
            group.addButton(widget)
        for widget in (self.by_row, self.heading_row, self.by_anchor, self.anchor_text):
            heading_layout.addWidget(widget)
        group.buttonToggled.connect(lambda *_: self.changed.emit())
        self.anchor_text.textChanged.connect(self.changed)
        self.heading_row.valueChanged.connect(self.changed)
        form.addRow("Heading row (header above, data below)", heading)
        self.data_offset = QSpinBox()
        self.data_offset.setRange(1, 1000)
        self.data_offset.valueChanged.connect(self.changed)
        data_start = QWidget()
        data_start_layout = QHBoxLayout(data_start)
        data_start_layout.setContentsMargins(0, 0, 0, 0)
        data_start_layout.addWidget(self.data_offset)
        data_start_layout.addWidget(QLabel("row(s) below the heading row"), 1)
        form.addRow("Data starts", data_start)
        self.layout_combo = QComboBox()
        fill_combo(self.layout_combo, _LAYOUT_LABELS)
        self.layout_combo.currentIndexChanged.connect(self.changed)
        form.addRow("Column pattern", self.layout_combo)
        self.text_format_box = QWidget()
        text_layout = QHBoxLayout(self.text_format_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        self.encoding_combo, self.delimiter_combo, self.decimal_combo = QComboBox(), QComboBox(), QComboBox()
        for label, combo, choices in (("Encoding", self.encoding_combo, _ENCODING_LABELS),
                                      ("Delimiter", self.delimiter_combo, _DELIMITER_LABELS),
                                      ("Decimal", self.decimal_combo, _DECIMAL_LABELS)):
            fill_combo(combo, choices)
            combo.currentIndexChanged.connect(self.changed)
            text_layout.addWidget(QLabel(label))
            text_layout.addWidget(combo)
        self.text_format_note = QLabel()
        text_layout.addWidget(self.text_format_note, 1)
        form.addRow("Text file", self.text_format_box)
        self.changed.connect(self._show_enabled)

    def show_template(self, template: ImportTemplate) -> None:
        """The template's structure choices; the caller keeps `changed` from reaching the wizard meanwhile."""
        self.sheet_list.clear_sheets()
        wizard = self.jobs.wizard
        for sheet in wizard.sample.sheet_names:
            self.sheet_list.add_sheet(sheet, sheet in template.sheets)
        rule = template.sheet_rule
        if rule == SHEETS_LISTED and not template.sheets:
            rule = SHEETS_FIRST_N                              # a template naming no sheet reads the first one
        select_data(self.sheet_rule_combo, rule)
        self.sheet_count.setValue(template.sheet_count)
        by_anchor = bool(template.anchor_text.strip())
        self.by_anchor.setChecked(by_anchor)
        self.by_row.setChecked(not by_anchor)
        self.anchor_text.setText(template.anchor_text)
        self.heading_row.setValue(max(1, template.heading_row))
        self.data_offset.setValue(template.data_offset)
        select_data(self.layout_combo, template.layout)
        select_data(self.encoding_combo, template.encoding)
        select_data(self.delimiter_combo, template.delimiter)
        select_data(self.decimal_combo, template.decimal_separator)
        self.form.setRowVisible(self.text_format_box, wizard.sample.text_format is not None)   # label too
        self.show_workbook()
        self._show_enabled()

    def show_preview(self, preview) -> None:
        """Nothing here depends on the preview."""

    def show_workbook(self) -> None:
        """The sheets of the workbook the preview shows, its shown sheet selected, and the text format detected."""
        wizard = self.jobs.wizard
        self.shown_sheet.blockSignals(True)
        self.shown_sheet.clear()
        self.shown_sheet.addItems(list(wizard.workbook.sheet_names))
        self.shown_sheet.setCurrentText(wizard.shown_sheet)
        self.shown_sheet.blockSignals(False)
        self._show_detected_text_format()

    def _show_enabled(self) -> None:
        is_text = self.jobs.wizard is not None and self.jobs.wizard.sample.text_format is not None
        rule = self.sheet_rule_combo.currentData()
        self.sheet_rule_combo.setEnabled(not is_text)        # a text file has no sheets to choose
        self.sheet_count.setVisible(rule in (SHEETS_FIRST_N, SHEETS_WITHOUT_LAST_N))
        self.sheet_count.setEnabled(not is_text)
        self.sheet_list.setVisible(rule == SHEETS_LISTED)
        self.sheet_list.setEnabled(not is_text)
        self.shown_sheet.setEnabled(not is_text)
        self.anchor_text.setEnabled(self.by_anchor.isChecked())
        self.heading_row.setEnabled(self.by_row.isChecked())

    def collect(self) -> dict:
        """The structure choices as ImportTemplate fields."""
        rule = self.sheet_rule_combo.currentData()
        sheets = self.sheet_list.checked_names() if rule == SHEETS_LISTED else ()
        by_anchor = self.by_anchor.isChecked()
        return dict(
            sheets=sheets, sheet_rule=rule, sheet_count=self.sheet_count.value(),
            anchor_text=self.anchor_text.text() if by_anchor else "",
            heading_row=0 if by_anchor else self.heading_row.value(),
            data_offset=self.data_offset.value(),
            layout=self.layout_combo.currentData(),
            encoding=self.encoding_combo.currentData() or "",
            delimiter=self.delimiter_combo.currentData() or "",
            decimal_separator=self.decimal_combo.currentData() or "",
        )

    def _show_detected_text_format(self) -> None:
        detected = self.jobs.wizard.detected_text_format
        if detected is None:
            self.text_format_note.setText("")
            return
        delimiter = dict(_DELIMITER_LABELS).get(detected.delimiter, repr(detected.delimiter))
        decimal = dict(_DECIMAL_LABELS).get(detected.decimal, detected.decimal)
        self.text_format_note.setText(
            f"Detected: {detected.encoding}, delimiter {delimiter.lower()}, decimal {decimal.lower()}")
