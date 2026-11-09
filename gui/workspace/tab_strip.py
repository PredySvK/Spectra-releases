"""
TabStrip -- what the user does with the tab strip itself, apart from what
the tabs hold: the right-click menu, double click to rename, MRU switching
(Ctrl+Tab / Ctrl+Shift+Tab, Ctrl release commits, Esc cancels) and the tab
list (the ▾ corner button and Ctrl+E).

It never ends a tab nor writes a label itself: both have one owner, the
Workspace (#900), handed in as `close_dock`, `set_label` and `reset_label`.
"""

from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QTabWidget, QToolButton

from gui.workspace.tab_list_popup import TabListPopup
from gui.workspace.workspace_dock import WorkspaceDock
from view_models.tab_history import TabHistory


class TabKeyEventFilter(QObject):
    """Catches the Ctrl release that commits an MRU cycle and the Esc that cancels it (#846)."""

    def __init__(self, strip: "TabStrip"):
        super().__init__(strip.tabs)
        self._strip = strip

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyRelease:
            if event.key() == Qt.Key.Key_Control:
                self._strip.commit_mru_cycle()
        elif event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape and self._strip.history.is_cycling:
                self._strip.cancel_mru_cycle()
                return True
        return super().eventFilter(watched, event)


class TabStrip:
    """
    The tab strip's own behaviour over one QTabWidget.

    Public interface
        `build_context_menu`, `rename`, `close_others`, `close_all`,
        `switch_mru`, `commit_mru_cycle`, `cancel_mru_cycle`,
        `show_tab_list`, `forget` (the Workspace calls it as a tab ends),
        `history` (the TabHistory), `tabs`, `tab_list_button`.

    It takes the three Workspace calls it needs rather than the Workspace,
    so the strip can reach nothing else of it.

    The Home Workspace `placeholder` is never renamed, closed, listed or
    cycled to.
    """

    def __init__(self, tabs: QTabWidget, *, placeholder,
                 close_dock: Callable[[object], None],
                 set_label: Callable[[int, str], None],
                 reset_label: Callable[[int], None]):
        self.tabs = tabs
        self._placeholder = placeholder
        self._close_dock = close_dock
        self._set_label = set_label
        self._reset_label = reset_label
        self.history = TabHistory()

        tab_bar = tabs.tabBar()
        tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self._on_context_menu_requested)
        tab_bar.tabBarDoubleClicked.connect(self.rename)
        tabs.currentChanged.connect(self._on_current_changed)

        self._shortcut_next = self._window_shortcut("Ctrl+Tab", lambda: self.switch_mru(1))
        self._shortcut_previous = self._window_shortcut("Ctrl+Shift+Tab", lambda: self.switch_mru(-1))
        self._key_filter = TabKeyEventFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._key_filter)
        else:
            tabs.installEventFilter(self._key_filter)

        self.tab_list_button = QToolButton(tabs)
        self.tab_list_button.setText("▾")
        self.tab_list_button.setToolTip("List and search all open tabs (Ctrl+E)")
        self.tab_list_button.setAutoRaise(True)
        self.tab_list_button.clicked.connect(self.show_tab_list)
        tabs.setCornerWidget(self.tab_list_button, Qt.Corner.TopRightCorner)
        self._shortcut_tab_list = self._window_shortcut("Ctrl+E", self.show_tab_list)

    def _window_shortcut(self, keys: str, action) -> QShortcut:
        shortcut = QShortcut(QKeySequence(keys), self.tabs)
        shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        shortcut.activated.connect(action)
        return shortcut

    def _is_tab_index(self, index: int) -> bool:
        return 0 <= index < self.tabs.count()

    def _is_dock_index(self, index: int) -> bool:
        return self._is_tab_index(index) and self.tabs.widget(index) is not self._placeholder

    def _docks(self) -> list:
        widgets = (self.tabs.widget(i) for i in range(self.tabs.count()))
        return [widget for widget in widgets if widget is not self._placeholder]

    # -- Menu and rename ------------------------------------------------

    def build_context_menu(self, index: int) -> Optional[QMenu]:
        """Builds the context menu for the tab at `index` (#845, #847)."""
        if not self._is_tab_index(index):
            return None
        target = self.tabs.widget(index)
        is_home = target is self._placeholder

        menu = QMenu(self.tabs)

        action_rename = menu.addAction("Rename Tab...")
        action_rename.setEnabled(not is_home)
        action_rename.triggered.connect(lambda: self.rename(index))

        if not is_home and isinstance(target, WorkspaceDock) and target.custom_tab_label:
            action_reset = menu.addAction("Reset Tab Label")
            action_reset.triggered.connect(lambda: self._reset_label(index))

        menu.addSeparator()

        action_close = menu.addAction("Close")
        action_close.setEnabled(not is_home)
        action_close.triggered.connect(lambda: self._close_dock(target))

        docks = self._docks()
        action_close_others = menu.addAction("Close Others")
        action_close_others.setEnabled(any(dock is not target for dock in docks))
        action_close_others.triggered.connect(lambda: self.close_others(index))

        action_close_all = menu.addAction("Close All")
        action_close_all.setEnabled(bool(docks))
        action_close_all.triggered.connect(self.close_all)

        return menu

    def _on_context_menu_requested(self, pos: QPoint) -> None:
        tab_bar = self.tabs.tabBar()
        index = tab_bar.tabAt(pos)
        if index < 0:
            return
        menu = self.build_context_menu(index)
        if menu is not None:
            menu.exec(tab_bar.mapToGlobal(pos))

    def rename(self, index: int) -> None:
        """Prompts the user to rename the tab at `index`; an empty name resets it (#847)."""
        if not self._is_dock_index(index):
            return
        dock = self.tabs.widget(index)
        initial_text = dock.custom_tab_label or self.tabs.tabText(index)
        new_name, ok = QInputDialog.getText(self.tabs, "Rename Tab", "Tab label:", text=initial_text)
        if not ok:
            return
        new_name = new_name.strip()
        if new_name:
            self._set_label(index, new_name)
        else:
            self._reset_label(index)

    # -- Close many -----------------------------------------------------

    def close_others(self, keep_index: int) -> None:
        """Closes every dock except the one at `keep_index` and brings it to front (#845)."""
        if not self._is_tab_index(keep_index):
            return
        keep = self.tabs.widget(keep_index)
        for dock in self._docks():
            if dock is not keep:
                self._close_dock(dock)
        self.tabs.setCurrentWidget(keep)

    def close_all(self) -> None:
        """Closes every dock; the Home Workspace comes back (#845)."""
        for dock in self._docks():
            self._close_dock(dock)

    # -- MRU ------------------------------------------------------------

    def _on_current_changed(self, index: int) -> None:
        if self._is_dock_index(index):
            self.history.record_active(self.tabs.widget(index))

    def switch_mru(self, direction: int = 1) -> None:
        """Cycles tabs in most-recently-used order (#846)."""
        self.history.sync(self._docks())
        if self.history.is_cycling:
            target = self.history.step_cycle(direction)
        else:
            target = self.history.start_cycle(direction)
        if target is not None:
            self.tabs.setCurrentWidget(target)

    def commit_mru_cycle(self) -> None:
        """Commits the active MRU cycle (#846)."""
        self.history.finish_cycle()

    def cancel_mru_cycle(self) -> None:
        """Cancels the active MRU cycle and returns to the tab it started on (#846)."""
        cancelled = self.history.cancel_cycle()
        if cancelled is not None:
            self.tabs.setCurrentWidget(cancelled)

    def forget(self, dock) -> None:
        """Drops a dock that has ended from the MRU history."""
        self.history.remove(dock)

    # -- Tab list -------------------------------------------------------

    def show_tab_list(self) -> TabListPopup:
        """Opens the searchable popup of all open docks (#848)."""
        popup = TabListPopup(self.tabs, self._placeholder)
        button = self.tab_list_button
        if button.isVisible():
            popup.move(button.mapToGlobal(QPoint(button.width() - popup.minimumWidth(), button.height() + 2)))
        else:
            popup.move(self.tabs.mapToGlobal(QPoint(self.tabs.width() - popup.minimumWidth() - 10, 30)))
        popup.show()
        return popup
