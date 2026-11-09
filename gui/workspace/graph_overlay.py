# =====================================================================
# FILE: gui/workspace/graph_overlay.py
# =====================================================================
"""
A text overlay laid over a graph's ViewBox that the user may drag with the mouse.

Positioned in ViewBox pixels (a child of the ViewBox, not a data item), so it
never moves the axis range: a move does not queue a ViewBox auto-range, which
with Highlight on would re-pad the range by the thicker pen and shake the graph
(#579). The Cursor Box is one use; any other box over a graph takes the same base.
"""

from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt


class GraphOverlay(pg.TextItem):
    """A hidden text box over ``view_box``; takes the left mouse button only while draggable.

    The ``pg.TextItem`` keyword arguments (anchor, color, fill, ...) pass through.
    Starts hidden and not draggable; the owner places it with ``setPos`` in ViewBox
    pixels and switches dragging with ``set_draggable``.
    """

    def __init__(self, view_box: pg.ViewBox, *, z_value: float = 1000, **text_item_kwargs: Any) -> None:
        super().__init__(**text_item_kwargs)
        self.setParentItem(view_box)
        self.set_draggable(False)
        self.setZValue(z_value)
        self.hide()

    def set_draggable(self, draggable: bool) -> None:
        """Take the left mouse button (to be dragged) or let every click through to the graph."""
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if draggable else Qt.MouseButton.NoButton)

    def informViewBoundsChanged(self):
        # An overlay is never data: every setPos would queue a ViewBox auto-range (#579).
        pass

    def mouseDragEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        parent = self.parentItem()
        delta = parent.mapFromScene(ev.scenePos()) - parent.mapFromScene(ev.lastScenePos())
        self.setPos(self.pos() + delta)
