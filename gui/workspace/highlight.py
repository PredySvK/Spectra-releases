"""
The Highlight on GraphDock: with it on, the curve under the mouse is drawn thicker and
every other curve is dimmed (CONTEXT.md "Highlight"). Independent of the Cursor.

Which curve is decided in view_models.cursor (the Cursor's nearest-curve rule); this
mixin only swaps pens on the drawn items. Pens are touched only when the highlighted
curve changes, not on every mouse move; leave / off / a pressed button / a redraw
puts the original pens back.

Runs synchronously on the GUI thread (the pen swap measured in ADR §1.150).
"""

from typing import Any, List, Optional, Tuple

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from gui.workspace.cursor import CURSOR_MOUSE_RATE_HZ, CURSOR_RADIUS_PX
from view_models.cursor import HIGHLIGHT_DIM_ALPHA, resolve_highlighted_trace
from view_models.plot import Trace

HIGHLIGHT_EXTRA_WIDTH = 2


def _set_pen(item: Any, pen: Any, visible: bool = True, on_top: bool = False) -> None:
    # PlotDataItem.setPen re-sets the curve data, which re-runs the ViewBox auto-range with
    # the new pen's padding and shifts the graph (#579); the inner curve only repaints. Hiding
    # the inner curve (not the item) keeps the item's bounds in the auto-range.
    item.curve.setPen(pen)
    item.curve.setVisible(visible)
    # Faded curves are opaque (colour mix), so a later one would cut through the highlighted one.
    item.setZValue(1 if on_top else 0)


class HighlightMixin:
    """Hover Highlight, mixed into GraphDock."""

    # The `H` shortcut asks the app to flip the one global switch; the ribbon
    # button owns the state (Workspace.toggle_highlight).
    sig_highlight_toggle_requested = Signal()

    def _init_highlight(self) -> None:
        """Called at the end of GraphDock.init_ui, after _init_cursor."""
        self._highlight_items: List[Tuple[Trace, Any, Any]] = []  # (trace, item, original pen)
        self._highlighted: Optional[Trace] = None
        self._highlight_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved, rateLimit=CURSOR_MOUSE_RATE_HZ,
            slot=lambda args: self.update_highlight_at(args[0]))
        shortcut = QShortcut(QKeySequence("H"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.sig_highlight_toggle_requested)

    def remember_highlight_item(self, trace: Trace, item: Any, pen: Any) -> None:
        self._highlight_items.append((trace, item, pen))
        if self._highlighted is not None:  # a curve appended while highlighting joins in
            _set_pen(item, *self._highlight_look(trace, pen, self._highlighted))

    def forget_highlight_items(self) -> None:
        """The items were just destroyed by a redraw -- nothing left to restore."""
        self._highlight_items = []
        self._highlighted = None

    def highlighted_trace(self) -> Optional[Trace]:
        return self._highlighted

    def clear_highlight(self) -> None:
        """Every curve back to its own pen."""
        if self._highlighted is None:
            return
        self._highlighted = None
        for _, item, pen in self._highlight_items:
            _set_pen(item, pen)

    def _highlight_look(self, trace: Trace, pen: Any, target: Trace) -> Tuple[Any, bool, bool]:
        """(pen, visible, on top) for a curve while ``target`` is highlighted.

        Other curves fade by mixing their colour toward the plot background, not by pen alpha:
        the OpenGL viewport (main.py) ignores pen alpha. At 0 % they are hidden outright.
        """
        changed = pg.mkPen(pen)
        if trace is target:
            changed.setWidthF(pen.widthF() + HIGHLIGHT_EXTRA_WIDTH)
            return changed, True, True
        percent = getattr(self.app_context, "highlight_other_opacity", None)
        keep = HIGHLIGHT_DIM_ALPHA if percent is None else percent / 100
        color, bg = changed.color(), self.plot_widget.backgroundBrush().color()
        changed.setColor(QColor(*(round(b + (c - b) * keep) for c, b in (
            (color.red(), bg.red()), (color.green(), bg.green()), (color.blue(), bg.blue())))))
        return changed, keep > 0, False

    def _apply_highlight(self, target: Trace) -> None:
        self._highlighted = target
        for trace, item, pen in self._highlight_items:
            _set_pen(item, *self._highlight_look(trace, pen, target))

    def eventFilter(self, obj, event):
        # The Cursor installed the filter on the viewport; this only adds the restore.
        if event.type() == QEvent.Type.Leave and obj is self.plot_widget.viewport():
            self.clear_highlight()
        return super().eventFilter(obj, event)

    def update_highlight_at(self, scene_pos: QPointF) -> None:
        """Highlight the curve under a mouse at ``scene_pos``; restore when none."""
        vb = self.plot_widget.plotItem.vb
        if (not getattr(self.app_context, "highlight_enabled", False)
                or self.curves.model is None
                or QApplication.mouseButtons() != Qt.MouseButton.NoButton
                or not vb.sceneBoundingRect().contains(scene_pos)):
            self.clear_highlight()
            return
        mouse = vb.mapFromScene(scene_pos)
        log_y = bool(self.plot_widget.plotItem.ctrl.logYCheck.isChecked())
        target = resolve_highlighted_trace(
            self.visible_traces(), self._cursor_transforms(log_y),
            (mouse.x(), mouse.y()), CURSOR_RADIUS_PX)
        if target is None:
            self.clear_highlight()
        elif target is not self._highlighted:
            self._apply_highlight(target)
