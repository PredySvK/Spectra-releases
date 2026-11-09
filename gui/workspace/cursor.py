# =====================================================================
# FILE: gui/workspace/cursor.py
# =====================================================================
"""
Shared hover gate and Cursor Box for GraphDock and SpectrogramDock
(CONTEXT.md "Cursor", "Cursor Box", "Highlight").

What is picked, whether the box is shown or kept in place, where the
spectrogram crosshair sits and which curve the Highlight emphasises are decided
in view_models.cursor.CursorState; this module reads the mouse and the
ViewBoxes into plain numbers, installs the single SignalProxy and viewport
Leave filter, and applies the resulting CursorView to the widgets. Another
tool that follows the mouse adds its own step to the same gate
(`_add_hover_step`) instead of a second SignalProxy.

Runs synchronously on the GUI thread: the hit test only touches a pixel-wide
window of each curve, mouse moves arrive rate-limited (~60 Hz).
"""

from typing import Dict, Iterable, List, Mapping, Optional, Protocol, Tuple

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication

from core.axis_projections import AxisScreenRule
from core.cursor_config import CursorConfig
from gui.workspace.graph_overlay import GraphOverlay
from gui.workspace.plot_area import GRAPH_TOKENS
from orchestration.trace_filter import resolve_curve_metadata_sources
from view_models.cursor import (
    AxisTransform,
    CursorState,
    CursorView,
    read_curve_metadata,
    resolve_box_position,
)
from view_models.plot import Trace

CURSOR_RADIUS_PX = 10
CURSOR_MOUSE_RATE_HZ = 60

class HoverStep(Protocol):
    """One more tool's step on the hover gate, run on every mouse move after the Cursor's own."""

    def __call__(self, vb: pg.ViewBox, scene_pos: QPointF, *, in_bounds: bool, button_pressed: bool) -> None: ...


def _axis_transform(vb: pg.ViewBox, x_rule: AxisScreenRule, y_rule: AxisScreenRule) -> AxisTransform:
    (x0, x1), (y0, y1) = vb.viewRange()
    w, h = vb.width(), vb.height()
    x_span, y_span = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    x_scale, y_scale = w / x_span, -h / y_span
    return AxisTransform(x_scale, -x0 * x_scale, y_scale, -y1 * y_scale,
                         x_rule=x_rule, y_rule=y_rule)


class CursorMixin:
    """Shared hover gate and Cursor Box, mixed into GraphDock (and via SpectrogramCursorMixin into SpectrogramDock)."""

    # The `C` and `P` shortcuts emit WorkspaceDock.sig_cursor_toggle_requested /
    # sig_cursor_pin_requested; the Settings store owns the state
    # (Workspace.toggle_tool_switch, ADR §1.290). `T` likewise emits
    # sig_track_cursor_toggle_requested from every dock, a spectrogram too,
    # though only a curve graph draws the Track cursor.

    def _init_cursor(self, *, with_crosshair: bool = False) -> None:
        """Called at the end of init_ui, once plot_widget exists."""
        self._cursor_state = CursorState()
        self._hover_steps: List[HoverStep] = []
        vb = self.plot_widget.plotItem.vb
        # Takes the left mouse button (to be dragged) only while pinned.
        self._cursor_box = GraphOverlay(
            vb,
            z_value=1000,
            anchor=(0, 0),
            color=GRAPH_TOKENS.cursor_box_line,
            fill=pg.mkBrush(*GRAPH_TOKENS.cursor_box_fill),
        )

        if with_crosshair:
            pen = pg.mkPen(color=GRAPH_TOKENS.cursor_box_line, width=1, style=Qt.PenStyle.DashLine)
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
        else:
            self._crosshair_v = None
            self._crosshair_h = None

        self._cursor_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved,
            rateLimit=CURSOR_MOUSE_RATE_HZ,
            slot=lambda args: self.update_cursor_at(args[0]),
        )
        self._install_hover_viewport_filter()
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.plot_widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        shortcut = QShortcut(QKeySequence("C"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.sig_cursor_toggle_requested)
        pin_shortcut = QShortcut(QKeySequence("P"), self)
        pin_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        pin_shortcut.activated.connect(self.sig_cursor_pin_requested)
        track_shortcut = QShortcut(QKeySequence("T"), self)
        track_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        track_shortcut.activated.connect(self.sig_track_cursor_toggle_requested)

    def _add_hover_step(self, step: HoverStep) -> None:
        """Run ``step`` on every mouse move of this gate, after the Cursor's own."""
        self._hover_steps.append(step)

    def _install_hover_viewport_filter(self) -> None:
        viewport = self.plot_widget.viewport()
        viewport.setMouseTracking(True)
        viewport.installEventFilter(self)

    def _cursor_enabled(self) -> bool:
        return bool(getattr(self.app_context, "cursor_enabled", False))

    def _cursor_pinned(self) -> bool:
        return bool(getattr(self.app_context, "cursor_pinned", False))

    def _highlight_enabled(self) -> bool:
        return bool(getattr(self.app_context, "highlight_enabled", False))

    def _cursor_config(self) -> CursorConfig:
        return getattr(self.app_context, "cursor_config", None) or CursorConfig()

    def cursor_box_visible(self) -> bool:
        return self._cursor_box.isVisible()

    def crosshair_visible(self) -> bool:
        return (
            self._crosshair_v is not None
            and self._crosshair_v.isVisible()
            and self._crosshair_h.isVisible()
        )

    def hide_cursor_box(self) -> None:
        self._apply_cursor_view(self._cursor_state.hide())

    def _clear_cursor(self) -> None:
        self._apply_cursor_view(self._cursor_state.clear())

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Leave and obj is self.plot_widget.viewport():
            self._apply_cursor_view(self._cursor_state.leave(
                cursor_enabled=self._cursor_enabled(),
                pinned=self._cursor_pinned(),
            ))
        return super().eventFilter(obj, event)

    def _cursor_transforms(self) -> Dict[str, AxisTransform]:
        x_rule, y_rule = self.x_screen_rule(), self.y_screen_rule()
        transforms = {"primary": _axis_transform(self.plot_widget.plotItem.vb, x_rule, y_rule)}
        secondary = self.secondary_axis.view_box
        if secondary is not None:
            # A secondary curve follows the primary axis into log X and log Y
            # (§1.276), so the Cursor reads both with the same rules.
            transforms["secondary"] = _axis_transform(secondary, x_rule, y_rule)
        return transforms

    def _read_trace_metadata(
        self, trace: Trace, fields: Iterable[str],
    ) -> Mapping[str, Tuple[str, str]]:
        sources = resolve_curve_metadata_sources(
            getattr(self.app_context, "project_session", None), getattr(self.app_context, "pool", None))
        if sources is None:
            return {}
        schema, identity_context = sources
        return read_curve_metadata(
            trace, fields, schema, identity_context.sources_by_path, identity_context.result_set_labels,
        )

    def update_cursor_at(self, scene_pos: QPointF) -> None:
        """Show, move or hide the Cursor Box (and Highlight / crosshair) for a mouse at ``scene_pos``."""
        try:
            vb = self.plot_widget.plotItem.vb
            if vb is None:
                return
            bounding_rect = vb.sceneBoundingRect()
        except RuntimeError:
            return
        in_bounds = bounding_rect.contains(scene_pos)
        button_pressed = QApplication.mouseButtons() != Qt.MouseButton.NoButton
        mouse_px: Optional[Tuple[float, float]] = None
        if in_bounds:
            mouse = vb.mapFromScene(scene_pos)
            mouse_px = (mouse.x(), mouse.y())
        view = self._hover_cursor_state(vb, scene_pos, mouse_px, button_pressed=button_pressed)
        self._apply_cursor_view(view, mouse_px=mouse_px)
        for step in self._hover_steps:
            step(vb, scene_pos, in_bounds=in_bounds, button_pressed=button_pressed)

    def _hover_cursor_state(
        self,
        vb: pg.ViewBox,
        scene_pos: QPointF,
        mouse_px: Optional[Tuple[float, float]],
        *,
        button_pressed: bool,
    ) -> CursorView:
        model = self.curves.model
        cursor_enabled = self._cursor_enabled()
        pinned = self._cursor_pinned()
        highlight_enabled = self._highlight_enabled()
        if model is None:
            return self._cursor_state.hover_graph(
                (), {}, None,
                cursor_enabled=cursor_enabled,
                pinned=pinned,
                highlight_enabled=highlight_enabled,
                button_pressed=button_pressed,
            )
        transforms: Dict[str, AxisTransform] = {}
        if mouse_px is not None and not button_pressed and (cursor_enabled or highlight_enabled):
            transforms = self._cursor_transforms()
        return self._cursor_state.hover_graph(
            self.visible_traces(),
            transforms,
            mouse_px,
            radius_px=CURSOR_RADIUS_PX,
            cursor_enabled=cursor_enabled,
            pinned=pinned,
            highlight_enabled=highlight_enabled,
            button_pressed=button_pressed,
            config=self._cursor_config(),
            x_unit=self._x_axis.unit,
            x_quantity=model.x_domain,
            two_axes=self.secondary_axis.is_active,
            prefs=self._unit_preferences(),
            metadata_reader=self._read_trace_metadata,
        )

    def refresh_cursor_box(self) -> None:
        self._apply_cursor_view(self._refresh_cursor_state())

    def _refresh_cursor_state(self) -> CursorView:
        model = self.curves.model
        if model is None:
            return self._cursor_state.hide()
        return self._cursor_state.refresh_graph(
            self.visible_traces(),
            x_display=self._x_axis.scale,
            cursor_enabled=self._cursor_enabled(),
            config=self._cursor_config(),
            x_unit=self._x_axis.unit,
            x_quantity=model.x_domain,
            two_axes=self.secondary_axis.is_active,
            prefs=self._unit_preferences(),
            metadata_reader=self._read_trace_metadata,
        )

    def _apply_cursor_view(
        self,
        view: CursorView,
        mouse_px: Optional[Tuple[float, float]] = None,
    ) -> None:
        self._cursor_box.set_draggable(self._cursor_pinned())
        if self._crosshair_v is not None:
            if view.crosshair is not None:
                self._crosshair_v.setPos(view.crosshair[0])
                self._crosshair_h.setPos(view.crosshair[1])
                self._crosshair_v.show()
                self._crosshair_h.show()
            else:
                self._crosshair_v.hide()
                self._crosshair_h.hide()
        if view.box_visible:
            self._cursor_box.setText("\n".join(f"{label}: {text}" for label, text in view.lines))
            if view.move_box and mouse_px is not None:
                vb = self.plot_widget.plotItem.vb
                rect = self._cursor_box.boundingRect()
                x, y = resolve_box_position(
                    (rect.width(), rect.height()), mouse_px, (0, 0, vb.width(), vb.height()),
                )
                self._cursor_box.setPos(x, y)
            self._cursor_box.show()
        else:
            self._cursor_box.hide()
        if hasattr(self, "_set_highlighted_trace"):
            self._set_highlighted_trace(view.highlighted_trace)


class SpectrogramCursorMixin(CursorMixin):
    """Hover crosshair and Cursor Box on SpectrogramDock, sharing CursorMixin's hover gate."""

    def _init_cursor(self) -> None:
        super()._init_cursor(with_crosshair=True)

    def _hover_cursor_state(
        self,
        vb: pg.ViewBox,
        scene_pos: QPointF,
        mouse_px: Optional[Tuple[float, float]],
        *,
        button_pressed: bool,
    ) -> CursorView:
        pos: Optional[Tuple[float, float]] = None
        if mouse_px is not None and not button_pressed:
            mouse_view = vb.mapSceneToView(scene_pos)
            pos = (float(mouse_view.x()), float(mouse_view.y()))
        return self._cursor_state.hover_spectrogram(
            self.drawn_spectrogram,
            pos,
            cursor_enabled=self._cursor_enabled(),
            pinned=self._cursor_pinned(),
            button_pressed=button_pressed,
            config=self._cursor_config(),
            prefs=self._unit_preferences(),
        )

    def _refresh_cursor_state(self) -> CursorView:
        return self._cursor_state.refresh_spectrogram(
            self.drawn_spectrogram,
            cursor_enabled=self._cursor_enabled(),
            config=self._cursor_config(),
            prefs=self._unit_preferences(),
        )
