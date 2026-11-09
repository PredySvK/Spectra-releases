# gui/ribbon/cursor_box.py
"""
The Tools tab's Cursor tile: Cursor on/off, with Cursor Settings (gear), Highlight
(flashlight) and Pin as its small buttons on the left, middle and right place.

Exposes the same `btn_*` names the Tools tab always had, so the workspace binds
them unchanged.
"""

from gui.ribbon.tool_tile import ChipPosition, ToolTile


class CursorBox(ToolTile):
    """Cursor on/off; `btn_cursor_settings`, `btn_highlight` and `btn_cursor_pin` sit along its bottom."""

    def __init__(self, parent=None):
        super().__init__(
            "cursor-arrow", "Cursor",
            "Cursor on/off: hover a curve graph to read the nearest sample of the nearest curve "
            "in a box next to the mouse (shortcut: C while a graph has focus).\n"
            "Bottom row: Settings, Highlight, Pin.",
            parent)
        self.btn_cursor_settings = self.add_chip(
            ChipPosition.LEFT, "gear",
            "Cursor Settings…: choose which fields the Cursor Box shows and in "
            "what order (saved for every project)", checkable=False)
        self.btn_highlight = self.add_chip(
            ChipPosition.MIDDLE, "flashlight",
            "Highlight: emphasise the curve under the mouse and dim the "
            "others (shortcut: H while a graph has focus)", checkable=True)
        # Pin only means something while the Cursor is on.
        self.btn_cursor_pin = self.add_chip(
            ChipPosition.RIGHT, "pin",
            "Pin: keep the Cursor Box where it is while its content follows the "
            "mouse; drag the box to move it (shortcut: P while a graph has focus)",
            checkable=True, only_while_on=True)
        self.setObjectName("CursorButton")  # object names: targets of the help figure annotations
        self.btn_cursor_settings.setObjectName("CursorSettingsButton")
        self.btn_highlight.setObjectName("HighlightButton")
        self.btn_cursor_pin.setObjectName("CursorPinButton")
