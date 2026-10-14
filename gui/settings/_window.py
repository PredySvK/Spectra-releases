"""The Settings window: page tree on the left, breadcrumb and page on the right, Apply · Revert · Close."""

from html import escape
from typing import Any, Callable

from PySide6.QtCore import QSettings, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSpinBox,
    QStackedWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs.dialog_state import remember_dialog_geometry
from core.app_metadata import APP_VERSION
from core.dsp_configs import DSP_ALGORITHM_VERSIONS
from core.project_model import PROJECT_FORMAT_VERSION
from io_modules.changelog import read_changelog
from io_modules.result_cache.cache_layout import FORMAT_VERSION as RESULT_CACHE_FORMAT_VERSION
from view_models.settings import (
    SETTINGS_IMMEDIATE_KEYS,
    SETTINGS_PAGES,
    SettingsDraft,
    SettingsField,
    build_settings_breadcrumb,
    build_settings_search_results,
    resolve_settings_page,
)
from gui.appearance import APP_TOKENS


_PAGE_KEY = "settings_window_page"
_PAGE_ROLE = Qt.ItemDataRole.UserRole


def _build_highlighted_text(parts: tuple[tuple[str, bool], ...]) -> str:
    return "".join(
        f'<span style="background-color: {APP_TOKENS.search_highlight_background};'
        f' color: {APP_TOKENS.search_highlight_text};">{escape(text)}</span>'
        if highlighted else escape(text)
        for text, highlighted in parts)


class SettingsWindow(QDialog):
    """
    Non-modal; edits are a draft until Apply. ``apply`` receives the changed values.
    Closing (Close, ✕, Esc) all go through ``reject``, which asks about unapplied changes.
    """

    def __init__(
        self,
        values: dict[str, Any],
        apply: Callable[[dict[str, Any]], None],
        settings: QSettings | None = None,
        parent: QWidget | None = None,
        *,
        preview: Callable[[dict[str, Any]], None] | None = None,
        reset_layout: Callable[[], bool] | None = None,
        reset_all_settings: Callable[[], bool] | None = None,
        check_updates: Callable[[], None] | None = None,
        read_values: Callable[[], dict[str, Any]] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._draft = SettingsDraft(values)
        self._apply_values = apply
        self._preview = preview
        self._reset_layout = reset_layout
        self._reset_all_settings = reset_all_settings
        self._check_updates = check_updates
        self._read_values = read_values
        self._settings = settings
        self.editors: dict[str, QWidget] = {}
        self._labels: dict[str, QWidget] = {}
        self._match_labels: dict[str, QLabel] = {}
        self._page_items: dict[str, QTreeWidgetItem] = {}
        self._page_index: dict[str, int] = {}
        self._search_results = {result.page_id: result for result in build_settings_search_results("")}

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search settings…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setObjectName("SettingsSearch")
        self.search_box.textChanged.connect(self._on_search_changed)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setObjectName("SettingsPageTree")
        self.breadcrumb = QLabel()
        self.breadcrumb.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.pages = QStackedWidget()
        sections: dict[tuple[str, ...], QTreeWidgetItem] = {}
        for page in SETTINGS_PAGES:
            parent_item = self.tree.invisibleRootItem()
            for depth in range(1, len(page.path)):
                prefix = page.path[:depth]
                if prefix not in sections:
                    section = QTreeWidgetItem(parent_item, [prefix[-1]])
                    section.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    sections[prefix] = section
                parent_item = sections[prefix]
            item = QTreeWidgetItem(parent_item, [page.path[-1]])
            item.setData(0, _PAGE_ROLE, page.page_id)
            self._page_items[page.page_id] = item
            self._page_index[page.page_id] = self.pages.addWidget(self._build_page(page.page_id, page.fields))
        self.tree.expandAll()
        self._section_items = sections
        self.tree.currentItemChanged.connect(self._on_tree_changed)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.search_box)
        left_layout.addWidget(self.tree, 1)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.addWidget(self.breadcrumb)
        right_layout.addWidget(self.pages, 1)
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 560])

        self.btn_apply = QPushButton("Apply")
        self.btn_revert = QPushButton("Revert")
        self.btn_close = QPushButton("Close")
        self.btn_apply.setObjectName("SettingsApply")
        self.btn_apply.clicked.connect(self.apply)
        self.btn_revert.clicked.connect(self.revert)
        self.btn_close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        for button in (self.btn_apply, self.btn_revert, self.btn_close):
            button.setAutoDefault(False)  # Enter in a field must not Apply or close
            buttons.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)

        remember_dialog_geometry(self, settings, "settings_window", default_size=(760, 480))
        self.finished.connect(self.deleteLater)
        saved = str(settings.value(_PAGE_KEY, "")) if settings is not None else ""
        self.open_page(resolve_settings_page(saved).page_id)
        self._load_editors()

    # ---- public ------------------------------------------------------------

    @property
    def page_id(self) -> str:
        item = self.tree.currentItem()
        return item.data(0, _PAGE_ROLE) if item is not None else ""

    def open_page(self, page_id: str) -> None:
        self.tree.setCurrentItem(self._page_items[resolve_settings_page(page_id).page_id])

    def apply(self) -> None:
        self._apply_values(self._draft.apply())
        self._refresh_marks()

    @Slot(dict)
    def adopt_external_values(self, values: dict[str, Any]) -> None:
        """Show external updates without overwriting unapplied edits."""
        self._draft.adopt_external_values(values)
        self._load_editors()

    def adopt_project_values(self, values: dict[str, Any]) -> None:
        """Another project was opened: show its values, dropping unapplied edits of project fields."""
        self._draft.adopt_project_values(values)
        self._load_editors()

    def revert(self) -> None:
        restore = self._draft.revert()
        if restore and self._preview is not None:
            self._preview(restore)
        self._load_editors()

    def reject(self) -> None:
        if self._draft.is_dirty:
            answer = self._ask_apply_changes()
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Apply:
                self.apply()
            else:
                self.revert()
        super().reject()

    # ---- building ----------------------------------------------------------

    def _build_page(self, page_id: str, fields: tuple[SettingsField, ...]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        group = ""
        for field in fields:
            if field.group != group:
                group = field.group
                heading = QLabel(group)
                heading.setStyleSheet("font-weight: bold; margin-top: 8px;")
                layout.addWidget(heading)
            if field.kind == "choice":
                label = QLabel(field.label)
                editor = QComboBox()
                for text, value in field.choices:
                    editor.addItem(text, value)
                editor.currentIndexChanged.connect(
                    lambda _i, key=field.key, box=editor: self._on_edited(key, box.currentData()))
                layout.addWidget(label)
            elif field.kind == "integer":
                label = QLabel(field.label)
                editor = QSpinBox()
                editor.setRange(field.minimum, field.maximum)
                editor.setSuffix(field.suffix)
                editor.valueChanged.connect(lambda value, key=field.key: self._on_edited(key, value))
                layout.addWidget(label)
            elif field.kind == "toggle":
                editor = label = QPushButton(field.label)
                editor.setCheckable(True)
                editor.setAutoDefault(False)
                editor.toggled.connect(lambda on, key=field.key: self._on_edited(key, on))
            else:
                editor = label = QCheckBox(field.label)
                editor.toggled.connect(lambda on, key=field.key: self._on_edited(key, on))
            editor.setObjectName(f"Settings_{field.key}")  # Help figures point at it
            editor.setToolTip(field.description)
            layout.addWidget(editor)
            # Choices and tooltip descriptions must be visible when search hits them.
            match_label = QLabel()
            match_label.setTextFormat(Qt.TextFormat.RichText)
            match_label.setWordWrap(True)
            match_label.hide()
            layout.addWidget(match_label)
            self._match_labels[field.key] = match_label
            if field.note:
                note = QLabel(field.note)
                note.setEnabled(False)  # dimmed
                layout.addWidget(note)
            self.editors[field.key] = editor
            self._labels[field.key] = label
        if page_id == "layout":
            self.btn_reset_layout = QPushButton("Reset Layout")
            self.btn_reset_layout.setAutoDefault(False)
            self.btn_reset_layout.clicked.connect(lambda: self._run_reset(self._reset_layout))
            layout.addWidget(self.btn_reset_layout)
        elif page_id == "maintenance":
            self.btn_reset_all_settings = QPushButton("Reset All Settings")
            self.btn_reset_all_settings.setAutoDefault(False)
            self.btn_reset_all_settings.clicked.connect(
                lambda: self._run_reset(self._reset_all_settings))
            layout.addWidget(self.btn_reset_all_settings)
        elif page_id == "about":
            layout.addWidget(QLabel(f"App version: {APP_VERSION}"))
            layout.addWidget(QLabel(f"Project file format: {PROJECT_FORMAT_VERSION}"))
            layout.addWidget(QLabel(f"Result cache format: {RESULT_CACHE_FORMAT_VERSION}"))
            dsp_lines = ["DSP algorithms:"] + [
                f"    {kind}: {version}" for kind, version in DSP_ALGORITHM_VERSIONS.items()]
            layout.addWidget(QLabel("\n".join(dsp_lines)))
            self.btn_check_updates = QPushButton("Check for Updates")
            self.btn_check_updates.setAutoDefault(False)
            if self._check_updates is not None:
                self.btn_check_updates.clicked.connect(self._check_updates)
            layout.addWidget(self.btn_check_updates)
            layout.addWidget(QLabel("Changelog"))
            self.changelog = QTextBrowser()
            # Small bundled file, read synchronously like the Welcome page.
            self.changelog.setPlainText("\n\n".join(
                f"{entry.version} - {entry.date}\n"
                + "\n".join(f"• {change.text}" for change in entry.changes)
                for entry in read_changelog()) or "No changelog available.")
            layout.addWidget(self.changelog, 1)
            return page
        layout.addStretch()
        return page

    def _ask_apply_changes(self) -> QMessageBox.StandardButton:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Settings")
        box.setText("Apply changes?")
        box.setStandardButtons(
            QMessageBox.StandardButton.Apply
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        box.button(QMessageBox.StandardButton.Cancel).setText("Back")
        box.setDefaultButton(QMessageBox.StandardButton.Apply)
        return QMessageBox.StandardButton(box.exec())

    # ---- state -> widgets --------------------------------------------------

    def _load_editors(self) -> None:
        for key, editor in self.editors.items():
            editor.blockSignals(True)
            if isinstance(editor, QComboBox):
                editor.setCurrentIndex(max(0, editor.findData(self._draft.value(key))))
            elif isinstance(editor, QSpinBox):
                editor.setValue(self._draft.value(key))
            else:
                editor.setChecked(bool(self._draft.value(key)))
            editor.blockSignals(False)
        self._refresh_marks()

    def _refresh_marks(self) -> None:
        dirty = self._draft.dirty_keys
        for key, label in self._labels.items():
            font = label.font()
            font.setBold(key in dirty)
            label.setFont(font)
        for page in SETTINGS_PAGES:
            for field in page.fields:
                enabled = all(self._draft.value(key) == value for key, value in field.enabled_when)
                self.editors[field.key].setEnabled(enabled)
                self._labels[field.key].setEnabled(enabled)
            item = self._page_items[page.page_id]
            font = item.font(0)
            font.setBold(self._draft.page_is_dirty(page))
            item.setFont(0, font)
        self.btn_apply.setEnabled(bool(dirty))
        self.btn_revert.setEnabled(bool(dirty))

    def _run_reset(self, reset: Callable[[], bool] | None) -> None:
        """A confirmed reset drops every draft and reloads the applied values."""
        if self._read_values is not None and reset is not None and reset():
            self._draft = SettingsDraft(self._read_values())
            self._load_editors()

    def _on_edited(self, key: str, value: Any) -> None:
        self._draft.set_value(key, value)
        if key in SETTINGS_IMMEDIATE_KEYS and self._preview is not None:
            self._preview({key: value})
        self._refresh_marks()

    def _on_tree_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None or current.data(0, _PAGE_ROLE) is None:
            return
        page = resolve_settings_page(current.data(0, _PAGE_ROLE))
        result = self._search_results.get(page.page_id)
        if result is not None and any(highlighted for _, highlighted in result.breadcrumb):
            self.breadcrumb.setText(_build_highlighted_text(result.breadcrumb))
        else:
            self.breadcrumb.setText(build_settings_breadcrumb(page))
        self.pages.setCurrentIndex(self._page_index[page.page_id])
        if self._settings is not None:
            self._settings.setValue(_PAGE_KEY, page.page_id)

    def _on_search_changed(self, query: str) -> None:
        self._search_results = {
            result.page_id: result for result in build_settings_search_results(query)}
        for page_id, item in self._page_items.items():
            item.setHidden(page_id not in self._search_results)
        for item in reversed(tuple(self._section_items.values())):
            item.setHidden(all(item.child(i).isHidden() for i in range(item.childCount())))
        for label in self._match_labels.values():
            label.clear()
            label.hide()
        for result in self._search_results.values():
            for key, parts in result.field_matches.items():
                label = self._match_labels[key]
                label.setText(_build_highlighted_text(parts))
                label.show()
        self.pages.setVisible(bool(self._search_results))
        if not self._search_results:
            self.tree.setCurrentItem(None)
            self.breadcrumb.setText("No settings found.")
            return
        page_id = self.page_id if self.page_id in self._search_results else next(iter(self._search_results))
        self.open_page(page_id)
        self._on_tree_changed(self.tree.currentItem(), None)
        self.tree.expandAll()
