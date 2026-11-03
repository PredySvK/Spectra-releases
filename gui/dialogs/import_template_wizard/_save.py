"""
The last step: the template's name and file pattern, the further sample files it is checked
against, and the optional check for duplicate curves. Both checks are WizardJobs'.
"""

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.import_template import ImportTemplate
from gui.appearance import APP_TOKENS
from orchestration.import_template import WizardJobs
from view_models.import_template import ENDING_MISFIT, ENDING_PROJECT, resolve_kept_copies

from ._choices import AMPLITUDE_LABELS, fill_combo


class SaveStep(QWidget):
    """
    Name, file pattern, further samples and duplicates. `changed` is a choice made here;
    the checks are asked of `jobs`, and the dialog hands their results back
    (`show_sample_fits`, `show_duplicates`).
    """

    changed = Signal()

    def __init__(self, jobs: WizardJobs, ending: str, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.sample_fits: tuple = ()
        self.duplicate_groups: tuple = ()
        form = QFormLayout(self)
        self.template_name = QLineEdit()
        self.template_name.textChanged.connect(self.changed)
        form.addRow("Template name", self.template_name)
        self.file_pattern = QLineEdit()
        self.file_pattern.setToolTip("The names of the files this template reads, e.g. *.xlsx or TEST*.xlsx")
        self.file_pattern.textChanged.connect(self.changed)
        form.addRow("File name pattern", self.file_pattern)
        if ending == ENDING_PROJECT:
            self.template_name.setReadOnly(True)
            note = ("Apply replaces the project's copy of the template: you see what it changes "
                    "before the files it reads are read again.")
        elif ending == ENDING_MISFIT:
            note = ("Overwrite replaces the template under its name (and re-reads its files); "
                    "Save as new puts it into your library under a new name. The files that fit are then added.")
        else:
            note = "Saving puts the template into your library and adds the files with it."
        form.addRow(QLabel(note))
        form.addRow(self._build_other_samples_box())
        form.addRow(self._build_duplicates_box())

    def _build_other_samples_box(self) -> QGroupBox:
        box = QGroupBox("Further sample files")
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel("Check that the template fits more files; a file that does not is listed "
                                "with the reason. Select one to see it in the preview."))
        self.sample_list = QListWidget()
        self.sample_list.setMaximumHeight(90)
        self.sample_list.currentRowChanged.connect(self._on_other_sample_selected)
        layout.addWidget(self.sample_list)
        buttons = QHBoxLayout()
        self.add_samples_button = QPushButton("Add sample files…")
        self.add_samples_button.clicked.connect(self.choose_other_samples)
        self.first_sample_button = QPushButton("Show the first sample")
        self.first_sample_button.clicked.connect(self.show_first_sample)
        buttons.addWidget(self.add_samples_button)
        buttons.addWidget(self.first_sample_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    def _build_duplicates_box(self) -> QGroupBox:
        box = QGroupBox("Duplicate curves (optional)")
        layout = QVBoxLayout(box)
        layout.addWidget(QLabel("Same channel, same order and equal values after conversion to RMS count as "
                                "duplicates, whatever their other metadata. Checked on the first sample only; "
                                "your choice is saved in the template as the sheets and columns it reads."))
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
        return box

    # ---- the template <-> the widgets ------------------------------------------

    def show_template(self, template: ImportTemplate) -> None:
        self.template_name.setText(template.name)
        self.file_pattern.setText(template.file_pattern)

    def show_preview(self, preview) -> None:
        """Nothing here depends on the preview."""

    def collect(self) -> dict:
        return dict(name=self.template_name.text(), file_pattern=self.file_pattern.text())

    # ---- further samples --------------------------------------------------------

    def choose_other_samples(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Further sample files", "", "Table files (*.xlsx *.txt *.csv)")
        self.jobs.add_other_samples(paths)

    def show_sample_fits(self, fits: tuple) -> None:
        self.sample_fits = fits
        self.sample_list.blockSignals(True)
        current = self.sample_list.currentRow()
        self.sample_list.clear()
        for fit in fits:
            item = QListWidgetItem(f"fits — {fit.path}" if fit.fits else f"does not fit — {fit.path}: {fit.problem}")
            if not fit.fits:
                item.setForeground(QColor(APP_TOKENS.text_muted))
            self.sample_list.addItem(item)
        self.sample_list.setCurrentRow(current)
        self.sample_list.blockSignals(False)

    def _on_other_sample_selected(self, row: int) -> None:
        if 0 <= row < len(self.sample_fits):
            self.jobs.show_other_sample(self.sample_fits[row].path)

    def show_first_sample(self) -> None:
        self.sample_list.blockSignals(True)
        self.sample_list.setCurrentRow(-1)
        self.sample_list.blockSignals(False)
        self.jobs.show_first_sample()

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
            self.duplicate_table.setItem(
                row, 1, QTableWidgetItem("" if group.order is None else f"{group.order:g}"))
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
