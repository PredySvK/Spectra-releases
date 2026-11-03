"""
The questions and the report of reading files with Import templates.

Which templates an Add reads with, which of several fitting templates reads a
file, and the list of files that fit none (with "Edit template"). Before an
edit of a project's template copy is applied, its consequence summary is
confirmed; afterwards the edit may also be saved into the library. An Add with
a library template that differs from the project's copy asks, over the same
summary, whether the copy is replaced. What to ask,
what is a misfit and what an edit changes is decided by orchestration and the
view models; this only shows it and hands the choice back. Writing the one
library file is a short, user-started write and runs on the GUI thread (§1.137).

All internal documentation strings and variable labels are standardly written
in English.
"""

import dataclasses
import os
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from io_modules.import_template import resolve_library_file, write_library_template
from view_models.import_template import resolve_library_save_problem


def pick_import_templates(parent, templates: Sequence) -> List:
    """Shows the templates as a checklist; returns the ticked ones, empty on Cancel."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Add with templates")
    dialog.setMinimumWidth(380)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(
        "<b>Read the files with these Import templates</b><br>"
        "Each reads the files whose names fit its pattern."))
    listing = QListWidget()
    for template in templates:
        item = QListWidgetItem(f"{template.name}   ({template.file_pattern})")
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        listing.addItem(item)
    layout.addWidget(listing)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return []
    return [template for row, template in enumerate(templates)
            if listing.item(row).checkState() == Qt.CheckState.Checked]


def ask_import_templates(parent, questions: Sequence) -> Optional[Dict[Tuple[str, ...], str]]:
    """Asks which of the fitting templates reads each group of files; None on Cancel."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Import template")
    dialog.setMinimumWidth(420)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("<b>Some files fit more than one Import template.</b><br>"
                            "Which template should read them?"))
    boxes: Dict[Tuple[str, ...], QComboBox] = {}
    for question in questions:
        files = "file" if question.file_count == 1 else "files"
        layout.addWidget(QLabel(f"{question.file_count} {files} fit all of these:"))
        combo = QComboBox()
        combo.addItems(list(question.candidates))
        boxes[question.candidates] = combo
        layout.addWidget(combo)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return {candidates: combo.currentText() for candidates, combo in boxes.items()}


def show_misfit_report(parent, misfits: Sequence, editable: Sequence[bool] = ()) -> Optional[object]:
    """
    Lists the files that were not added because they do not fit their Import
    template. Returns the misfit whose template the user chose to edit ("Edit
    template", on the selected row -- the first one unless another is picked),
    None when the report was just closed. `editable` says per misfit whether
    its template can be edited; without it there is no Edit button.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Files that do not fit their Import template")
    dialog.resize(720, 320)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(f"<b>{len(misfits)} file(s) were not added.</b>"))
    table = QTableWidget(len(misfits), 3)
    table.setHorizontalHeaderLabels(["File", "Template", "Why it does not fit"])
    table.horizontalHeader().setStretchLastSection(True)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    for row, misfit in enumerate(misfits):
        for column, text in enumerate((os.path.basename(misfit.path), misfit.template, misfit.reason)):
            item = QTableWidgetItem(text)
            item.setToolTip(misfit.path if column == 0 else text)
            table.setItem(row, column, item)
    table.resizeColumnToContents(0)
    layout.addWidget(table)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    chosen: List = []
    if any(editable):
        edit = QPushButton("Edit template…")
        edit.setToolTip("Opens the import wizard on the selected file with its template loaded")
        box.addButton(edit, QDialogButtonBox.ButtonRole.ActionRole)

        def _row() -> int:
            row = table.currentRow()
            return row if 0 <= row < len(misfits) else 0

        def _edit() -> None:
            chosen.append(misfits[_row()])
            dialog.accept()

        def _enable() -> None:
            row = _row()
            edit.setEnabled(row < len(editable) and bool(editable[row]))

        edit.clicked.connect(_edit)
        table.currentCellChanged.connect(lambda *_args: _enable())
        table.selectRow(next((row for row, can in enumerate(editable) if can), 0))
        _enable()
    box.rejected.connect(dialog.reject)
    layout.addWidget(box)
    dialog.exec()
    return chosen[0] if chosen else None


def confirm_template_edit(parent, summary) -> bool:
    """Shows what applying an edit of the project's template copy changes; True when the user confirms."""
    box = QMessageBox(parent)
    box.setWindowTitle("Apply the template edit")
    box.setIcon(QMessageBox.Icon.Warning if summary.has_losses else QMessageBox.Icon.Question)
    box.setText(f"<b>Apply the edit of '{summary.template}' to this project?</b><br>"
                "The files read by this template are read again.")
    box.setInformativeText("\n".join(f"• {line}" for line in summary.lines()))
    box.setStandardButtons(QMessageBox.StandardButton.Apply | QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel if summary.has_losses
                         else QMessageBox.StandardButton.Apply)
    return box.exec() == QMessageBox.StandardButton.Apply


def ask_library_change(parent, summary) -> Optional[bool]:
    """
    Asks whether the project's copy of a template is replaced by the library's
    differing one before an Add: True replaces it, False keeps the copy, None
    (Cancel) drops the Add.
    """
    box = QMessageBox(parent)
    box.setWindowTitle("Import template changed in your library")
    box.setIcon(QMessageBox.Icon.Warning if summary.has_losses else QMessageBox.Icon.Question)
    box.setText(f"<b>'{summary.template}' in your library differs from this project's copy.</b><br>"
                "Replace the project's copy? The files read by this template are read again.")
    box.setInformativeText("\n".join(f"• {line}" for line in summary.lines()))
    replace = box.addButton("Replace the copy", QMessageBox.ButtonRole.AcceptRole)
    keep = box.addButton("Keep the project's copy", QMessageBox.ButtonRole.RejectRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(keep if summary.has_losses else replace)
    box.exec()
    if box.clickedButton() is replace:
        return True
    if box.clickedButton() is keep:
        return False
    return None


def ask_save_to_library(parent, template, library_folder=None, builtin_names=None) -> str:
    """
    Offers to save a template edited in the project also into the library:
    over the library's template of its name, or as a new one under a name the
    user gives. Returns what was done for the log, blank when nothing was.
    """
    box = QMessageBox(parent)
    box.setWindowTitle("Import template")
    box.setText(f"Also save '{template.name}' into your library?")
    box.setInformativeText("Other projects get a library change only when you add files with it again.")
    overwrite = box.addButton("Overwrite in library", QMessageBox.ButtonRole.AcceptRole)
    as_new = box.addButton("Save as new…", QMessageBox.ButtonRole.ActionRole)
    box.addButton("No", QMessageBox.ButtonRole.RejectRole)
    blocked = resolve_library_save_problem(template.name, builtin_names)
    overwrite.setEnabled(not blocked)
    overwrite.setToolTip(blocked)
    box.exec()
    if box.clickedButton() is overwrite:
        return write_library_copy(parent, template, library_folder, ask_replace=False)
    if box.clickedButton() is not as_new:
        return ""
    name, accepted = QInputDialog.getText(parent, "Save as new", "Name of the new template in your library:",
                                          text=f"{template.name} (new)")
    if not accepted:
        return ""
    problem = resolve_library_save_problem(name, builtin_names)
    if problem:
        QMessageBox.warning(parent, "Import template", problem)
        return ""
    return write_library_copy(parent, dataclasses.replace(template, name=name.strip()), library_folder,
                              ask_replace=True)


def write_library_copy(parent, template, library_folder=None, *, ask_replace: bool = True) -> str:
    """
    Writes the template into the library, asking first (`ask_replace`) before
    replacing one of its name. Returns what was done, blank when it was not.
    """
    if ask_replace and resolve_library_file(template.name, library_folder).exists():
        answer = QMessageBox.question(
            parent, "Import template", f"Your library already has a template '{template.name}'. Replace it?")
        if answer != QMessageBox.StandardButton.Yes:
            return ""
    try:
        write_library_template(template, library_folder)
    except OSError as error:
        QMessageBox.warning(parent, "Import template", f"The template cannot be saved: {error}")
        return ""
    return f"Saved the Import template '{template.name}' into your library."
