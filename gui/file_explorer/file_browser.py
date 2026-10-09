# =====================================================================
# FILE: gui/file_explorer/file_browser.py
# =====================================================================
"""
The disk side of the explorer: what exists, as opposed to what is being used.

Deliberately shallow. It shows folders and measurement files and nothing
inside them -- opening a file to list its channels is what the Data Pool is
for, and doing it here would mean parsing everything the user merely scrolled
past. What it does instead is tell them, at a glance, which of those files the
project already knows about, and let them push a folder or a selection into
the pool.

The colour rules are the point of the tree: a file already in the pool is not
worth adding twice, a folder with a metadata sheet behaves differently from
one without, and the project's own folder is where results are written. All
three are invisible in a plain file dialog.

All internal documentation strings and variable labels are standardly written
in English.
"""

import os

from PySide6.QtCore import QDir, QModelIndex, Qt, QPoint
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileSystemModel,
    QMenu,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from io_modules.measurement_files import SUPPORTED_EXTENSIONS, canonical_path, has_measurement_suffix

# The folder-adjacent Level 2 sheet, and the project-wide one beside the
# .nvhproject. Both are worth marking: a folder holding one behaves
# differently from a folder without.
METADATA_FILE_NAMES = {"metadata.xlsx"}

# What the browser lets through. The measurement formats come from the single
# list the scanner uses, so the two can never disagree about what a
# measurement is; the spreadsheets are added because the user needs to see
# whether a folder has one before deciding to add it.
BROWSER_NAME_FILTERS = list(SUPPORTED_EXTENSIONS) + ["*.xlsx", "*.xls"]

IN_POOL_COLOR = QColor("#2e7d32")
PROJECT_FOLDER_COLOR = QColor("#1565c0")
METADATA_COLOR = QColor("#ef6c00")


class BrowserFileSystemModel(QFileSystemModel):
    """
    A file system model that colours rows by what the project makes of them.

    Subclassed rather than decorated after the fact because QFileSystemModel
    populates itself lazily on a background thread -- rows appear as the OS
    reports them, so anything painted on by walking the tree once would miss
    every folder the user expands afterwards.
    """

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self._pool_paths: set = set()
        self._project_folder: str = ""

    def refresh_project_state(self):
        """
        Re-reads what the pool and the project currently hold.

        Cached rather than asked per row: data() is called for every visible
        row on every repaint, and resolving the project's sources each time
        would make scrolling a large folder crawl.
        """
        self._pool_paths = {
            canonical_path(run.file_path) for run in self.app_context.pool.loaded_runs
        }

        session = self.app_context.project_session
        self._project_folder = canonical_path(os.path.dirname(session.path)) if session.path else ""
        # Repainting the rows is the panel's job (refresh -> viewport().update()):
        # QFileSystemModel fills rows lazily, so there is no valid range to name
        # here -- the old dataChanged(index(0,0), ...) pointed at the first drive.

    def is_in_pool(self, path: str) -> bool:
        return canonical_path(path) in self._pool_paths

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ForegroundRole and index.isValid():
            path = canonical_path(self.filePath(index))

            if path in self._pool_paths:
                return QBrush(IN_POOL_COLOR)
            if self._project_folder and path == self._project_folder:
                return QBrush(PROJECT_FOLDER_COLOR)
            if os.path.basename(path).lower() in METADATA_FILE_NAMES:
                return QBrush(METADATA_COLOR)

        if role == Qt.ItemDataRole.ToolTipRole and index.isValid():
            path = canonical_path(self.filePath(index))
            if path in self._pool_paths:
                return "Already in the Data Pool"
            if self._project_folder and path == self._project_folder:
                return "This project's folder"

        return super().data(index, role)


class FileBrowserPanel(QWidget):
    """The OS tree plus the right-click actions that feed the Data Pool."""

    def __init__(self, app_context, data_pool, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.data_pool = data_pool
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.model = BrowserFileSystemModel(self.app_context, self)
        self.model.setRootPath("")
        self.model.setNameFilters(BROWSER_NAME_FILTERS)
        # Non-matching files stay visible but greyed out rather than vanishing:
        # a folder that looks empty reads as "wrong folder" when in fact it
        # only holds formats this build does not open.
        self.model.setNameFilterDisables(True)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)

        self.tree = QTreeView(self)
        self.tree.setModel(self.model)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.slot_show_context_menu)
        self.tree.doubleClicked.connect(self._slot_double_clicked)

        # Size, type and date add nothing here and cost most of the panel's width.
        for column in range(1, self.model.columnCount()):
            self.tree.hideColumn(column)
        self.tree.setHeaderHidden(True)

        layout.addWidget(self.tree)

    def refresh(self):
        """Repaints the tree after the pool or the project changed."""
        self.model.refresh_project_state()
        # data() recomputes the foreground per visible row on paint; force one
        # now so files just added to the pool go green without the user first
        # scrolling or resizing the panel (finding 4.4).
        self.tree.viewport().update()

    def reveal(self, directory: str):
        """Scrolls to a folder and opens it, without disturbing the selection."""
        if not directory or not os.path.isdir(directory):
            return
        index = self.model.index(directory)
        if index.isValid():
            self.tree.setExpanded(index, True)
            self.tree.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)

    # ---- interaction --------------------------------------------------

    def _slot_double_clicked(self, index: QModelIndex):
        """
        A double click on a measurement adds it; on a folder it just expands.

        Adding on double click is what makes the browser feel like a basket
        rather than a dialog, but only for files -- folders are how the user
        navigates, and swallowing that gesture would trap them.
        """
        if not index.isValid() or self.model.isDir(index):
            return
        path = self.model.filePath(index)
        if not _is_measurement(path):
            return
        # A file already in the pool is not worth adding twice: routing it back
        # through the ingest would rescan its whole folder (every header re-read)
        # only to integrate nothing new. The row is already marked as in-pool;
        # the user works with it from the Data Pool.
        if self.model.is_in_pool(path):
            return
        self._add_paths([path])

    def slot_show_context_menu(self, position: QPoint):
        indexes = [i for i in self.tree.selectedIndexes() if i.column() == 0]
        if not indexes:
            return

        paths = [self.model.filePath(index) for index in indexes]
        directories = [path for path in paths if os.path.isdir(path)]
        measurements = [path for path in paths if _is_measurement(path)]

        pool_keys = self.app_context.pool.pool_keys()
        pooled_dirs = [d for d in directories if canonical_path(d) in pool_keys]

        menu = QMenu(self)
        add_folder_action = None
        remove_folder_action = None
        add_files_action = None
        assign_action = None

        if directories:
            label = (f"📥 Add {len(directories)} folders to Data Pool"
                     if len(directories) > 1 else "📥 Add folder to Data Pool")
            add_folder_action = menu.addAction(label)

        if pooled_dirs:
            label = (f"🗑 Remove {len(pooled_dirs)} folders from Data Pool"
                     if len(pooled_dirs) > 1 else "🗑 Remove folder from Data Pool")
            remove_folder_action = menu.addAction(label)

        if measurements:
            add_files_action = menu.addAction(f"📥 Add {len(measurements)} file(s) to Data Pool")

        if not menu.actions():
            return

        menu.addSeparator()
        assign_action = menu.addAction("🧪 Add and assign to Test Setup...")

        menu.addSeparator()
        reveal_action = menu.addAction("📂 Show in File Explorer") if len(paths) == 1 else None
        copy_path_action = menu.addAction(
            "📋 Copy path" if len(paths) == 1 else f"📋 Copy {len(paths)} paths"
        )

        chosen = menu.exec(self.tree.viewport().mapToGlobal(position))
        if chosen is None:
            return

        if chosen == add_folder_action:
            self._add_paths(directories)
        elif chosen == remove_folder_action:
            self.data_pool.remove_directories(pooled_dirs)
        elif chosen == add_files_action:
            self._add_paths(measurements)
        elif chosen == assign_action:
            self._add_paths(directories + measurements, ask_for_setup=True)
        elif reveal_action is not None and chosen == reveal_action:
            from gui.file_explorer.reveal import show_in_file_manager
            show_in_file_manager(paths[0])
        elif chosen == copy_path_action:
            from gui.file_explorer.reveal import copy_paths_to_clipboard
            copy_paths_to_clipboard(paths)

    def _add_paths(self, paths: list, ask_for_setup: bool = False):
        self.data_pool.add_paths(paths, ask_for_setup=ask_for_setup)


def _is_measurement(path: str) -> bool:
    """
    Whether a path is a file this build may read as a measurement -- by suffix
    only. A generic suffix (.xlsx, .txt) is settled by its header later, in the
    ingest; reading headers here would put workbook I/O on every double-click
    and context menu.
    """
    return os.path.isfile(path) and has_measurement_suffix(path)
