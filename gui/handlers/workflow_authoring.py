# =====================================================================
# FILE: gui/handlers/workflow_authoring.py
# =====================================================================
"""
Workflow ribbon actions (ARCHITECTURE_DECISIONS §1.6, Epic P phase 7C):
make a new (empty) workflow, move one between projects as JSON, delete one.
Building the graph up -- adding blocks, editing params, picking the input
selection -- happens inside `WorkflowView`, not here.

`WorkflowAuthoringHandler` groups these authoring actions with explicit
dependencies: `app_context`, `workflow_view`, and `parent_widget`.

There is no "save workflow" action: `save_workflow` upserts into
`NVHProject.workflows` and marks the project dirty, so Ctrl+S persists it, the
same as a selection or a test setup.

All internal documentation strings and variable labels are standardly written
in English.
"""
import json
from typing import Optional

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from core import workflow_graph
from core.workflow_graph import Workflow

__all__ = ["WorkflowAuthoringHandler"]


class WorkflowAuthoringHandler:
    """Handles workflow authoring actions (new, import, export, delete)."""

    def __init__(
        self,
        app_context,
        workflow_view,
        parent_widget: Optional[QWidget] = None,
    ) -> None:
        self._context = app_context
        self._workflow_view = workflow_view
        self._parent_widget = parent_widget

    def _refresh(self) -> None:
        if self._workflow_view is not None:
            self._workflow_view.refresh()

    def new_workflow(self) -> Optional[Workflow]:
        """Prompt for a name and store an empty graph (one input node, no selection,
        no blocks). The user adds blocks and picks the selection in the panel."""
        name, ok = QInputDialog.getText(
            self._parent_widget, "New Workflow", "Workflow name:"
        )
        name = name.strip()
        if not ok or not name:
            return None
        session = self._context.project_session
        if session.find_workflow(name) is not None:
            QMessageBox.warning(
                self._parent_widget,
                "New Workflow",
                f"A workflow named '{name}' already exists.",
            )
            return None
        stored = session.save_workflow(workflow_graph.new_workflow(name))
        self._refresh()
        if self._workflow_view is not None:
            self._workflow_view.select_workflow(name)
        self._context.log(f"WORKFLOW: created '{stored.name}'.")
        return stored

    def import_workflow(self) -> Optional[Workflow]:
        path, _ = QFileDialog.getOpenFileName(
            self._parent_widget, "Import Workflow", "", "Workflow JSON (*.json)"
        )
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                workflow = Workflow.from_dict(json.load(handle))
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
            QMessageBox.warning(
                self._parent_widget, "Import Workflow", f"This file is not a workflow:\n{exc}"
            )
            return None
        if not workflow.name:
            QMessageBox.warning(
                self._parent_widget, "Import Workflow", "That file has no workflow name."
            )
            return None
        session = self._context.project_session
        if session.find_workflow(workflow.name) is not None:
            confirm = QMessageBox.question(
                self._parent_widget,
                "Import Workflow",
                f"This project already has a workflow named '{workflow.name}'. Replace it?",
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return None
        stored = session.save_workflow(workflow)
        self._refresh()
        self._context.log(f"WORKFLOW: imported '{stored.name}'.")
        return stored

    def export_workflow(self) -> Optional[str]:
        name = (
            self._workflow_view.current_workflow_name()
            if self._workflow_view is not None
            else None
        )
        if not name:
            QMessageBox.information(
                self._parent_widget, "Export Workflow", "Select a workflow to export."
            )
            return None
        workflow = self._context.project_session.find_workflow(name)
        if workflow is None:
            return None
        path, _ = QFileDialog.getSaveFileName(
            self._parent_widget,
            "Export Workflow",
            f"{name}.json",
            "Workflow JSON (*.json)",
        )
        if not path:
            return None
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(workflow.to_dict(), handle, indent=2, ensure_ascii=False)
        except OSError as exc:
            QMessageBox.warning(
                self._parent_widget, "Export Workflow", f"Could not write it:\n{exc}"
            )
            return None
        self._context.log(f"WORKFLOW: exported '{name}' to {path}.")
        return path

    def delete_workflow(self) -> bool:
        name = (
            self._workflow_view.current_workflow_name()
            if self._workflow_view is not None
            else None
        )
        if not name:
            QMessageBox.information(
                self._parent_widget, "Delete Workflow", "Select a workflow to delete."
            )
            return False
        confirm = QMessageBox.question(
            self._parent_widget,
            "Delete Workflow",
            f"Remove workflow '{name}' from this project?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return False
        removed = self._context.project_session.remove_workflow(name)
        if removed:
            self._refresh()
            self._context.log(f"WORKFLOW: deleted '{name}'.")
        return removed
