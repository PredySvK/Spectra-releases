# =====================================================================
# FILE: gui/file_explorer/file_explorer.py
# =====================================================================
"""
The left-hand Explorer dock: a disk browser, the Data Pool, the Result Pool,
the project's Selections (in every mode), and -- while the ribbon's Workflow tab is active -- the Block Pool palette, as
side-by-side tabs.

What used to be one tree doing both jobs. Browsing a folder replaced the
working set, so looking at what else was on the drive cost the user everything
they had lined up, and only one folder could ever be open at a time. The two
activities are now two tabs -- gui/file_explorer/file_browser.py finds files,
gui/file_explorer/data_pool_panel.py holds the ones being worked on -- and the pool
spans as many folders as the user adds to it.

This module is deliberately thin. It exists so that everything which already
reached for `explorer_panel.rebuild_tree_view()` or `explorer_panel.tree`
after changing something -- the unit fixes, the metadata editor, the synthetic
signal generator, the window's own directory load -- kept working without
knowing the panel had grown a second tab underneath.

All internal documentation strings and variable labels are standardly written
in English.
"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from gui.file_explorer.data_pool_panel import DataPoolPanel
from gui.file_explorer.file_browser import FileBrowserPanel
from gui.file_explorer.measurement_selections import MeasurementSelectionsPanel
from gui.file_explorer.pool_watcher import PoolWatcher
from gui.file_explorer.result_pool import ResultPoolPanel
from gui.workspace.block_pool_panel import BlockPoolPanel

_BLOCK_POOL_TAB_LABEL = "🧩 Block Pool"


class UnvChannelExplorer(QWidget):
    def __init__(self, app_context, data_pool, parent=None, *,
                 filter_panel=None, focused_dock=None,
                 result_content_handler=None,
                 refresh_and_apply_for_focused_dock=None, job_runner=None):
        super().__init__(parent)
        self.app_context = app_context
        self.job_runner = job_runner
        # The one owner of what the pool holds (#240). Built by the composition
        # root before this panel, because all three tabs below call it.
        self.data_pool = data_pool
        self.filter_panel = filter_panel
        self._focused_dock = focused_dock
        self.result_content_handler = result_content_handler
        # Passed straight through to ResultPoolPanel (see its constructor) --
        # this panel itself never calls it.
        self._refresh_and_apply_for_focused_dock = refresh_and_apply_for_focused_dock
        self.init_ui()

        # Owned here rather than by the window because this is where the pool
        # is drawn, and the one moment the watched set is guaranteed to be
        # correct is right after the tree has been rebuilt from it.
        self.watcher = PoolWatcher(app_context, data_pool, self)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget(self)
        # Slightly smaller labels so all five fit the default column width. A font
        # change (not a QSS tab rule) keeps the native selected-tab look.
        font = self.tabs.tabBar().font()
        font.setPointSizeF(font.pointSizeF() - 1)
        self.tabs.tabBar().setFont(font)
        self.tabs.setObjectName("ExplorerTabs")
        self.browser_panel = FileBrowserPanel(self.app_context, self.data_pool, self)
        self.pool_panel = DataPoolPanel(self.app_context, self.filter_panel, self.data_pool, self)
        self.result_pool_panel = ResultPoolPanel(
            self.app_context, self._focused_dock, self,
            result_content_handler=self.result_content_handler,
            refresh_and_apply_for_focused_dock=self._refresh_and_apply_for_focused_dock,
        )
        self.selections_panel = MeasurementSelectionsPanel(self.app_context, self.job_runner, self)

        # The block palette. Built here so it is tabbed alongside the two data
        # views, but only shown while the ribbon's Workflow tab is active
        # (MainWindowFrame.show_workflow_view -> set_block_pool_visible).
        self.block_pool_panel = BlockPoolPanel(self)
        # Not in any layout until set_block_pool_visible(True) reparents it
        # into the tab widget -- left visible, it's an unmanaged child sitting
        # at (0, 0) and its hint text ghosts through the tab bar on first show.
        self.block_pool_panel.hide()

        self.tabs.addTab(self.browser_panel, "📁 File Browser")
        self.tabs.addTab(self.pool_panel, "📥 Data Pool")
        self.tabs.addTab(self.result_pool_panel, "📈 Result Pool")
        self.tabs.addTab(self.selections_panel, "🔖 Selections")
        # Fresh-install default: the file browser is the entry point for a
        # session that has no data loaded yet.
        self.tabs.setCurrentWidget(self.browser_panel)

        layout.addWidget(self.tabs)

    def bind_workspace(self, workspace) -> None:
        """Hands the pool tree the thing that opens tabs, once it exists."""
        self.pool_panel.workspace = workspace

    def set_block_pool_visible(self, on: bool) -> None:
        """Adds or removes the Block Pool tab. Removing keeps the widget alive
        (Qt retains ownership), so re-adding it later is free."""
        idx = self.tabs.indexOf(self.block_pool_panel)
        if on and idx == -1:
            new_idx = self.tabs.addTab(self.block_pool_panel, _BLOCK_POOL_TAB_LABEL)
            self.tabs.setCurrentIndex(new_idx)
        elif not on and idx != -1:
            self.tabs.removeTab(idx)

    @property
    def tree(self):
        """
        The pool's channel tree.

        Kept as a property because callers that had a single explorer tree
        still mean this one -- it is the tree with channels in it.
        """
        return self.pool_panel.tree

    def rebuild_tree_view(self):
        """Redraws the pool, repaints the browser, recounts the Selections and
        re-aims the folder watcher."""
        self.pool_panel.rebuild_tree_view()
        self.selections_panel.refresh()
        self.browser_panel.refresh()
        self.watcher.sync()

    def refresh_browser(self):
        self.browser_panel.refresh()

    def reveal_in_browser(self, directory: str):
        """Points the browser at a folder without switching tabs to it."""
        self.browser_panel.reveal(directory)
