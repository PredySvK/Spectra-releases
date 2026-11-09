"""Tab list dropdown with search for open graph tabs (#848)."""

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from view_models.tab_label import TabSearchEntry, filter_tab_entries


class TabListPopup(QDialog):
    """Searchable popup listing open tabs in the workspace (#848)."""

    def __init__(self, tabs, placeholder):
        super().__init__(tabs, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._tabs = tabs
        self._placeholder = placeholder
        self._entries: List[TabSearchEntry] = []

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumWidth(320)
        self.setMaximumHeight(350)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        self.container = QFrame(self)
        self.container.setObjectName("tabListContainer")
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(4)

        self.search_input = QLineEdit(self.container)
        self.search_input.setPlaceholderText("Search open tabs...")
        self.search_input.textChanged.connect(self._on_search_text_changed)
        container_layout.addWidget(self.search_input)

        self.list_widget = QListWidget(self.container)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.itemActivated.connect(self._on_item_activated)
        self.list_widget.itemClicked.connect(self._on_item_activated)
        container_layout.addWidget(self.list_widget)

        main_layout.addWidget(self.container)

        self._refresh_entries()
        self.search_input.setFocus()

    def _refresh_entries(self) -> None:
        tabs = self._tabs
        placeholder = self._placeholder
        curr_idx = tabs.currentIndex()

        self._entries = []
        for i in range(tabs.count()):
            widget = tabs.widget(i)
            if widget is placeholder:
                continue
            title = tabs.tabText(i)
            tooltip = tabs.tabToolTip(i)
            self._entries.append(
                TabSearchEntry(
                    index=i,
                    title=title,
                    tooltip=tooltip,
                    is_active=(i == curr_idx),
                )
            )
        self._render_items(self._entries)

    def _render_items(self, entries: List[TabSearchEntry]) -> None:
        self.list_widget.clear()
        for entry in entries:
            item = QListWidgetItem()
            display_text = entry.title
            if entry.is_active:
                display_text = f"● {display_text}"
            item.setText(display_text)
            item.setToolTip(entry.tooltip)
            item.setData(Qt.ItemDataRole.UserRole, entry.index)
            self.list_widget.addItem(item)
            if entry.is_active and not self.list_widget.currentItem():
                self.list_widget.setCurrentItem(item)

        if not self.list_widget.currentItem() and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _on_search_text_changed(self, text: str) -> None:
        filtered = filter_tab_entries(self._entries, text)
        self._render_items(filtered)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is not None and 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)
        self.accept()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            row = self.list_widget.currentRow()
            count = self.list_widget.count()
            if count > 0:
                if key == Qt.Key.Key_Down:
                    next_row = (row + 1) % count
                else:
                    next_row = (row - 1 + count) % count
                self.list_widget.setCurrentRow(next_row)
            event.accept()
            return
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            curr = self.list_widget.currentItem()
            if curr is not None:
                self._on_item_activated(curr)
            event.accept()
            return
        elif key == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
            return
        super().keyPressEvent(event)
