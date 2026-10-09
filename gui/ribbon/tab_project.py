# FILE: gui/ribbon/tab_project.py
"""
Project ribbon card: everything that acts on the project as a whole.

Groups, left to right: Document (Save lead + New/Open/Save As stacked), Recent,
Data, Tools, then Help. The widgets are declared here and wired in MainWindowFrame,
matching every other ribbon tab.
"""

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_ribbon_button, vertical_separator

# How many recent projects the drop-down offers.
RECENT_LIMIT = 10


class TabProject(QWidget):
    """Project ribbon card: document, data-loading and management actions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(8)

        # -- Document --
        self.btn_save_project = make_ribbon_button(
            "Save", "save", kind="commit", big=True, tooltip="Save the current project")
        self.btn_new_project = make_ribbon_button(
            "New", "file-plus", tooltip="Start a new, empty project")
        self.btn_open_project = make_ribbon_button(
            "Open", "folder-open", tooltip="Open an existing project file")
        self.btn_save_project_as = make_ribbon_button(
            "Save As…", "save-as", tooltip="Save the project under a new name")

        for button, name in ((self.btn_save_project, "SaveProjectButton"), (self.btn_new_project, "NewProjectButton"),
                             (self.btn_open_project, "OpenProjectButton")):
            button.setObjectName(name)  # Help figure targets

        document = RibbonGroup("Document")
        document.add(self.btn_save_project)
        document.add_column(self.btn_new_project, self.btn_open_project,
                            self.btn_save_project_as, spacing=4)
        layout.addWidget(document)
        layout.addWidget(vertical_separator())

        # -- Recent --
        recent_column = QVBoxLayout()
        recent_column.setSpacing(2)
        recent_column.addWidget(QLabel("Recent project"))
        self.combo_recent = QComboBox()
        self.combo_recent.setMinimumWidth(220)
        self.combo_recent.setToolTip("Reopen a recently used project")
        recent_column.addWidget(self.combo_recent)
        recent_column.addStretch()
        recent = RibbonGroup("Recent")
        recent.add(recent_column)
        layout.addWidget(recent)
        layout.addWidget(vertical_separator())

        # -- Data --
        self.btn_select_dir = make_ribbon_button(
            "Add Data Directory", "folder-plus",
            tooltip="Add a folder to the Data Pool, keeping the folders already in it")
        self.btn_select_dir.setObjectName("AddDataDirectoryButton")  # Help figure target
        self.btn_edit_meta = make_ribbon_button(
            "Metadata and Filter Settings", "list",
            tooltip="Edit per-measurement metadata, the schema, and which fields are usable as filters")
        data = RibbonGroup("Data")
        data.add_column(self.btn_select_dir, self.btn_edit_meta, spacing=4)
        layout.addWidget(data)
        layout.addWidget(vertical_separator())

        # -- Tools --
        self.btn_generate_signal = make_ribbon_button(
            "Generate Debug Signal", "wrench",
            tooltip="Developer utility: synthesise a test measurement")
        self.btn_realize_dataset = make_ribbon_button(
            "Realize Test Dataset", "database",
            tooltip="Developer utility: write a whole version-controlled dataset to disk as .asc")
        tools = RibbonGroup("Tools")
        tools.add_column(self.btn_generate_signal, self.btn_realize_dataset, spacing=4)
        layout.addWidget(tools)

        build_tab_layout(self, layout, "project")

    # ---- recent projects -------------------------------------------------

    def populate_recent(self, project_paths):
        """
        Refills the recent list.

        The first entry is a placeholder rather than a project, so showing the
        list does not look like a selection and re-selecting the same project
        still fires a change signal.
        """
        self.combo_recent.blockSignals(True)
        self.combo_recent.clear()
        self.combo_recent.addItem("— select —", None)

        import os
        for path in project_paths[:RECENT_LIMIT]:
            self.combo_recent.addItem(os.path.basename(path), path)

        self.combo_recent.setCurrentIndex(0)
        self.combo_recent.setEnabled(bool(project_paths))
        self.combo_recent.blockSignals(False)

    def selected_recent_path(self):
        """The project path chosen in the drop-down, or None for the placeholder."""
        return self.combo_recent.currentData()

    def reset_recent_selection(self):
        self.combo_recent.blockSignals(True)
        self.combo_recent.setCurrentIndex(0)
        self.combo_recent.blockSignals(False)
