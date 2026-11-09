"""
The import wizard (#1028): builds an Import template on
several samples, in four linear steps, with the preview of every sample at the
bottom from step 2 on. It opens maximized.

A thin layer over view_models.import_template.TemplateWizard: every widget hands
its choice to orchestration.import_template.TemplateWizardJobs, which reads the
samples and computes the preview on workers and says which preview still
holds. Saving writes one small template file into the user's library on the
GUI thread (§1.137).

It also edits a template (#1034): every step shows its choices and
the last step ends in Save (a built-in template only
Save as), Overwrite and Save as new from the misfit report, Apply in the project.
"""

from typing import Iterable, Optional, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QSplitter, QStackedWidget, QVBoxLayout,
)

from core.import_template import ImportTemplate
from gui.dialogs.import_template_dialog import write_library_copy
from orchestration.import_template import (
    SAMPLES_CHANGED, SAMPLES_CHOICE, SAMPLES_DUPLICATES, SAMPLES_MESSAGE, SAMPLES_OPENED, SAMPLES_PREVIEW,
    SAMPLES_ROLES, TemplateWizardJobs,
)
from orchestration.jobs import JobRunner
from view_models.import_template import (
    ACTION_OVERWRITE, ACTION_SAVE, ACTION_SAVE_AS_NEW, ENDING_LIBRARY, ENDING_PROJECT, SAVED_OVERWRITE, STEP_CHECK,
    STEP_ROLES, STEP_SAMPLES, STEP_TABLE, WizardEnding,
)

from ._check_step import CheckStep
from ._roles_step import RolesStep
from ._sample_grid import MODE_CHANNELS, MODE_ROLES, MODE_TABLE, RED, SampleGridPane, muted_color
from ._samples_step import SamplesStep
from ._table_step import TableStep

_PREVIEW_DELAY_MS = 250
_STEP_TITLES = ("1. Samples and what it is", "2. Table", "3. Texts → roles", "4. Check and save")


class TemplateWizardDialog(QDialog):
    """
    The wizard on the samples `sample_paths` (every one with the first
    one's suffix; another is refused with the reason). After `exec()` accepts,
    `saved_template` is the template it ended with and `saved_as` how:
    `SAVED_NEW` was written into the library (`library_folder`, the user's
    library when None), `SAVED_OVERWRITE` replaces the template loaded and was
    written nowhere. `builtin_names` are the names a template cannot be saved
    under (read from the installation when None).

    With `template` it edits that template:
    in the library (`ENDING_LIBRARY`) a built-in one is read-only, so it opens
    under a free name and ends in "Save as" only; a project's copy opened from
    the misfit report (`ENDING_MISFIT`) ends in Overwrite or Save as new (a name
    none of `taken_names` has); one opened in the project (`ENDING_PROJECT`)
    keeps its name and ends in Apply.
    """

    def __init__(self, parent, sample_paths: Sequence[str], job_runner: JobRunner, *, library_folder=None,
                 builtin_names: Optional[Iterable[str]] = None, template: Optional[ImportTemplate] = None,
                 ending: str = ENDING_LIBRARY, taken_names=()):
        super().__init__(parent)
        self.setWindowTitle("New Import template" if template is None else f"Edit Import template '{template.name}'")
        self.ending = ending
        self.ending_rules = WizardEnding(ending, builtin_names, taken_names)
        self.edits_builtin = self.ending_rules.edits_builtin(template)
        template = self.ending_rules.resolve_opening_template(template)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint)
        self.resize(1400, 900)
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)
        self.library_folder = library_folder
        self.builtin_names = tuple(builtin_names) if builtin_names is not None else None
        self.saved_template: Optional[ImportTemplate] = None
        self.saved_as = ""
        self.jobs = TemplateWizardJobs(job_runner, self._on_jobs, self.ending_rules)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.submit_preview)
        self._build()
        self._set_step(STEP_SAMPLES)
        self.pages.setEnabled(False)
        self.status.setText("Reading the samples…")
        self.jobs.open(sample_paths, template)

    @property
    def wizard(self):
        return self.jobs.wizard

    # ---- layout --------------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setObjectName("WizardSteps")  # Help figure target
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.body = QSplitter(Qt.Orientation.Vertical)
        self.pages = QStackedWidget()
        self.grid = SampleGridPane()
        self.grid.heading_clicked.connect(self.jobs.choose_heading_row)
        self.grid.data_start_clicked.connect(self.jobs.choose_data_row)
        self.samples_step = SamplesStep(self.jobs)
        self.table_step = TableStep(self.jobs)
        self.roles_step = RolesStep(self.jobs, self.grid)
        self.check_step = CheckStep(self.jobs, self.ending)
        self.check_step.channel_selected.connect(self._on_channel_selected)
        for page in (self.samples_step, self.table_step, self.roles_step, self.check_step):
            self.pages.addWidget(page)
        self.pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.body.addWidget(self.pages)
        self.body.addWidget(self.grid)
        self.body.addWidget(self.roles_step.results)        # step 3's results, under the preview
        self.body.setStretchFactor(0, 2)
        self.body.setStretchFactor(1, 3)
        self.body.setStretchFactor(2, 2)
        layout.addWidget(self.body, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.reason = QLabel()
        self.reason.setObjectName("WizardReason")  # Help figure target
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet(f"color:{RED};")
        buttons.addWidget(self.reason, 1)
        self.back_button = QPushButton("< Back")
        self.next_button = QPushButton("Next >")
        self.save_button = QPushButton("Save as" if self.edits_builtin else "Save")
        self.next_button.setObjectName("WizardNext")  # Help figure targets
        self.save_button.setObjectName("WizardSave")
        self.overwrite_button = QPushButton("Apply to project" if self.ending == ENDING_PROJECT else "Overwrite")
        self.save_new_button = QPushButton("Save as new")
        self._action_buttons = {ACTION_SAVE: self.save_button, ACTION_OVERWRITE: self.overwrite_button,
                                ACTION_SAVE_AS_NEW: self.save_new_button}
        cancel = QPushButton("Cancel")
        for button in (self.back_button, self.next_button, self.save_button, self.overwrite_button,
                       self.save_new_button, cancel):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.back_button.clicked.connect(lambda: self._set_step(self.step - 1))
        self.next_button.clicked.connect(self.next_step)
        self.save_button.clicked.connect(self.save)
        self.overwrite_button.clicked.connect(self.overwrite)
        self.save_new_button.clicked.connect(self.save_as_new)
        cancel.clicked.connect(self.reject)
        QShortcut(QKeySequence("Alt+Left"), self, activated=lambda: self._set_step(self.step - 1))
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.next_step)

    @property
    def step(self) -> int:
        return self.pages.currentIndex()

    # ---- the state -> the widgets -------------------------------------------------------

    def _on_jobs(self, kind: str) -> None:
        """What TemplateWizardJobs says changed, drawn."""
        if kind == SAMPLES_MESSAGE:
            self.status.setText(self.jobs.message)
        elif self.wizard is not None:
            if kind == SAMPLES_OPENED:
                self.pages.setEnabled(True)
                self.status.setText("")
            if kind in (SAMPLES_OPENED, SAMPLES_CHANGED, SAMPLES_CHOICE, SAMPLES_ROLES, SAMPLES_DUPLICATES):
                for step in (self.samples_step, self.table_step, self.check_step):
                    step.show_wizard(self.wizard)
            if kind == SAMPLES_CHOICE:
                self.preview_timer.start(_PREVIEW_DELAY_MS)
            if kind == SAMPLES_PREVIEW:
                self._show_preview()
            if kind in (SAMPLES_OPENED, SAMPLES_CHOICE, SAMPLES_DUPLICATES):
                self.check_step.show_duplicates(self.jobs.duplicate_groups, self.jobs.duplicate_note)
            if kind != SAMPLES_PREVIEW and self.step == STEP_ROLES:
                self.roles_step.refresh()
        self._show_title()
        self._show_nav()

    def _show_preview(self) -> None:
        preview = self.jobs.preview
        self.grid.show_preview(preview)
        for step in (self.samples_step, self.table_step, self.check_step):
            step.show_preview(self.wizard, preview)
        if self.step == STEP_ROLES:
            self.roles_step.refresh()
        if self.jobs.is_preview_current():
            self.status.setText("")

    def _show_title(self) -> None:
        muted = muted_color().name()
        crumbs = "   ›   ".join(f"<b>{title}</b>" if number == self.step else f"<span style='color:{muted}'>{title}</span>"
                                for number, title in enumerate(_STEP_TITLES))
        # The facts line stays while a new preview is computed (the last one's numbers), so the
        # wizard below it does not jump on every choice.
        preview = self.jobs.preview
        facts = "…"
        if self.wizard is not None and preview is not None:
            read = sum(1 for sheet in preview.sheets if not sheet.skipped)
            facts = (f"samples: {len(self.wizard.samples)}  ·  "
                     f"sheets read: {read} of {len(preview.sheets)}  ·  channels: {len(preview.channels)}")
        self.title.setText(f"{crumbs}<br><span style='color:{muted}'>{facts}</span>")

    def _show_nav(self) -> None:
        step = self.step
        last = step == STEP_CHECK
        self.back_button.setEnabled(step > STEP_SAMPLES)
        self.next_button.setVisible(not last)
        problems = self.jobs.resolve_action_problems()
        for action, button in self._action_buttons.items():
            button.setVisible(last and action in problems)
            button.setEnabled(problems.get(action) == "")
            button.setToolTip(problems.get(action, ""))
        if last:
            # Said only when no ending can be used; each button's own reason is its tooltip.
            usable = any(not text for text in problems.values())
            self.reason.setText("" if usable else next(iter(problems.values()), ""))
            return
        problem = self.jobs.resolve_step_problem(step, self.builtin_names)
        self.reason.setText(problem)
        self.next_button.setEnabled(not problem)

    # ---- steps and saving -------------------------------------------------------------------

    def _set_step(self, step: int) -> None:
        step = max(STEP_SAMPLES, min(step, STEP_CHECK))
        self.pages.setCurrentIndex(step)
        self.roles_step.stop_picking()
        self.grid.setVisible(step >= STEP_TABLE)
        self.roles_step.results.setVisible(step == STEP_ROLES)
        self.grid.set_mode({STEP_TABLE: MODE_TABLE, STEP_ROLES: MODE_ROLES}.get(step, MODE_CHANNELS))
        if step == STEP_ROLES:
            self.roles_step.refresh()
        self._show_title()
        self._show_nav()

    def next_step(self) -> None:
        if self.step < STEP_CHECK and not self.jobs.resolve_step_problem(self.step, self.builtin_names):
            self._set_step(self.step + 1)

    def submit_preview(self) -> None:
        """Previews the current choices on a worker; the newest request wins."""
        self.preview_timer.stop()
        self.jobs.run_preview()

    def _on_channel_selected(self, path: str, sheet: str, x_column: int, y_column: int) -> None:
        columns = tuple(column for column in (x_column, y_column) if column >= 0)
        self.grid.show_sheet((path, sheet), columns)

    def save(self) -> None:
        """Writes the template into the library (asking before replacing one of its name) and accepts."""
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
        template = self.jobs.template
        saved_as = self.ending_rules.resolve_saved_as(action)
        if saved_as != SAVED_OVERWRITE and not write_library_copy(self, template, self.library_folder):
            return
        self.saved_template, self.saved_as = template, saved_as
        self.accept()

    def done(self, result) -> None:
        self.preview_timer.stop()
        self.jobs.cancel()
        super().done(result)
