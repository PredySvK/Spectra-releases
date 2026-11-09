"""
The Import template library: the built-in templates, the user's library and
the open project's own copies in one list, with new and edit (both open the
import wizard), export to a file, import from a file and delete.

Editing a project's copy is the Data Pool's business (its consequence summary
and the re-read of the files it reads), handed in as `edit_project_template`;
the copy cannot be deleted here.

Built-in templates are read-only: edit ends in "Save as" into the library, and
delete is refused. Deleting a library template removes only the library's file;
a project keeps its own copy. Writing and reading one template file is a short,
user-started access to a small file and runs on the GUI thread (§1.137).
"""

from pathlib import Path
from typing import Callable, List, Mapping, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.import_template import ImportTemplate
from gui.dialogs.import_template_wizard import TemplateWizardDialog
from io_modules.import_template import (
    delete_library_template,
    write_library_template_from_file,
    read_builtin_templates,
    read_library_problems,
    read_library_templates,
    read_template_file,
    resolve_library_file,
    write_template_file,
)
from orchestration.jobs import JobRunner

_BUILTIN_MARK = "built-in"
_PROJECT_MARK = "this project"


class ImportTemplateLibraryDialog(QDialog):
    """
    Lists built-in and library templates; `library_folder` is the user's
    library when None. With `edit_project_template` (called with a name) the
    open project's copies (`project_templates`, name -> template) are listed
    too, and editing one goes through it.
    """

    def __init__(self, parent, job_runner: JobRunner, *, library_folder=None,
                 project_templates: Optional[Mapping[str, ImportTemplate]] = None,
                 edit_project_template: Optional[Callable[[str], None]] = None):
        super().__init__(parent)
        self.setWindowTitle("Import templates")
        self.resize(560, 420)
        self.job_runner = job_runner
        self.library_folder = library_folder
        self.edit_project_template = edit_project_template
        self._project_templates = dict(project_templates or {}) if edit_project_template else {}
        self._templates: List[ImportTemplate] = []
        self._origins: List[str] = []
        self._builtin_names: List[str] = []  # lower-case, as the wizard compares names
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Import templates</b><br>Built-in templates are read-only; edit one to save a changed copy "
            "into your library. The library is a folder of files you can copy to colleagues. "
            "A project reads its own copy: editing it there re-reads the files it reads."))
        self.listing = QListWidget()
        layout.addWidget(self.listing, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.new_button = QPushButton("New…")
        self.edit_button = QPushButton("Edit…")
        self.export_button = QPushButton("Export…")
        self.import_button = QPushButton("Import…")
        self.delete_button = QPushButton("Delete")
        close = QPushButton("Close")
        for button in (self.new_button, self.edit_button, self.export_button,
                       self.import_button, self.delete_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.new_button.clicked.connect(self._ask_new)
        self.edit_button.clicked.connect(self._ask_edit)
        self.export_button.clicked.connect(self._ask_export)
        self.import_button.clicked.connect(self._ask_import)
        self.delete_button.clicked.connect(self._ask_delete)
        close.clicked.connect(self.accept)
        self.listing.currentRowChanged.connect(self._update_button_states)

    # ---- the list ------------------------------------------------------------

    def refresh(self, select: str = "") -> None:
        """Re-reads the built-ins and the library; selects the template named `select` when it is there."""
        builtins = read_builtin_templates()
        self._builtin_names = [template.name.lower() for template in builtins]
        library = read_library_templates(self.library_folder)
        project = sorted(self._project_templates.values(), key=lambda template: template.name.lower())
        self._templates = builtins + library + project
        self._origins = ([_BUILTIN_MARK] * len(builtins) + ["library"] * len(library)
                         + [_PROJECT_MARK] * len(project))
        self.listing.clear()
        for template, origin in zip(self._templates, self._origins):
            item = QListWidgetItem(f"{template.name}   ({template.file_pattern}, {origin})")
            item.setData(Qt.ItemDataRole.UserRole, template.name)
            self.listing.addItem(item)
        names = [template.name for template in self._templates]
        self.listing.setCurrentRow(names.index(select) if select in names else (0 if names else -1))
        problems = read_library_problems(self.library_folder)
        self.status.setText("\n".join(f"Not usable, not listed: {file} -- {why}" for file, why in problems))
        self._update_button_states()

    def selected_template(self) -> Optional[ImportTemplate]:
        row = self.listing.currentRow()
        return self._templates[row] if 0 <= row < len(self._templates) else None

    def selected_is_project_copy(self) -> bool:
        row = self.listing.currentRow()
        return 0 <= row < len(self._origins) and self._origins[row] == _PROJECT_MARK

    def is_builtin(self, template: ImportTemplate) -> bool:
        return template.name.strip().lower() in self._builtin_names

    def _update_button_states(self, *_args) -> None:
        template = self.selected_template()
        self.edit_button.setEnabled(template is not None)
        self.export_button.setEnabled(template is not None)
        self.delete_button.setEnabled(template is not None and not self.is_builtin(template)
                                      and not self.selected_is_project_copy())

    # ---- actions (the button slots ask for a file, these do the work) ----------

    def edit_template(self, sample_paths: Sequence[str]) -> TemplateWizardDialog:
        """Opens the wizard on the samples with the selected template loaded (not yet shown)."""
        return TemplateWizardDialog(
            self, sample_paths, self.job_runner, library_folder=self.library_folder,
            builtin_names=self._builtin_names, template=self.selected_template())

    def new_template(self, sample_paths: Sequence[str]) -> TemplateWizardDialog:
        """Opens the wizard on the samples with no template loaded (not yet shown)."""
        return TemplateWizardDialog(self, sample_paths, self.job_runner, library_folder=self.library_folder,
                                  builtin_names=self._builtin_names)

    def export_template(self, path) -> str:
        """Writes the selected template to this file; blank when done, else the reason it was not."""
        template = self.selected_template()
        if template is None:
            return "Select a template."
        try:
            write_template_file(template, Path(path))
        except OSError as error:
            return f"The template cannot be exported: {error}"
        return ""

    def import_template(self, path) -> str:
        """Copies a template file into the library; blank when done, else the reason it was refused."""
        try:
            template = write_library_template_from_file(Path(path), self.library_folder, self._builtin_names)
        except (OSError, ValueError) as error:
            return str(error)
        self.refresh(select=template.name)
        return ""

    def delete_template(self) -> str:
        """Removes the selected library template; blank when done, else the reason it was not."""
        template = self.selected_template()
        if template is None:
            return "Select a template."
        if self.is_builtin(template):
            return f"'{template.name}' is built in and cannot be deleted."
        if self.selected_is_project_copy():
            return f"'{template.name}' is the project's own copy; it is not deleted here."
        if not delete_library_template(template.name, self.library_folder):
            return f"'{template.name}' is not in your library any more."
        self.refresh()
        return ""

    def _report(self, problem: str, done: str = "") -> None:
        self.status.setText(problem or done)
        if problem:
            QMessageBox.warning(self, "Import templates", problem)

    def _ask_new(self) -> None:
        samples = self._ask_samples("Sample files for the new template")
        if samples:
            self._run_wizard(self.new_template(samples))

    def _ask_samples(self, title: str) -> List[str]:
        samples, _ = QFileDialog.getOpenFileNames(self, title, "", "Table files (*.xlsx *.txt *.csv)")
        return samples

    def _run_wizard(self, dialog: TemplateWizardDialog) -> None:
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved_template:
            self.refresh(select=dialog.saved_template.name)
            self.status.setText(f"Saved '{dialog.saved_template.name}' into your library.")

    def _ask_edit(self) -> None:
        template = self.selected_template()
        if template is None:
            return
        if self.selected_is_project_copy():
            self.edit_project_template(template.name)
            return
        samples = self._ask_samples("Sample files to edit the template on")
        if samples:
            self._run_wizard(self.edit_template(samples))

    def _ask_export(self) -> None:
        template = self.selected_template()
        if template is None:
            return
        target = resolve_library_file(template.name, Path.home()).name
        path, _ = QFileDialog.getSaveFileName(self, "Export the template", target, "Import template (*.json)")
        if path:
            self._report(self.export_template(path), f"Exported '{template.name}'.")

    def _ask_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import a template", "", "Import template (*.json)")
        if not path:
            return
        try:
            name = read_template_file(Path(path)).name
        except ValueError as error:
            self._report(str(error))
            return
        if resolve_library_file(name, self.library_folder).exists():
            answer = QMessageBox.question(
                self, "Import templates", f"Your library already has a template '{name}'. Replace it?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._report(self.import_template(path), "Imported into your library.")

    def _ask_delete(self) -> None:
        template = self.selected_template()
        if template is None or self.is_builtin(template) or self.selected_is_project_copy():
            return
        answer = QMessageBox.question(
            self, "Import templates",
            f"Delete '{template.name}' from your library? Projects that already hold a copy keep it.")
        if answer == QMessageBox.StandardButton.Yes:
            self._report(self.delete_template(), f"Deleted '{template.name}'.")
