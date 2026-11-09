"""
The Highlight on GraphDock: with it on, the curve under the mouse is drawn thicker and
every other curve is dimmed (CONTEXT.md "Highlight"); the legend rows follow -- a thicker
sample for that curve, the other rows' sample and text dimmed alike. Independent of the Cursor.

Which curve is decided in view_models.cursor.CursorState and delivered through the shared
hover gate in gui.workspace.cursor; this mixin only swaps pens on the drawn items and
legend rows. Pens are touched only when the highlighted curve changes, not on every mouse
move; leave / off / a pressed button / a redraw puts the original pens back.

The same pen work dims the curves for the Track cursor highlight: each curve's look follows
two inputs, the Highlight's curve (or None) and whether the Track cursor highlight is
showing (TrackCursorMixin reports it). Highlighted curve -> thicker, own colour, on top;
every other curve while either is active -> faded; neither -> own pen. The legend follows
the Highlight alone. Pens are touched only when that pair changes.

Runs synchronously on the GUI thread (the pen swap measured in ADR §1.150).
"""

from typing import Any, Dict, List, Optional, Tuple

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut

from gui.workspace.plot_area import GRAPH_TOKENS
from view_models.cursor import HIGHLIGHT_DIM_ALPHA
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


def _faded(color: QColor, keep: float) -> QColor:
    """``color`` mixed toward the plot background, ``keep`` of it left."""
    bg = QColor(GRAPH_TOKENS.background)
    return QColor(*(round(b + (c - b) * keep) for c, b in (
        (color.red(), bg.red()), (color.green(), bg.green()), (color.blue(), bg.blue()))))


class HighlightSample(pg.ItemSample):
    """Legend sample that draws the Highlight's look of its curve while one is set.

    The plain sample paints from the curve item's own pen, which the Highlight leaves
    alone (setting it shifts the graph, #579), so the look is handed over here instead.
    """

    def __init__(self, item: Any) -> None:
        super().__init__(item)
        self.highlight_look: Optional[Tuple[Any, bool]] = None  # (pen, visible); None = own

    def paint(self, p, *args):
        if self.highlight_look is None or not self.item.isVisible():
            return super().paint(p, *args)
        pen, visible = self.highlight_look
        if visible:  # hidden still keeps its place in the legend
            p.setRenderHint(p.RenderHint.Antialiasing)
            p.setPen(pen)
            p.drawLine(0, 11, 20, 11)


class HighlightMixin:
    """Hover Highlight pen and legend styling, mixed into GraphDock."""

    # The `H` shortcut emits WorkspaceDock.sig_highlight_toggle_requested; the
    # Settings store owns the state (Workspace.toggle_tool_switch, ADR §1.290).

    def _init_highlight(self) -> None:
        """Called at the end of GraphDock.init_ui, after _init_cursor."""
        self._highlight_items: List[Tuple[Trace, Any, Any]] = []  # (trace, item, original pen)
        self._highlighted: Optional[Trace] = None
        # The Track cursor highlight is showing: every curve but the Highlight's is dimmed.
        self._track_dimming = False
        # A Settings window's Auto apply preview of the other curves' opacity (%), shown instead of the saved one.
        self._highlight_preview: Optional[int] = None
        shortcut = QShortcut(QKeySequence("H"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.sig_highlight_toggle_requested)

    def remember_highlight_item(self, trace: Trace, item: Any, pen: Any) -> None:
        self._highlight_items.append((trace, item, pen))
        # A clipped / downsampled PlotDataItem re-sets its inner curve's pen from its own on
        # every X range change (updateItems: Auto range, pan, zoom), which drops the look.
        item.curve.sigPlotChanged.connect(
            lambda curve, trace=trace, pen=pen: self._keep_curve_look(curve, trace, pen))
        if self._highlighted is not None or self._track_dimming:  # a curve appended meanwhile joins in
            _set_pen(item, *self._curve_look(trace, pen))
        if self._highlighted is not None:
            self._paint_legend(self._highlighted)

    def _keep_curve_look(self, curve: Any, trace: Trace, pen: Any) -> None:
        """Put the current look back after the curve took its own pen again; visibility and z stay."""
        if self._highlighted is not None or self._track_dimming:
            curve.setPen(self._curve_look(trace, pen)[0])

    def forget_highlight_items(self) -> None:
        """The items were just destroyed by a redraw -- nothing left to restore.

        The Track cursor reports its highlight again at the end of the redraw (refresh_track_cursor).
        """
        self._highlight_items = []
        self._highlighted = None
        self._track_dimming = False

    def highlighted_trace(self) -> Optional[Trace]:
        return self._highlighted

    def refresh_highlight(self) -> None:
        """Repaint the current looks after the other curves' opacity changes."""
        if self._highlighted is not None or self._track_dimming:
            self._apply_curve_looks(self._highlighted, self._track_dimming, legend=self._highlighted is not None)

    def set_highlight_preview(self, percent: Optional[int]) -> None:
        """Dim the other curves by ``percent`` in place of the saved setting; None puts the saved one back."""
        self._highlight_preview = percent
        self.refresh_highlight()

    def clear_highlight(self) -> None:
        """No highlighted curve; the curves keep the Track cursor highlight's look while it shows."""
        self._set_curve_looks(None, self._track_dimming)

    def set_track_cursor_dimming(self, showing: bool) -> None:
        """The Track cursor places its dots: every curve but the Highlight's is dimmed while ``showing``."""
        self._set_curve_looks(self._highlighted, showing)

    def _set_highlighted_trace(self, target: Optional[Trace]) -> None:
        self._set_curve_looks(target, self._track_dimming)

    def _set_curve_looks(self, target: Optional[Trace], track_dimming: bool) -> None:
        """Touch the pens only when the pair (highlighted curve, Track cursor highlight) changes."""
        if target is self._highlighted and track_dimming == self._track_dimming:
            return
        self._apply_curve_looks(target, track_dimming, legend=target is not self._highlighted)

    def _apply_highlight(self, target: Trace) -> None:
        self._apply_curve_looks(target, self._track_dimming, legend=True)

    def _apply_curve_looks(self, target: Optional[Trace], track_dimming: bool, *, legend: bool) -> None:
        self._highlighted = target
        self._track_dimming = track_dimming
        for trace, item, pen in self._highlight_items:
            _set_pen(item, *self._curve_look(trace, pen))
        if legend:  # the Track cursor highlight leaves the legend alone
            self._paint_legend(target)

    def _curve_look(self, trace: Trace, pen: Any) -> Tuple[Any, bool, bool]:
        """(pen, visible, on top) for a curve under the current Highlight and Track cursor highlight."""
        if self._highlighted is None and not self._track_dimming:
            return pen, True, False
        return self._highlight_look(trace, pen, self._highlighted)

    def _highlight_look(self, trace: Trace, pen: Any, target: Optional[Trace]) -> Tuple[Any, bool, bool]:
        """(pen, visible, on top) for a curve while ``target`` is highlighted; None dims every curve.

        Other curves fade by mixing their colour toward the plot background, not by pen alpha:
        an OpenGL viewport ignores pen alpha. At 0 % they are hidden outright.
        The copied pen keeps the curve's line style.
        """
        changed = pg.mkPen(pen)
        if trace is target:
            changed.setWidthF(pen.widthF() + HIGHLIGHT_EXTRA_WIDTH)
            return changed, True, True
        keep = self._highlight_keep()
        changed.setColor(_faded(changed.color(), keep))
        return changed, keep > 0, False

    def _highlight_keep(self) -> float:
        """How much of their own colour the other curves keep (the Settings percent)."""
        percent = self._highlight_preview
        if percent is None:
            percent = getattr(self.app_context, "highlight_other_opacity", None)
        return HIGHLIGHT_DIM_ALPHA if percent is None else percent / 100

    def _paint_legend(self, target: Optional[Trace]) -> None:
        """Legend rows in the curves' look while ``target`` is highlighted; own look for None.

        Text keeps its weight, so the legend never changes size; a row hidden at 0 %
        keeps its place (opacity, not visibility).
        """
        legend = self.plot_widget.plotItem.legend
        if legend is None or not legend.items:  # no legend above the curve limit
            return
        drawn: Dict[int, Tuple[Trace, Any]] = {
            id(item): (trace, pen) for trace, item, pen in self._highlight_items}
        text_color = legend.opts["labelTextColor"]
        keep = self._highlight_keep()
        for sample, label in legend.items:
            entry = drawn.get(id(sample.item))
            if entry is None or not isinstance(sample, HighlightSample):
                continue
            trace, pen = entry
            if target is None:
                sample.highlight_look, color, opacity = None, text_color, 1.0
            else:
                pen, visible, _ = self._highlight_look(trace, pen, target)
                sample.highlight_look = (pen, visible)
                dim = trace is not target
                color = _faded(pg.mkColor(text_color), keep) if dim else text_color
                opacity = 0.0 if dim and not visible else 1.0
            label.setText(label.text, color=color)
            label.setOpacity(opacity)
            sample.update()

    def update_highlight_at(self, scene_pos: QPointF) -> None:
        """Highlight the curve under a mouse at ``scene_pos`` via the shared hover gate."""
        self.update_cursor_at(scene_pos)
