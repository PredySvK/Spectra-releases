# =====================================================================
# FILE: gui/file_explorer/measurement_selections.py
# =====================================================================
"""
The Explorer's "Selections" tab (#462): every Measurement selection of the
project with its "N measurements / M channels" against the current Data
Pool, and Create Selection, which opens the Selection editor
(gui/dialogs/measurement_selection_dialog.py) and stores the result through
the session (which marks the project unsaved). A selection's context menu
offers Edit, Rename (the workflows' Input nodes follow the new name) and Delete
(nothing cascades; the workflows that used it show "Not ready", #463).

The counts are resolved on the job runner, one job for the whole list,
superseded by the next refresh. `selections_changed` tells the composition
root a Selection was stored, so the Workflow panel's `Input selection:`
combo offers it at once.
"""
from typing import Optional

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtWidgets import (
    QInputDialog, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.jobs import job_step
from selection.measurement_selection import resolve
from selection.source_facets import all_pool_sources

from gui.dialogs.measurement_selection_dialog import MeasurementSelectionDialog, describe_counts
from gui.workspace.channel_drop_target import SELECTION_DRAG_MIME

_COUNT_SLOT = "measurement_selections.count"


def _count_all(selections, sources, schema) -> list:
    return [(selection.name, describe_counts(resolve(selection, sources, schema)))
            for selection in selections]


class _SelectionList(QListWidget):
    """The selections, each draggable by name onto a graph or the Workflow's Input node (#465)."""

    def mimeData(self, items):
        mime = QMimeData()
        mime.setData(SELECTION_DRAG_MIME, items[0].data(Qt.UserRole).encode("utf-8"))
        return mime


class MeasurementSelectionsPanel(QWidget):
    selections_changed = Signal()
    # A double click: the composition root draws it in a new graph (#465).
    selection_activated = Signal(str)

    def __init__(self, app_context, job_runner, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._job_runner = job_runner

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.btn_create = QPushButton("Create Selection")
        self.btn_create.clicked.connect(self.create_selection)
        layout.addWidget(self.btn_create)
        self.list_selections = _SelectionList()
        self.list_selections.setDragEnabled(True)
        self.list_selections.itemDoubleClicked.connect(
            lambda item: self.selection_activated.emit(item.data(Qt.UserRole)))
        self.list_selections.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_selections.customContextMenuRequested.connect(self._show_menu)
        layout.addWidget(self.list_selections, stretch=1)

    def _schema(self) -> dict:
        return self.app_context.pool.schema().master

    def refresh(self) -> None:
        """Re-list the project's selections and recount them on the job runner."""
        session = self.app_context.project_session
        selections = session.selections()
        self._fill([(s.name, "counting…") for s in selections])
        if not selections:
            self._job_runner.cancel_slot(_COUNT_SLOT)
            return
        self._job_runner.submit(
            "Count Selections",
            [job_step("Count", _count_all, selections,
                      all_pool_sources(session.project), self._schema())],
            lane="interactive", slot_key=_COUNT_SLOT, quiet=True,
            on_step=lambda rows, _index: self._show_counts(rows),
        )

    def _show_counts(self, rows) -> None:
        self._fill(rows)

    def _fill(self, rows) -> None:
        self.list_selections.clear()
        for name, counts in rows:
            item = QListWidgetItem(f"{name} — {counts}")
            item.setData(Qt.UserRole, name)
            self.list_selections.addItem(item)

    def _show_menu(self, position) -> None:
        item = self.list_selections.itemAt(position)
        if item is None:
            return
        name = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction("Edit…", lambda: self.edit_selection(name))
        menu.addAction("Rename…", lambda: self.rename_selection(name))
        menu.addAction("Delete…", lambda: self.delete_selection(name))
        menu.exec(self.list_selections.viewport().mapToGlobal(position))

    def create_selection(self) -> Optional[str]:
        """Open the editor on a new Selection; the saved name, None if cancelled."""
        return self._open_editor(None)

    def edit_selection(self, name: str) -> None:
        self._open_editor(self.app_context.project_session.find_selection(name))

    def _open_editor(self, existing) -> Optional[str]:
        session = self.app_context.project_session
        dialog = MeasurementSelectionDialog(
            session, self._schema(), self._job_runner, selection=existing,
            taken_names=[s.name for s in session.selections()
                         if existing is None or s.name != existing.name],
            settings=getattr(self.app_context, "settings", None), parent=self)
        try:
            accepted = dialog.exec()
            selection = dialog.selection() if accepted else None
        finally:
            dialog.deleteLater()
        if selection is None:
            return None
        session.save_selection(selection)
        self.app_context.log(f"SELECTION: '{selection.name}' saved.")
        self.refresh()
        self.selections_changed.emit()
        return selection.name

    def rename_selection(self, name: str) -> None:
        new_name, accepted = QInputDialog.getText(self, "Rename Selection", "New name:", text=name)
        new_name = new_name.strip()
        if not accepted or new_name == name:
            return
        session = self.app_context.project_session
        try:
            session.rename_selection(name, new_name)
        except ValueError as error:
            QMessageBox.warning(self, "Rename Selection", str(error))
            return
        self.app_context.log(f"SELECTION: '{name}' renamed to '{new_name}'.")
        self.refresh()
        self.selections_changed.emit()

    def delete_selection(self, name: str) -> None:
        session = self.app_context.project_session
        used_by = session.workflows_using_selection(name)
        text = f"Delete the selection '{name}'?"
        if used_by:
            text += ("\n\nThese workflows use it and will show \"Not ready\":\n"
                     + "\n".join(f"  • {workflow}" for workflow in used_by))
        if QMessageBox.question(self, "Delete Selection", text) != QMessageBox.Yes:
            return
        session.remove_selection(name)
        self.app_context.log(f"SELECTION: '{name}' deleted.")
        self.refresh()
        self.selections_changed.emit()
