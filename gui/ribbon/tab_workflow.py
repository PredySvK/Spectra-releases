# =====================================================================
# FILE: gui/ribbon/tab_workflow.py
# =====================================================================
"""
Ribbon tab for block-diagram workflows (ARCHITECTURE_DECISIONS §1.6, Epic P
phase 7C).

Selecting this tab swaps sub_area's centre from the analysis docks to the
WorkflowView (RibbonBar.handle_ribbon_tab_changed_routing ->
main_window.show_workflow_view). Which workflow is shown, and which node, is
chosen inside that view; this tab only carries the verbs.

Phase 7C: make an empty workflow, move one between projects, delete, and -- once
the graph type-checks and at least one block is ticked to save -- Run it over its
input node's selection. Building the graph (add blocks, edit params, pick the
input selection, tick Save) happens in the panel itself.
"""
from PySide6.QtWidgets import QHBoxLayout, QWidget

from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_ribbon_button, vertical_separator


class TabWorkflow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_context = parent.app_context if hasattr(parent, "app_context") else None
        self.init_ui()

    def init_ui(self) -> None:
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(8)

        self.btn_new = make_ribbon_button(
            "New\nWorkflow", "file-plus", kind="primary", big=True,
            tooltip="Create an empty block-diagram workflow, then add blocks in the panel",
        )
        create_group = RibbonGroup("Create")
        create_group.add(self.btn_new)
        layout.addWidget(create_group)
        layout.addWidget(vertical_separator())

        self.btn_run = make_ribbon_button(
            "Run", "play", kind="commit", big=True,
            tooltip="Run the selected workflow over its input node's selection, "
                    "writing one result set per block ticked to save",
        )
        run_group = RibbonGroup("Run")
        run_group.add(self.btn_run)
        layout.addWidget(run_group)
        layout.addWidget(vertical_separator())

        self.btn_import = make_ribbon_button(
            "Import…", "folder-open",
            tooltip="Load a workflow from a .json file into this project",
        )
        self.btn_export = make_ribbon_button(
            "Export…", "save-as",
            tooltip="Save the selected workflow to a .json file for another project",
        )
        self.btn_delete = make_ribbon_button(
            "Delete", "trash", kind="danger",
            tooltip="Remove the selected workflow from this project",
        )
        manage_group = RibbonGroup("Manage")
        manage_group.add_column(self.btn_import, self.btn_export, self.btn_delete)
        layout.addWidget(manage_group)

        build_tab_layout(self, layout, "workflow")
