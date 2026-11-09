# =====================================================================
# FILE: gui/workspace/band_rms_cursors.py
# =====================================================================
"""
Band RMS cursors for GraphDock's frequency-domain plots.

A draggable band over a spectrum that reports Band RMS (CONTEXT.md) within
its span. Mixed into GraphDock rather than built as a separate collaborator:
this code reaches directly into the dock's own plot_widget. Whether the band
shows is the app-level AppContext.band_rms_cursors_enabled, which curve it
measures and the span the user dragged are GraphCurves', and where it stands
and what the readout says are decided in view_models.plot; only the two
pyqtgraph widgets live here (_band_rms_region, _band_rms_label), declared in
_init_band_rms_cursors.
"""

from typing import Optional, Tuple

import pyqtgraph as pg

from gui.workspace.plot_area import GRAPH_TOKENS
from view_models.plot import build_band_rms_readout, resolve_band_rms_span


class BandRmsCursorsMixin:
    """Draggable Band RMS band + readout, mixed into GraphDock."""

    def _init_band_rms_cursors(self) -> None:
        """Called from GraphDock.__init__."""
        self._band_rms_region: Optional[pg.LinearRegionItem] = None
        self._band_rms_label: Optional[pg.TextItem] = None

    def _remove_band_rms_cursors(self):
        if self._band_rms_region is not None:
            for signal in (self._band_rms_region.sigRegionChanged, self._band_rms_region.sigRegionChangeFinished):
                try:
                    signal.disconnect(self._on_band_rms_dragged)
                except (RuntimeError, TypeError):
                    pass
            self.plot_widget.removeItem(self._band_rms_region)
            self._band_rms_region = None

        if self._band_rms_label is not None:
            self._band_rms_label.setParentItem(None)
            scene = self.plot_widget.plotItem.scene()
            if scene is not None:
                scene.removeItem(self._band_rms_label)
            self._band_rms_label = None

    def refresh_band_rms_cursors(self) -> None:
        """Draw the band and its readout again, or take them away when the global
        switch is off or this graph holds no spectrum."""
        self._remove_band_rms_cursors()

        curve = self.curves.band_rms_curve
        if curve is None or not getattr(self.app_context, "band_rms_cursors_enabled", False):
            return
        span = resolve_band_rms_span(self.curves.band_rms_band, curve.x)
        if span is None:
            return

        # The band is kept in Hz; only the region on screen follows the X axis
        # rule (unit scale, then log10 on a Logarithmic axis, §1.276), so
        # the span survives switching either. On a Logarithmic axis an edge at
        # or below 0 Hz is clipped to the smallest positive X, on screen only.
        rule = self.x_screen_rule()
        floor = self.log_x_floor() if rule.logarithmic else None
        if rule.logarithmic and floor is None:
            return
        start, stop, low = (max(v, floor) if floor is not None else v
                            for v in (span.start, span.stop, span.low))
        if not stop > start:
            return
        self._band_rms_region = pg.LinearRegionItem(
            values=(rule.to_screen(start), rule.to_screen(stop)),
            pen=pg.mkPen(GRAPH_TOKENS.band_rms_line),
            hoverPen=pg.mkPen(GRAPH_TOKENS.band_rms_line_hover),
            brush=pg.mkBrush(*GRAPH_TOKENS.band_rms_region_fill),
            hoverBrush=pg.mkBrush(*GRAPH_TOKENS.band_rms_region_hover_fill),
        )
        self._band_rms_region.setBounds([rule.to_screen(low), rule.to_screen(span.high)])
        # Behind the traces, so dragging the band never hides the data it measures.
        self._band_rms_region.setZValue(-10)
        self.plot_widget.addItem(self._band_rms_region)

        # Parented to the ViewBox, so setPos is in pixels and the readout stays
        # put while the user pans and zooms underneath it.
        self._band_rms_label = pg.TextItem(
            anchor=(0, 0), color=GRAPH_TOKENS.cursor_box_line, fill=pg.mkBrush(*GRAPH_TOKENS.band_rms_box_fill)
        )
        self._band_rms_label.setParentItem(self.plot_widget.plotItem.vb)
        self._band_rms_label.setPos(12, 10)

        # The last step of dragging the whole band only reports "finished".
        self._band_rms_region.sigRegionChanged.connect(self._on_band_rms_dragged)
        self._band_rms_region.sigRegionChangeFinished.connect(self._on_band_rms_dragged)
        self._show_band_rms_readout()

    def _band_rms_region_hz(self) -> Tuple[float, float]:
        """The band as it stands on screen, back in Hz."""
        to_native = self.x_screen_rule().to_native
        start, stop = self._band_rms_region.getRegion()
        return to_native(float(start)), to_native(float(stop))

    def _on_band_rms_dragged(self) -> None:
        self.curves.move_band_rms_band(*self._band_rms_region_hz())

    def _show_band_rms_readout(self) -> None:
        start, stop = self._band_rms_region_hz()
        self._band_rms_label.setText(build_band_rms_readout(
            self.curves.band_rms_curve, start, stop, self._x_axis, self._unit_preferences()))
