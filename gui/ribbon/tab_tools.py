# gui/ribbon/tab_tools.py
"""
Tools ribbon tab: helpers that work on any open graph rather than on one analysis.

Groups: Cursors (the hover Cursor, `C`; Highlight, `H`).
"""

from PySide6.QtWidgets import QHBoxLayout, QWidget

from gui.ribbon.cursor_box import CursorBox
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout


class TabTools(QWidget):
    """Graph tools: the Cursor."""

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
        layout.addWidget(cursors)

        build_tab_layout(self, layout, "tools")
