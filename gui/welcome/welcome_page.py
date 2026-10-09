# gui/welcome/welcome_page.py
"""
The no-project state: what the window shows before a project is open.

Two big choices -- New or Open -- and the recent list. It owns no application
state; every action leaves as a signal that MainWindowFrame routes to the same
cli_* project commands the ribbon uses. A saved layout, the ribbon and the docks
all belong to WorkspacePage and stay hidden while this is up.

Layer: gui/. Pure view -- it is handed a list of core.recent_projects.RecentProject
and emits paths back out.
"""
from __future__ import annotations

import html
import os
from pathlib import Path
from typing import List, Optional, Tuple, TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QFrame, QSizePolicy, QTextBrowser,
)

from core.app_metadata import APP_TITLE
from core.jobs import job_step
from core.recent_projects import RecentProject
from io_modules.changelog import ChangelogEntry
from view_models.recent_projects import format_when

if TYPE_CHECKING:
    from orchestration.jobs import JobRunner

# The recent list on the Welcome screen stays short on purpose -- the full
# history is in the Project ribbon drop-down.
_WELCOME_RECENT_LIMIT = 5

# Widest a changelog screenshot is drawn: the 960 px column minus margins and scrollbar.
_SCREENSHOT_MAX_WIDTH = 860

_WELCOME_RECENT_SLOT = "welcome_page_recent_check"


def _check_path_exists(path: str) -> Tuple[str, bool]:
    return path, os.path.exists(path)


# Extensions a drop is allowed to be. A folder is also accepted (durability
# layout: one folder = one cycle point), handled separately in dropEvent.
_PROJECT_SUFFIX = ".nvhproject"


def _screenshots_html(paths) -> str:
    """<img> per readable screenshot, shrunk to fit the box (Qt does not scale on its own)."""
    tags = []
    for path in paths:
        width = QImage(path).width()
        if width:
            tags.append(f'<br><img src="{Path(path).as_uri()}" width="{min(width, _SCREENSHOT_MAX_WIDTH)}">')
    return "".join(tags)


class _Tile(QPushButton):
    """One of the two big primary choices."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setMinimumSize(220, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton { font-size: 18px; font-weight: bold; border: 1px solid #3b5998;"
            " border-radius: 8px; padding: 16px; }"
            "QPushButton:hover { background-color: #3b5998; color: white; }"
        )


class WelcomePage(QWidget):
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_recent_requested = Signal(str)
    path_dropped = Signal(str)

    def __init__(self, job_runner: Optional[JobRunner] = None, parent=None):
        super().__init__(parent)
        self.job_runner = job_runner
        self.setAcceptDrops(True)
        self._build_ui()

    # -- construction ---------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.addStretch(1)

        column = QVBoxLayout()
        column.setSpacing(18)
        column.setContentsMargins(0, 24, 0, 24)

        heading = QLabel(APP_TITLE)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet("font-size: 28px; font-weight: bold;")
        column.addWidget(heading)

        subtitle = QLabel("Open a project to begin, or drop a .nvhproject file or a data folder here.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #888;")
        column.addWidget(subtitle)

        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        self.tile_new = _Tile("📁\nNew Project")
        self.tile_open = _Tile("📂\nOpen Project")
        self.tile_new.clicked.connect(self.new_project_requested)
        self.tile_open.clicked.connect(self.open_project_requested)
        tiles.addWidget(self.tile_new)
        tiles.addWidget(self.tile_open)
        column.addLayout(tiles)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        column.addWidget(line)

        recent_label = QLabel("Recent")
        recent_label.setStyleSheet("font-weight: bold; color: #888;")
        column.addWidget(recent_label)

        self.recent_list = QListWidget()
        self.recent_list.setMinimumHeight(160)
        self.recent_list.setStyleSheet("QListWidget { border: 1px solid #444; border-radius: 6px; }")
        self.recent_list.itemActivated.connect(self._emit_selected)
        self.recent_list.itemDoubleClicked.connect(self._emit_selected)
        column.addWidget(self.recent_list)

        self.empty_hint = QLabel("No recent projects yet.")
        self.empty_hint.setStyleSheet("color: #888;")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.empty_hint)

        self.whats_new_label = QLabel("What's new")
        self.whats_new_label.setStyleSheet("font-weight: bold; color: #888;")
        column.addWidget(self.whats_new_label)

        self.whats_new = QTextBrowser()
        self.whats_new.setMinimumHeight(200)
        self.whats_new.setStyleSheet("QTextBrowser { border: 1px solid #444; border-radius: 6px; }")
        column.addWidget(self.whats_new, stretch=1)  # takes all the spare height
        self.set_changelog([])

        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(960)
        outer.addWidget(holder, stretch=3)
        outer.addStretch(1)

    # -- data ---------------------------------------------------------------

    def set_changelog(self, entries: List[ChangelogEntry]) -> None:
        """Scrollable list of released versions, hidden when there is nothing to show."""
        self.whats_new_label.setVisible(bool(entries))
        self.whats_new.setVisible(bool(entries))
        self.whats_new.setHtml("".join(
            f"<p><b>{html.escape(e.version)} - {html.escape(e.date)}</b></p><ul>"
            + "".join(f"<li>{html.escape(c.text)}{_screenshots_html(c.images)}</li>" for c in e.changes)
            + "</ul>"
            for e in entries))

    def set_recent(self, entries: List[RecentProject]) -> None:
        """
        Fills the recent list immediately; existence is verified in the background
        so an inaccessible network share never freezes the GUI thread (#412).
        Missing projects are greyed and made inert when the check reports.
        """
        self.recent_list.clear()
        shown = entries[:_WELCOME_RECENT_LIMIT]

        for entry in shown:
            when = format_when(entry.last_opened)
            detail = f"{entry.path}" + (f"  ·  {when}" if when else "")
            item = QListWidgetItem(f"{entry.display_name}\n{detail}")
            item.setData(Qt.ItemDataRole.UserRole, entry.path)
            item.setData(Qt.ItemDataRole.UserRole + 1, (entry.display_name, detail))
            self.recent_list.addItem(item)

        has_any = self.recent_list.count() > 0
        self.recent_list.setVisible(has_any)
        self.empty_hint.setVisible(not has_any)

        if has_any:
            self.recent_list.setCurrentItem(self.recent_list.item(0))

        if not shown or self.job_runner is None:
            return

        steps = [
            job_step(f"Check recent project {entry.path}", _check_path_exists, entry.path)
            for entry in shown
        ]
        self.job_runner.submit(
            "Check recent projects exist",
            steps=steps,
            lane="interactive",
            slot_key=_WELCOME_RECENT_SLOT,
            quiet=True,
            on_step=lambda payload, _idx: self._on_recent_checked(payload[0], payload[1]),
        )

    def _find_item_by_path(self, path: str) -> Optional[QListWidgetItem]:
        for i in range(self.recent_list.count()):
            item = self.recent_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == path:
                return item
        return None

    def _on_recent_checked(self, path: str, exists: bool) -> None:
        item = self._find_item_by_path(path)
        if item is None:
            return

        meta = item.data(Qt.ItemDataRole.UserRole + 1)
        if meta:
            display_name, detail = meta
            suffix = "" if exists else "   (missing)"
            item.setText(f"{display_name}{suffix}\n{detail}")

        if not exists:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setForeground(Qt.GlobalColor.gray)

            # If the currently selected item was just disabled, move selection
            # to the first selectable (enabled) row.
            if self.recent_list.currentItem() is item:
                first_selectable = None
                for i in range(self.recent_list.count()):
                    candidate = self.recent_list.item(i)
                    if candidate.flags() & Qt.ItemFlag.ItemIsEnabled:
                        first_selectable = candidate
                        break
                self.recent_list.setCurrentItem(first_selectable)
        else:
            # If current selection is disabled or None, select this newly verified item.
            curr = self.recent_list.currentItem()
            if curr is None or not (curr.flags() & Qt.ItemFlag.ItemIsEnabled):
                self.recent_list.setCurrentItem(item)

    # -- events -----------------------------------------------------------

    def _emit_selected(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            self.open_recent_requested.emit(path)

    def _dropped_path(self, event) -> str:
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            if os.path.isdir(local) or local.lower().endswith(_PROJECT_SUFFIX):
                return local
        return ""

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and self._dropped_path(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        path = self._dropped_path(event)
        if path:
            event.acceptProposedAction()
            self.path_dropped.emit(path)
