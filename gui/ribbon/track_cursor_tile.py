# gui/ribbon/track_cursor_tile.py
"""
The Tools tab's Track tile: the Track cursor on/off, beside the Cursor tile and
the same size and colours (`gui/ribbon/tool_tile.py`).

Its small buttons sit on the Cursor tile's places: Track cursor Settings (gear)
on the left, the Track cursor highlight (flashlight) in the middle, the Track
cursor pin on the right.
"""

from gui.ribbon.tool_tile import ChipPosition, ToolTile


class TrackCursorTile(ToolTile):
    """Track cursor on/off for every curve graph; `btn_track_cursor_settings`,
    `btn_track_cursor_highlight` and `btn_track_cursor_pin` sit along its bottom."""

    def __init__(self, parent=None):
        super().__init__(
            "track", "Track",
            "Track cursor on/off: a vertical line on every curve graph and a Track table with "
            "each curve's value on its X, highest first; drag the line to move it "
            "(shortcut: T while a graph has focus).",
            parent)
        self.btn_track_cursor_settings = self.add_chip(
            ChipPosition.LEFT, "gear",
            "Track cursor Settings…: choose which columns the Track table shows and in "
            "what order, apart from the Cursor Box (saved for every project)", checkable=False)
        # The highlight and the pin only mean something while the Track cursor is on;
        # neither has a shortcut (`H` is the Highlight's).
        self.btn_track_cursor_highlight = self.add_chip(
            ChipPosition.MIDDLE, "flashlight",
            "Highlight: mark where the Track cursor line crosses each curve and dim the curves",
            checkable=True, only_while_on=True)
        self.btn_track_cursor_pin = self.add_chip(
            ChipPosition.RIGHT, "pin",
            "Pin: the Track cursor line moves only when you drag it; off, the line "
            "follows the mouse over the graph and stays where it is when the mouse leaves",
            checkable=True, only_while_on=True)
        self.setObjectName("TrackCursorButton")  # object names: targets of the help figure annotations
        self.btn_track_cursor_settings.setObjectName("TrackCursorSettingsButton")
        self.btn_track_cursor_highlight.setObjectName("TrackCursorHighlightButton")
        self.btn_track_cursor_pin.setObjectName("TrackCursorPinButton")
