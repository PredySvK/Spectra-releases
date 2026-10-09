"""The Help window: tree on the left, page on the right, language selector beside the find bar."""

import atexit
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.app_metadata import SETTINGS_ORGANIZATION, SETTINGS_SHARED
from io_modules.help import HELP_FALLBACK_LANGUAGE, read_help_languages
from view_models.help import (
    build_help_page,
    build_help_search_results,
    build_help_tree,
    resolve_help_link,
    resolve_help_topic,
)

_LANGUAGE_KEY = "help_language"
_HIDE_AT_STARTUP_KEY = "help_hide_at_startup"
_TOPIC_ROLE = Qt.ItemDataRole.UserRole


class _EscapeFilter(QObject):
    """Clears the line edit and restores focus on Escape."""

    def __init__(self, target: QLineEdit, next_focus: QWidget):
        super().__init__(target)
        self._target = target
        self._next_focus = next_focus

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._target.clear()
            self._next_focus.setFocus()
            return True
        return super().eventFilter(obj, event)


class _HelpPage(QWebEnginePage):
    """Keeps navigation inside the manual: topic links stay in-window, web links leave."""

    def __init__(self, window: "HelpWindow"):
        super().__init__(window)
        self._window = window

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if url.scheme() == "file":
            return True
        link = resolve_help_link(url.toString())
        if link.kind == "topic":
            self._window.open_topic(link.topic_id, link.fragment)
        elif link.kind == "external":
            QDesktopServices.openUrl(url)
        return False


class HelpWindow(QWidget):
    def __init__(self, parent: QWidget | None = None, settings: QSettings | None = None):
        super().__init__(parent, Qt.WindowType.Window)
        # Unowned top-level (own taskbar entry, survives minimizing the main window), so it
        # must not keep the app alive after the main window closes.
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle("Help")
        self.resize(1000, 700)
        self._settings = settings or QSettings(SETTINGS_ORGANIZATION, SETTINGS_SHARED)
        self._topic_id = ""
        self._history: list[tuple[str, str]] = []
        self._history_pos = -1
        # setHtml() pages may not read file:// (KaTeX would stay unrendered), so pages go through a file.
        # mkdtemp + atexit (not TemporaryDirectory): no ResourceWarning when the dir outlives the window.
        page_dir = tempfile.mkdtemp(prefix="spectra_help_")
        atexit.register(shutil.rmtree, page_dir, ignore_errors=True)
        self._page_file = Path(page_dir) / "page.html"

        languages = read_help_languages()
        saved = str(self._settings.value(_LANGUAGE_KEY, HELP_FALLBACK_LANGUAGE))
        self._language = saved if saved in languages else HELP_FALLBACK_LANGUAGE
        self.language_box = QComboBox()
        for code in languages:
            self.language_box.addItem(code.upper(), code)
        self.language_box.setCurrentIndex(self.language_box.findData(self._language))
        self.language_box.currentIndexChanged.connect(self._on_language_changed)

        # Left pane: search box above topic tree
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search topics…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_changed)
        self.search_box.returnPressed.connect(self._on_search_return_pressed)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._on_tree_changed)
        self.search_box.installEventFilter(_EscapeFilter(self.search_box, self.tree))

        self.btn_back = QPushButton("↶")
        self.btn_back.setToolTip("Back (Alt+Left)")
        self.btn_back.clicked.connect(self.go_back)
        self.btn_forward = QPushButton("↷")
        self.btn_forward.setToolTip("Forward (Alt+Right)")
        self.btn_forward.clicked.connect(self.go_forward)
        for btn in (self.btn_back, self.btn_forward):
            btn.setFixedWidth(32)
            btn.setStyleSheet("font-size: 16px;")
        QShortcut(QKeySequence("Alt+Left"), self).activated.connect(self.go_back)
        QShortcut(QKeySequence("Alt+Right"), self).activated.connect(self.go_forward)
        nav_bar = QHBoxLayout()
        nav_bar.setContentsMargins(0, 0, 0, 0)
        nav_bar.addWidget(self.btn_back)
        nav_bar.addWidget(self.btn_forward)
        nav_bar.addStretch()

        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addLayout(nav_bar)
        left_layout.addWidget(self.search_box)
        left_layout.addWidget(self.tree)

        # Right pane: in-page find bar above web view
        self.find_box = QLineEdit()
        self.find_box.setPlaceholderText("Find in page…")
        self.find_box.setClearButtonEnabled(True)
        self.find_box.textChanged.connect(self._on_find_text_changed)
        self.find_box.returnPressed.connect(self._on_find_return_pressed)

        self.btn_find_prev = QPushButton("◀")
        self.btn_find_prev.setToolTip("Previous match (Shift+Enter)")
        self.btn_find_prev.setFixedWidth(28)
        self.btn_find_prev.clicked.connect(lambda: self.find_previous())

        self.btn_find_next = QPushButton("▶")
        self.btn_find_next.setToolTip("Next match (Enter)")
        self.btn_find_next.setFixedWidth(28)
        self.btn_find_next.clicked.connect(lambda: self.find_next())

        self.find_label = QLabel("")
        self.find_label.setStyleSheet("color: #888;")

        self.view = QWebEngineView()
        self.view.setPage(_HelpPage(self))
        self.view.loadFinished.connect(self._on_page_loaded)
        self.find_box.installEventFilter(_EscapeFilter(self.find_box, self.view))

        find_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        find_shortcut.activated.connect(self._focus_find_box)

        find_bar = QHBoxLayout()
        find_bar.setContentsMargins(0, 0, 0, 0)
        find_bar.addWidget(QLabel("Find:"))
        find_bar.addWidget(self.find_box)
        find_bar.addWidget(self.btn_find_prev)
        find_bar.addWidget(self.btn_find_next)
        find_bar.addWidget(self.find_label)
        find_bar.addSpacing(12)
        find_bar.addWidget(QLabel("Language:"))
        find_bar.addWidget(self.language_box)

        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addLayout(find_bar)
        right_layout.addWidget(self.view, 1)

        splitter = QSplitter()
        splitter.addWidget(left_pane)
        splitter.addWidget(right_pane)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 740])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        # Only offered when the window opens by itself at launch (see show_help_at_startup).
        self.cb_dont_show_again = QCheckBox("Don't show this again")
        self.cb_dont_show_again.toggled.connect(
            lambda on: self._settings.setValue(_HIDE_AT_STARTUP_KEY, on))
        self.cb_dont_show_again.hide()
        layout.addWidget(self.cb_dont_show_again)
        self._fill_tree()
        self._update_nav_buttons()

    @property
    def topic_id(self) -> str:
        return self._topic_id

    @property
    def language(self) -> str:
        return self._language

    def open_topic(self, topic_id: str, fragment: str = "", *, _record: bool = True) -> None:
        if _record and (topic_id, fragment) != (self._history[self._history_pos] if self._history else None):
            del self._history[self._history_pos + 1:]
            self._history.append((topic_id, fragment))
            self._history_pos += 1
            self._update_nav_buttons()
        self._topic_id = topic_id
        self._select_in_tree(topic_id)
        page = build_help_page(topic_id, self._language, fragment)
        self._page_file.write_text(page.html, encoding="utf-8")
        self.view.load(QUrl.fromLocalFile(str(self._page_file)))

    def go_back(self) -> None:
        self._go_to(self._history_pos - 1)

    def go_forward(self) -> None:
        self._go_to(self._history_pos + 1)

    def _go_to(self, pos: int) -> None:
        if 0 <= pos < len(self._history):
            self._history_pos = pos
            self._update_nav_buttons()
            self.open_topic(*self._history[pos], _record=False)

    def _update_nav_buttons(self) -> None:
        self.btn_back.setEnabled(self._history_pos > 0)
        self.btn_forward.setEnabled(self._history_pos < len(self._history) - 1)

    def find_in_page(self, text: str, backward: bool = False, callback: Any = None) -> None:
        """Search the active page in the web view for ``text`` and highlight matches."""
        if self.find_box.text() != text:
            self.find_box.blockSignals(True)
            self.find_box.setText(text)
            self.find_box.blockSignals(False)

        stripped = text.strip()
        if not stripped:
            self.view.findText("")
            self.find_label.setText("")
            if callback:
                callback(0, 0)
            return

        flags = QWebEnginePage.FindFlag.FindBackward if backward else QWebEnginePage.FindFlag(0)

        def handle_result(result):
            total = result.numberOfMatches()
            active = result.activeMatch()
            if total == 0:
                self.find_label.setText("0 matches")
            else:
                self.find_label.setText(f"{active} of {total}")
            if callback:
                callback(active, total)

        self.view.findText(stripped, flags, handle_result)

    def find_next(self, text: str | None = None, callback: Any = None) -> None:
        query = self.find_box.text() if text is None else text
        self.find_in_page(query, backward=False, callback=callback)

    def find_previous(self, text: str | None = None, callback: Any = None) -> None:
        query = self.find_box.text() if text is None else text
        self.find_in_page(query, backward=True, callback=callback)

    def _focus_find_box(self) -> None:
        self.find_box.setFocus()
        self.find_box.selectAll()

    def _on_find_text_changed(self, text: str) -> None:
        self.find_in_page(text)

    def _on_find_return_pressed(self) -> None:
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self.find_previous()
        else:
            self.find_next()

    def _on_page_loaded(self, ok: bool) -> None:
        if ok and self.find_box.text().strip():
            self.find_in_page(self.find_box.text())

    def _on_search_changed(self, text: str) -> None:
        query = text.strip()
        if not query:
            self._set_tree_filter(None)
            return
        results = build_help_search_results(query, self._language)
        self._set_tree_filter({r.topic_id for r in results})

    def _on_search_return_pressed(self) -> None:
        for item in self.tree.findItems("*", Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive):
            if not item.isHidden():
                self.tree.setCurrentItem(item)
                break

    def _set_tree_filter(self, matching_ids: set[str] | None) -> None:
        self.tree.blockSignals(True)

        def filter_item(item: QTreeWidgetItem, parent_matched: bool = False) -> bool:
            topic_id = item.data(0, _TOPIC_ROLE)
            item_matches = matching_ids is None or topic_id in matching_ids
            effective_match = item_matches or parent_matched
            child_matches = False
            for i in range(item.childCount()):
                if filter_item(item.child(i), parent_matched=effective_match):
                    child_matches = True
            visible = effective_match or child_matches
            item.setHidden(not visible)
            if child_matches:
                item.setExpanded(True)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            filter_item(self.tree.topLevelItem(i))

        if matching_ids is None:
            self.tree.expandAll()
        self.tree.blockSignals(False)

    def _fill_tree(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()

        def add(parent, entry):
            item = QTreeWidgetItem([entry.title])
            item.setData(0, _TOPIC_ROLE, entry.topic_id)
            (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(item)
            for child in entry.children:
                add(item, child)

        for entry in build_help_tree(self._language):
            add(self.tree, entry)
        self.tree.expandAll()
        self.tree.blockSignals(False)

    def _select_in_tree(self, topic_id: str) -> None:
        self.tree.blockSignals(True)
        for item in self.tree.findItems("*", Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive):
            if item.data(0, _TOPIC_ROLE) == topic_id:
                self.tree.setCurrentItem(item)
                break
        self.tree.blockSignals(False)

    def _on_tree_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is not None:
            self.open_topic(current.data(0, _TOPIC_ROLE))

    def _on_language_changed(self, _index: int) -> None:
        self._language = self.language_box.currentData()
        self._settings.setValue(_LANGUAGE_KEY, self._language)
        self._fill_tree()
        if self.search_box.text().strip():
            self._on_search_changed(self.search_box.text())
        if self._topic_id:
            self.open_topic(self._topic_id)


_window: HelpWindow | None = None


def show_help(context: str, owner: QWidget | None = None) -> None:
    """Open the one Help window on the topic of a tab ``context`` (or topic id)."""
    global _window
    if _window is None:
        # No parent on purpose: an owned window hides with its owner and makes Qt recreate its HWND (#578).
        _window = HelpWindow()
        _window.destroyed.connect(_forget_window)
    _window.open_topic(resolve_help_topic(context))
    if _window.isMinimized():
        _window.showNormal()
    _window.show()
    _window.raise_()
    _window.activateWindow()


def close_help() -> None:
    """Close the Help window if it is open (called when the main window closes)."""
    if _window is not None:
        _window.close()


def show_help_at_startup(owner: QWidget) -> None:
    """Open Help on the quick start at launch, unless the user ticked "Don't show this again"."""
    settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_SHARED)
    if settings.value(_HIDE_AT_STARTUP_KEY, False, type=bool):
        return
    show_help("workflow", owner)
    _window.cb_dont_show_again.show()


def _forget_window(*_args) -> None:
    global _window
    _window = None
