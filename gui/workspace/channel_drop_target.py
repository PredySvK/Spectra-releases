# =====================================================================
# FILE: gui/workspace/channel_drop_target.py
# =====================================================================
"""
Accepts an internal channel drag and forwards its payload upward.

Mixed into GraphDock and SpectrogramDock. Both used to carry a
byte-for-byte copy of dragEnterEvent/dropEvent plus the MIME type name --
a contract shared across two files, so a typo in one copy of
"application/x-nvh-channels" would have made a drop silently do nothing
with nothing to flag it. One home now owns the name and the payload shape.

A plain mixin (like BandRmsCursorsMixin): the concrete dock is the
QWidget, so it must come before QWidget in the bases and it is responsible
for calling setAcceptDrops(True).
"""

import json

from PySide6.QtCore import Qt, Signal


CHANNEL_DRAG_MIME = "application/x-nvh-channels"
# A Selection dragged out of the Explorer's Selections tab: its name, which the
# drop target hands up to be expanded into channels once (#465).
SELECTION_DRAG_MIME = "application/x-nvh-selection"


class ChannelDropTargetMixin:
    # Broadcasts the dropped descriptor list to external controllers,
    # decoupling the dock from the routing logic in Workspace.
    sig_channels_dropped = Signal(list)
    sig_selection_dropped = Signal(str)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasFormat(CHANNEL_DRAG_MIME) or mime.hasFormat(SELECTION_DRAG_MIME):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Extracts JSON payload and routes it up to the Workspace."""
        if event.mimeData().hasFormat(SELECTION_DRAG_MIME):
            self.sig_selection_dropped.emit(
                bytes(event.mimeData().data(SELECTION_DRAG_MIME)).decode("utf-8"))
            event.acceptProposedAction()
            return
        try:
            raw_descriptors = json.loads(
                bytes(event.mimeData().data(CHANNEL_DRAG_MIME)).decode("utf-8")
            )
            if raw_descriptors:
                self.sig_channels_dropped.emit(raw_descriptors)
                event.acceptProposedAction()
            else:
                event.ignore()
        except Exception:
            event.ignore()
