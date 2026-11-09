"""
The wizard's step 4, "Check and save": the template name and file pattern
suggested from the samples (or the edited template's own), and one
table of every channel of every sample -- a misfit red with its reason, and
the skipped sheets and the files that do not fit among them. A click on a row
shows that channel in the preview. Under "Advanced" is the optional check for
duplicate curves (the first sample, on a worker); its choice is written into
the template as the sheets and channels it reads.
"""

import os
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.import_template import DATA_KIND_ORDER_CUT
from orchestration.import_template import TemplateWizardJobs
from view_models.import_template import (
    ENDING_LIBRARY, ENDING_MISFIT, ENDING_PROJECT, SamplePreview, TemplateWizard, resolve_kept_copies,
)

from ._choices import AMPLITUDE_LABELS, fill_combo, fill_result_table
from ._sample_grid import RED

_ENDING_NOTES = {
    ENDING_LIBRARY: "Saving puts the template into your library and adds the files with it.",
    ENDING_MISFIT: ("Overwrite replaces the template under its name (and re-reads its files); Save as new puts it "
                    "into your library under a new name. The files that fit are then added."),
    ENDING_PROJECT: ("Apply replaces the project's copy of the template: you see what it changes before the files "
                     "it reads are read again."),
}



class CheckStep(QWidget):
    """Step 4. `channel_selected(path, sheet, x column, amplitude column)` when a channel's row is clicked."""

    channel_selected = Signal(str, str, int, int)

    def __init__(self, jobs: TemplateWizardJobs, ending: str = ENDING_LIBRARY, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.duplicate_groups: tuple = ()
        self._rows = []
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.template_name, self.file_pattern = QLineEdit(), QLineEdit()
        self.template_name.setObjectName("WizardTemplateName")  # Help figure targets
        self.file_pattern.setObjectName("WizardFilePattern")
        self.file_pattern.setToolTip("The names of the files the template reads, e.g. TEST*NmA_H1.txt")
        for edit in (self.template_name, self.file_pattern):
            edit.textEdited.connect(self._on_name)
        if ending == ENDING_PROJECT:
            self.template_name.setReadOnly(True)      # the project's copy keeps its name
        form.addRow("Template name", self.template_name)
        form.addRow("File name pattern", self.file_pattern)
        layout.addLayout(form)
        layout.addWidget(QLabel(_ENDING_NOTES[ending]))
        self.summary = QLabel()
        self.summary.setObjectName("WizardSummary")  # Help figure target
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.results = QTableWidget()
        self.results.setObjectName("WizardCheckResults")  # Help figure target
        self.results.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.cellClicked.connect(self._on_row)
        layout.addWidget(self.results, 1)
        layout.addWidget(self._build_advanced())

    def _build_advanced(self) -> QGroupBox:
        """The collapsed "Advanced" box: the optional check for duplicate curves."""
        box = QGroupBox("Advanced")
        box.setObjectName("WizardAdvanced")  # Help figure target
        box.setCheckable(True)
        box.setChecked(False)
        inside = QWidget()
        layout = QVBoxLayout(inside)
        layout.setContentsMargins(0, 0, 0, 0)
        text = QLabel("Duplicate curves (optional): same channel, same order and equal values after conversion to "
                      "RMS count as duplicates, whatever their other metadata. Checked on the first sample only; "
                      "your choice is saved in the template as the sheets and columns it reads.")
        text.setWordWrap(True)
        layout.addWidget(text)
        buttons = QHBoxLayout()
        self.check_duplicates_button = QPushButton("Check for duplicates")
        self.check_duplicates_button.clicked.connect(self.jobs.run_duplicate_check)
        self.keep_one = QComboBox()
        self.keep_one.addItem("Keep all", "")
        fill_combo(self.keep_one, [(value, f"Keep one: {label}") for value, label in AMPLITUDE_LABELS])
        self.keep_one.currentIndexChanged.connect(self._on_keep_one)
        self.apply_keep_button = QPushButton("Apply to the template")
        self.apply_keep_button.clicked.connect(self.apply_duplicate_choice)
        for widget in (self.check_duplicates_button, self.keep_one, self.apply_keep_button):
            buttons.addWidget(widget)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        self.duplicate_table = QTableWidget(0, 3)
        self.duplicate_table.setHorizontalHeaderLabels(["Channel", "Order", "Keep"])
        self.duplicate_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.duplicate_table.setMaximumHeight(140)
        layout.addWidget(self.duplicate_table)
        self.duplicate_status = QLabel()
        layout.addWidget(self.duplicate_status)
        self.keep_one.setEnabled(False)
        self.apply_keep_button.setEnabled(False)
        outer = QVBoxLayout(box)
        outer.addWidget(inside)
        inside.setVisible(False)
        box.toggled.connect(inside.setVisible)
        self.advanced = box
        return box

    def show_wizard(self, wizard: TemplateWizard) -> None:
        template = wizard.template
        for edit, text in ((self.template_name, template.name), (self.file_pattern, template.file_pattern)):
            if edit.text() != text:
                edit.setText(text)

    def show_preview(self, wizard: TemplateWizard, preview: Optional[SamplePreview]) -> None:
        if preview is None:
            return
        ordered = wizard.answers.data_kind == DATA_KIND_ORDER_CUT
        labels = ["File", "Sheet", "Channel"] + (["Order"] if ordered else []) + ["X unit", "Unit", "Points",
                                                                                  "Problem"]
        rows = []
        for channel in preview.channels:
            order = [f"{channel.order:g}" if channel.order is not None else ""] if ordered else []
            rows.append(((channel.path, channel.sheet, channel.x_column, channel.y_column),
                         [os.path.basename(channel.path), channel.sheet, channel.name] + order
                         + [channel.x_unit, channel.unit, str(channel.points), channel.problem],
                         bool(channel.problem)))
        blank = [""] * (len(labels) - 4)
        for skipped in preview.skipped_sheets:
            rows.append(((skipped.path, skipped.sheet, -1, -1),
                         [os.path.basename(skipped.path), skipped.sheet, "— skipped sheet —"] + blank
                         + [skipped.reason], True))
        for path, reason in preview.misfits:
            rows.append(((path, "", -1, -1), [os.path.basename(path), "", "— the file does not fit —"] + blank
                         + [reason], True))
        self._rows = [key for key, _, _ in rows]
        fill_result_table(self.results, labels, [(values, red) for _key, values, red in rows], RED)
        bad = sum(1 for channel in preview.channels if channel.problem)
        read = sum(1 for sheet in preview.sheets if not sheet.skipped)
        self.summary.setText(
            f"<b>{len(preview.channels)} channel(s)</b> from {read} sheet(s) of {len(wizard.samples)} sample(s)"
            + (f"  ·  <span style='color:{RED}'>{bad} do not fit</span>" if bad else "")
            + (f"  ·  <span style='color:{RED}'>{len(preview.skipped_sheets)} sheet(s) skipped</span>"
               if preview.skipped_sheets else "")
            + (f"  ·  <span style='color:{RED}'>{len(preview.misfits)} file(s) do not fit</span>"
               if preview.misfits else ""))

    # ---- duplicates -------------------------------------------------------------

    def show_duplicates(self, groups: tuple, note: str) -> None:
        """The groups found for the template as it stands; the table is rebuilt only when they are others."""
        self.duplicate_status.setText(note)
        if groups is self.duplicate_groups:
            return
        self.duplicate_groups = groups
        self.duplicate_table.setRowCount(len(groups))
        for row, group in enumerate(groups):
            self.duplicate_table.setItem(row, 0, QTableWidgetItem(group.name))
            self.duplicate_table.setItem(row, 1, QTableWidgetItem("" if group.order is None else f"{group.order:g}"))
            combo = QComboBox()
            combo.addItem("All copies", None)
            for number, copy in enumerate(group.copies):
                amplitude = dict(AMPLITUDE_LABELS).get(copy.source_amplitude, copy.source_amplitude)
                combo.addItem(f"{copy.sheet} ({amplitude})", number)
            self.duplicate_table.setCellWidget(row, 2, combo)
        self.keep_one.setEnabled(bool(groups))
        self.apply_keep_button.setEnabled(bool(groups))
        self._on_keep_one()

    def _on_keep_one(self, *_args) -> None:
        amplitude = self.keep_one.currentData()
        if not amplitude:
            return
        for row, number in enumerate(resolve_kept_copies(self.duplicate_groups, None, amplitude)):
            self.duplicate_table.cellWidget(row, 2).setCurrentIndex(0 if number is None else number + 1)

    def apply_duplicate_choice(self) -> None:
        """Writes the keep-one choice of every group into the template; groups left on "All copies" keep all."""
        if not self.duplicate_groups:
            return
        picks = {row: self.duplicate_table.cellWidget(row, 2).currentData()
                 for row in range(len(self.duplicate_groups))}
        self.jobs.keep_duplicates({row: number for row, number in picks.items() if number is not None})

    def _on_name(self, _text: str) -> None:
        self.jobs.name_template(self.template_name.text(), self.file_pattern.text())

    def _on_row(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._rows):
            self.channel_selected.emit(*self._rows[row])
