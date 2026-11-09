# gui/ribbon/tab_tools.py
"""
Tools ribbon tab: helpers that work on any open graph rather than on one analysis.

Groups: Cursors (the hover Cursor, `C`; Highlight, `H`; the Track cursor, `T`).
"""

from PySide6.QtWidgets import QHBoxLayout, QWidget

from gui.ribbon.cursor_box import CursorBox
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout
from gui.ribbon.track_cursor_tile import TrackCursorTile


class TabTools(QWidget):
    """Graph tools: the Cursor and the Track cursor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(8)

        box = CursorBox()
        self.btn_cursor = box
        self.btn_cursor_settings = box.btn_cursor_settings
        self.btn_highlight = box.btn_highlight
        self.btn_cursor_pin = box.btn_cursor_pin
        cursors = RibbonGroup("Cursors")
        cursors.add(box)
        self.btn_track_cursor = TrackCursorTile()
        self.btn_track_cursor_settings = self.btn_track_cursor.btn_track_cursor_settings
        self.btn_track_cursor_highlight = self.btn_track_cursor.btn_track_cursor_highlight
        self.btn_track_cursor_pin = self.btn_track_cursor.btn_track_cursor_pin
        cursors.add(self.btn_track_cursor)
        layout.addWidget(cursors)

        build_tab_layout(self, layout, "tools")
