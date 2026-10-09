# =====================================================================
# FILE: gui/workspace/cursor.py
# =====================================================================
"""
The Cursor on GraphDock: hover a curve graph and a frameless Cursor Box shows the
nearest real sample of the nearest visible curve (CONTEXT.md "Cursor").

What is picked and what the box says is decided in view_models.cursor; this mixin
only reads the mouse and the ViewBoxes into plain numbers, and draws the box. The
box is a pg.TextItem parented to the ViewBox (pixel coordinates, like the Band RMS
label), so it never takes part in auto-range and survives a replot. On/off is an
app-level flag (AppContext.cursor_enabled) shared by every graph.

Runs synchronously on the GUI thread: the hit test only touches a pixel-wide
window of each curve, mouse moves arrive rate-limited (~60 Hz).
"""

from typing import Dict, Optional

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from core.axis_projections import X_AXIS_NATIVE, resolve_x_axis_display
from core.cursor_config import CursorConfig
from orchestration.trace_filter import build_identity_context
from view_models.cursor import (
    AxisTransform, build_cursor_box_lines, read_curve_metadata, resolve_box_position,
    resolve_cursor_point, resolve_spectrogram_pixel,
)

CURSOR_RADIUS_PX = 10
CURSOR_MOUSE_RATE_HZ = 60


def _axis_transform(vb: pg.ViewBox, x_display: float, log_y: bool) -> AxisTransform:
    (x0, x1), (y0, y1) = vb.viewRange()
    w, h = vb.width(), vb.height()
    x_span, y_span = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    x_scale, y_scale = w / x_span, -h / y_span
    return AxisTransform(x_scale, -x0 * x_scale, y_scale, -y1 * y_scale,
                         x_display=x_display, log_y=log_y)


class _CursorBox(pg.TextItem):
    """The Cursor Box; takes the left mouse button (to be dragged) only while pinned."""

    def informViewBoundsChanged(self):
        # The box is an overlay, never data: every setPos would queue a ViewBox auto-range,
        # which with Highlight on re-pads the range by the thicker pen and shakes the graph (#579).
        pass

    def mouseDragEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        parent = self.parentItem()
        delta = parent.mapFromScene(ev.scenePos()) - parent.mapFromScene(ev.lastScenePos())
        self.setPos(self.pos() + delta)


def _set_box_draggable(box: pg.TextItem, pinned: bool) -> None:
    box.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if pinned else Qt.MouseButton.NoButton)


class CursorMixin:
    """Hover Cursor Box, mixed into GraphDock."""

    # The `C` shortcut asks the app to flip the one global switch; the ribbon
    # button owns the state (Workspace.toggle_cursor).
    sig_cursor_toggle_requested = Signal()
    sig_cursor_pin_requested = Signal()

    def _init_cursor(self) -> None:
        """Called at the end of GraphDock.init_ui, once plot_widget exists."""
        vb = self.plot_widget.plotItem.vb
        self._cursor_box = _CursorBox(anchor=(0, 0), color="#e8edf2", fill=pg.mkBrush(18, 24, 31, 230))
        self._cursor_box.setParentItem(vb)
        _set_box_draggable(self._cursor_box, False)
        self._cursor_box.setZValue(1000)
        self._cursor_box.hide()
        self._cursor_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved, rateLimit=CURSOR_MOUSE_RATE_HZ,
            slot=lambda args: self.update_cursor_at(args[0]))
        self.plot_widget.viewport().installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.plot_widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        shortcut = QShortcut(QKeySequence("C"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.sig_cursor_toggle_requested)
        pin_shortcut = QShortcut(QKeySequence("P"), self)
        pin_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        pin_shortcut.activated.connect(self.sig_cursor_pin_requested)

    def cursor_box_visible(self) -> bool:
        return self._cursor_box.isVisible()

    def hide_cursor_box(self) -> None:
        self._cursor_box.hide()

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Leave and obj is self.plot_widget.viewport()
                and not getattr(self.app_context, "cursor_pinned", False)):
            self.hide_cursor_box()
        return super().eventFilter(obj, event)

    def _cursor_transforms(self, log_y: bool) -> Dict[str, AxisTransform]:
        x_display = self._x_axis.scale
        transforms = {"primary": _axis_transform(self.plot_widget.plotItem.vb, x_display, log_y)}
        secondary = self.secondary_axis.view_box
        if secondary is not None:
            transforms["secondary"] = _axis_transform(secondary, x_display, log_y)
        return transforms

    def update_cursor_at(self, scene_pos: QPointF) -> None:
        """Show, move or hide the Cursor Box for a mouse at ``scene_pos``."""
        ctx = self.app_context
        vb = self.plot_widget.plotItem.vb
        pinned = bool(getattr(ctx, "cursor_pinned", False))
        _set_box_draggable(self._cursor_box, pinned)
        if not getattr(ctx, "cursor_enabled", False) or self.curves.model is None:
            self.hide_cursor_box()
            return
        if (QApplication.mouseButtons() != Qt.MouseButton.NoButton
                or not vb.sceneBoundingRect().contains(scene_pos)):
            if not pinned:
                self.hide_cursor_box()
            return
        mouse = vb.mapFromScene(scene_pos)
        mouse_px = (mouse.x(), mouse.y())
        # ponytail: log X axis is not handled (pixel X would be wrong); only log Y is.
        log_y = bool(self.plot_widget.plotItem.ctrl.logYCheck.isChecked())
        point = resolve_cursor_point(
            self.visible_traces(), self._cursor_transforms(log_y), mouse_px, CURSOR_RADIUS_PX)
        if point is None:
            if not pinned:
                self.hide_cursor_box()
            return
        config = getattr(ctx, "cursor_config", None) or CursorConfig()
        identity_context = build_identity_context(ctx.project_session)
        metadata = read_curve_metadata(
            point.trace, config.fields, ctx.pool.schema().master, identity_context.sources_by_path,
            identity_context.result_set_labels)
        lines = build_cursor_box_lines(
            point, config, x_unit=self._x_axis.unit, two_axes=self.secondary_axis.is_active,
            metadata=metadata)
        if not lines:
            if not pinned:
                self.hide_cursor_box()
            return
        self._cursor_box.setText("\n".join(f"{label}: {text}" for label, text in lines))
        if not (pinned and self._cursor_box.isVisible()):
            rect = self._cursor_box.boundingRect()
            x, y = resolve_box_position((rect.width(), rect.height()), mouse_px, (0, 0, vb.width(), vb.height()))
            self._cursor_box.setPos(x, y)
        self._cursor_box.show()


class SpectrogramCursorMixin:
    """Hover crosshair and Cursor Box, mixed into SpectrogramDock."""

    # The `C` shortcut asks the app to flip the one global switch; the ribbon
    # button owns the state (Workspace.toggle_cursor).
    sig_cursor_toggle_requested = Signal()
    sig_cursor_pin_requested = Signal()

    def _init_cursor(self) -> None:
        """Called at the end of SpectrogramDock.init_ui."""
        vb = self.plot_widget.plotItem.vb
        self._cursor_box = _CursorBox(anchor=(0, 0), color="#e8edf2", fill=pg.mkBrush(18, 24, 31, 230))
        self._cursor_box.setParentItem(vb)
        _set_box_draggable(self._cursor_box, False)
        self._cursor_box.setZValue(1000)
        self._cursor_box.hide()

        pen = pg.mkPen(color="#e8edf2", width=1, style=Qt.PenStyle.DashLine)
        self._crosshair_v = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        self._crosshair_h = pg.InfiniteLine(angle=0, movable=False, pen=pen)
        self._crosshair_v.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._crosshair_h.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._crosshair_v.setZValue(999)
        self._crosshair_h.setZValue(999)
        self.plot_widget.addItem(self._crosshair_v)
        self.plot_widget.addItem(self._crosshair_h)
        self._crosshair_v.hide()
        self._crosshair_h.hide()

        self._cursor_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved, rateLimit=CURSOR_MOUSE_RATE_HZ,
            slot=lambda args: self.update_cursor_at(args[0]))
        self.plot_widget.viewport().installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.plot_widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        shortcut = QShortcut(QKeySequence("C"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.sig_cursor_toggle_requested)
        pin_shortcut = QShortcut(QKeySequence("P"), self)
        pin_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        pin_shortcut.activated.connect(self.sig_cursor_pin_requested)

    def cursor_box_visible(self) -> bool:
        return self._cursor_box.isVisible()

    def crosshair_visible(self) -> bool:
        return self._crosshair_v.isVisible() and self._crosshair_h.isVisible()

    def hide_cursor_box(self) -> None:
        self._cursor_box.hide()
        self._crosshair_v.hide()
        self._crosshair_h.hide()

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Leave and obj is self.plot_widget.viewport()
                and not getattr(self.app_context, "cursor_pinned", False)):
            self.hide_cursor_box()
        return super().eventFilter(obj, event)

    def update_cursor_at(self, scene_pos: QPointF) -> None:
        """Show, move or hide the Cursor Box and crosshair for a mouse at ``scene_pos``."""
        ctx = self.app_context
        vb = self.plot_widget.plotItem.vb
        model = self.spectrogram.model
        pinned = bool(getattr(ctx, "cursor_pinned", False))
        _set_box_draggable(self._cursor_box, pinned)
        if not getattr(ctx, "cursor_enabled", False) or model is None:
            self.hide_cursor_box()
            return
        if (QApplication.mouseButtons() != Qt.MouseButton.NoButton
                or not vb.sceneBoundingRect().contains(scene_pos)):
            if not pinned:
                self.hide_cursor_box()
            return

        mouse_px = (vb.mapFromScene(scene_pos).x(), vb.mapFromScene(scene_pos).y())
        mouse_view = vb.mapSceneToView(scene_pos)
        x_view = float(mouse_view.x())
        y_view = float(mouse_view.y())

        x_axis_unit = ctx.unit_preferences().x_axis_unit if ctx and hasattr(ctx, "unit_preferences") else X_AXIS_NATIVE
        frequency_axis = resolve_x_axis_display("frequency", x_axis_unit)
        bottom_axis = resolve_x_axis_display(model.z_quantity, x_axis_unit)
        x_unit = bottom_axis.unit if bottom_axis.scale != 1.0 else model.z_unit
        y_unit = frequency_axis.unit

        point = resolve_spectrogram_pixel(
            model,
            x=x_view,
            y=y_view,
            x_scale=bottom_axis.scale,
            y_scale=frequency_axis.scale,
            x_unit=x_unit,
            y_unit=y_unit,
        )
        if point is None:
            if not pinned:
                self.hide_cursor_box()
            return

        self._crosshair_v.setPos(x_view)
        self._crosshair_h.setPos(y_view)
        self._crosshair_v.show()
        self._crosshair_h.show()

        config = getattr(ctx, "cursor_config", None) or CursorConfig()
        lines = build_cursor_box_lines(point, config)
        if not lines:
            if not pinned:
                self._cursor_box.hide()
            return
        self._cursor_box.setText("\n".join(f"{label}: {text}" for label, text in lines))
        if not (pinned and self._cursor_box.isVisible()):
            rect = self._cursor_box.boundingRect()
            bx, by = resolve_box_position((rect.width(), rect.height()), mouse_px, (0, 0, vb.width(), vb.height()))
            self._cursor_box.setPos(bx, by)
        self._cursor_box.show()
