"""
The import wizard: builds an Import template on one sample workbook.

A thin layer over view_models.import_template.ImportTemplateWizard. Every
widget change is handed to the wizard state as a choice; reading the sample,
the preview (the sample as a grid with header, data and ignored cells
coloured, and the resulting channels and the metadata table) and the checks
run on workers through orchestration.import_template.WizardJobs, which also
says which result still holds. The metadata step's pieces are redrawn from the
wizard state at once: it reads only the head of one sheet. Saving writes one
small template file into the user's library on the GUI thread (§1.137).

All internal documentation strings and variable labels are standardly written
in English.
"""

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
)

from core.import_template import ImportTemplate
from gui.dialogs.import_template_dialog import write_library_copy
from orchestration.import_template import (
    CHANGE_DUPLICATES, CHANGE_FITS, CHANGE_MESSAGE, CHANGE_OPENED, CHANGE_PREVIEW, CHANGE_REWRITTEN,
    CHANGE_TEMPLATE, CHANGE_WORKBOOK, WizardJobs,
)
from orchestration.jobs import JobRunner
from view_models.import_template import (
    ACTION_OVERWRITE, ACTION_SAVE, ACTION_SAVE_AS_NEW, ENDING_LIBRARY, ENDING_PROJECT, SAVED_OVERWRITE,
    ImportTemplateWizard, WizardEnding, WizardPreview,
)

from ._meaning import MeaningStep
from ._metadata import MetadataStep
from ._preview import PreviewPane
from ._save import SaveStep
from ._structure import StructureStep

_PREVIEW_DELAY_MS = 250

_STEP_TITLES = ("1. File structure", "2. Column meaning", "3. Metadata", "4. Summary")


class ImportTemplateWizardDialog(QDialog):
    """
    The wizard on one sample workbook. After `exec()` accepts, `saved_template`
    is the template it ended with and `saved_as` how: `SAVED_NEW` was written
    into the library (`library_folder`, the user's library when None),
    `SAVED_OVERWRITE` replaces the template loaded and was written nowhere.

    With `template` it edits that template instead of guessing a new one. In
    the library (`ENDING_LIBRARY`) a built-in template is read-only, so it
    opens under a free name and ends in "Save as" only; a library template is
    saved over unless it is renamed. A project's copy opened from the misfit
    report (`ENDING_MISFIT`) ends in Overwrite or Save as new (a name none of
    `taken_names` has); one opened in the project (`ENDING_PROJECT`) keeps its
    name and ends in Apply.
    """

    def __init__(self, parent, sample_path: str, job_runner: JobRunner, *, library_folder=None,
                 builtin_names=None, template: Optional[ImportTemplate] = None,
                 ending: str = ENDING_LIBRARY, taken_names=()):
        super().__init__(parent)
        self.setWindowTitle("New Import template" if template is None else f"Edit Import template '{template.name}'")
        self.ending = ending
        self.ending_rules = WizardEnding(ending, builtin_names, taken_names)
        self.edits_builtin = self.ending_rules.edits_builtin(template)
        self.initial_template = template = self.ending_rules.resolve_opening_template(template)
        # A QDialog has no maximize button by default, so Windows will not snap it to the top edge.
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint)
        self.resize(1100, 760)
        self.sample_path = sample_path
        self.library_folder = library_folder
        self.jobs = WizardJobs(job_runner, self.ending_rules, self._on_jobs)
        self.saved_template: Optional[ImportTemplate] = None
        self.saved_as = ""
        self._populating = False
        self._sized = False
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.submit_preview)
        self._build()
        self._set_step(0)
        self.body.setEnabled(False)
        self.status.setText(f"Reading the sample {sample_path}…")
        self.jobs.open(sample_path, template)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sized:
            self._sized = True
            half = self.body.height() // 2
            self.body.setSizes([half, half])              # the preview takes half of the body's height

    @property
    def wizard(self) -> Optional[ImportTemplateWizard]:
        return self.jobs.wizard

    @property
    def last_preview(self) -> Optional[WizardPreview]:
        return self.jobs.preview

    # ---- layout ------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        self.step_title = QLabel()
        layout.addWidget(self.step_title)
        self.body = QSplitter(Qt.Orientation.Vertical)
        self.pages = QStackedWidget()
        self.structure_step = StructureStep(self.jobs)
        self.structure_step.shown_sheet_changed.connect(self._on_shown_sheet)
        self.meaning_step = MeaningStep(self.jobs)
        self.metadata_step = MetadataStep(self.jobs)
        self.save_step = SaveStep(self.jobs, self.ending)
        # Each step: show_template(template), show_preview(preview), collect() -> ImportTemplate fields.
        self.steps = (self.structure_step, self.meaning_step, self.metadata_step, self.save_step)
        for step in self.steps:
            self.pages.addWidget(step)
        for step in (self.structure_step, self.meaning_step, self.save_step):     # metadata edits go to jobs
            step.changed.connect(self._on_choice)
        self.body.addWidget(self.pages)
        self.preview_pane = PreviewPane()
        self.body.addWidget(self.preview_pane)
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)   # the preview is not squeezed by the tallest step
        self.body.setStretchFactor(0, 1)
        self.body.setStretchFactor(1, 1)
        layout.addWidget(self.body, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.back_button = QPushButton("< Back")
        self.next_button = QPushButton("Next >")
        self.save_button = QPushButton("Save as" if self.edits_builtin else "Save")
        self.overwrite_button = QPushButton("Apply to project" if self.ending == ENDING_PROJECT else "Overwrite")
        self.save_new_button = QPushButton("Save as new")
        self._action_buttons = {ACTION_SAVE: self.save_button, ACTION_OVERWRITE: self.overwrite_button,
                                ACTION_SAVE_AS_NEW: self.save_new_button}
        cancel = QPushButton("Cancel")
        for button in (self.back_button, self.next_button, self.save_button, self.overwrite_button,
                       self.save_new_button, cancel):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.back_button.clicked.connect(lambda: self._set_step(self.pages.currentIndex() - 1))
        self.next_button.clicked.connect(self.next_step)
        self.save_button.clicked.connect(self.save)
        self.overwrite_button.clicked.connect(self.overwrite)
        self.save_new_button.clicked.connect(self.save_as_new)
        cancel.clicked.connect(self.reject)

    # ---- wizard state <-> widgets ---------------------------------------------

    def _on_jobs(self, kind: str) -> None:
        """What WizardJobs says changed, drawn."""
        if kind == CHANGE_OPENED:
            self._populate(self.wizard.template)
            self.body.setEnabled(True)
            self.status.setText("")
        elif kind == CHANGE_REWRITTEN:
            self._populate(self.wizard.template)
        elif kind == CHANGE_WORKBOOK:
            self.structure_step.show_workbook()
        elif kind == CHANGE_PREVIEW:
            self._show_preview()
        elif kind == CHANGE_FITS:
            self.save_step.show_sample_fits(self.jobs.sample_fits)
        elif kind == CHANGE_MESSAGE:
            self.status.setText(self.jobs.message)
        elif kind == CHANGE_TEMPLATE:
            self.preview_timer.start(_PREVIEW_DELAY_MS)
        if kind in (CHANGE_TEMPLATE, CHANGE_REWRITTEN, CHANGE_DUPLICATES):
            self._show_duplicates()
        self._show_ending()

    def _populate(self, template: ImportTemplate) -> None:
        self._populating = True
        try:
            for step in self.steps:
                step.show_template(template)
        finally:
            self._populating = False

    def _collect(self) -> dict:
        """Every choice the widgets show, as ImportTemplate fields."""
        fields = {}
        for step in self.steps:
            fields.update(step.collect())
        return fields

    def _on_choice(self, *_args) -> None:
        if not self._populating:
            self.jobs.change(**self._collect())

    def _on_shown_sheet(self, sheet: str) -> None:
        if self._populating or self.wizard is None:
            return
        self.jobs.show_sheet(sheet)
        self._show_ending()
        self.preview_timer.start(_PREVIEW_DELAY_MS)

    def _show_duplicates(self) -> None:
        self.save_step.show_duplicates(self.jobs.duplicate_groups, self.jobs.duplicate_note)

    # ---- preview ---------------------------------------------------------------

    def submit_preview(self) -> None:
        """Previews the current choices on a worker; the newest request wins."""
        self.preview_timer.stop()
        self.jobs.run_preview()

    def _show_preview(self) -> None:
        preview = self.jobs.preview
        self.preview_pane.show_preview(preview)
        for step in self.steps:
            step.show_preview(preview)
        if not self.jobs.is_preview_current():
            return
        problems = self.jobs.resolve_action_problems()
        # Said only when no ending can be used; each button's own reason is its tooltip.
        problem = "" if any(not text for text in problems.values()) else next(iter(problems.values()), "")
        self.status.setText(problem or f"{len(preview.channels)} channel(s) read from the sample.")

    def _show_ending(self) -> None:
        """Each ending button usable or not, with its reason as the tooltip; one this ending does not offer stays off."""
        problems = self.jobs.resolve_action_problems()
        for action, button in self._action_buttons.items():
            button.setEnabled(problems.get(action) == "")
            button.setToolTip(problems.get(action, ""))

    # ---- steps and saving ------------------------------------------------------

    def _set_step(self, step: int) -> None:
        step = max(0, min(step, self.pages.count() - 1))
        self.pages.setCurrentIndex(step)
        self.step_title.setText(f"<b>{_STEP_TITLES[step]}</b> — sample: {self.sample_path}")
        self.back_button.setEnabled(step > 0)
        self.next_button.setVisible(step < self.pages.count() - 1)
        last = step == self.pages.count() - 1
        for action, button in self._action_buttons.items():
            button.setVisible(last and action in self.ending_rules.resolve_actions())

    def next_step(self) -> None:
        self._set_step(self.pages.currentIndex() + 1)

    def save(self) -> None:
        """Writes the template into the library (asking before replacing one) and accepts."""
        self._end(ACTION_SAVE)

    def save_as_new(self) -> None:
        """Writes the edited template into the library under its new name and accepts."""
        self._end(ACTION_SAVE_AS_NEW)

    def overwrite(self) -> None:
        """Accepts the edited template in place of the one loaded; writes nothing."""
        self._end(ACTION_OVERWRITE)

    def _end(self, action: str) -> None:
        problem = self.jobs.resolve_action_problems().get(action, f"This wizard does not offer '{action}'.")
        if problem:
            QMessageBox.warning(self, "Import template", problem)
            return
        template = self.wizard.template
        saved_as = self.ending_rules.resolve_saved_as(action)
        if saved_as != SAVED_OVERWRITE and not write_library_copy(self, template, self.library_folder):
            return
        self.saved_template, self.saved_as = template, saved_as
        self.accept()

    def done(self, result) -> None:
        self.preview_timer.stop()
        self.jobs.cancel()
        super().done(result)
