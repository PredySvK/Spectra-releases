# =====================================================================
# FILE: gui/workspace/graph_dock.py
# =====================================================================
"""
GraphDock: one graph tab's PyQtGraph canvas. Its curves live in
view_models.plot.GraphCurves; the dock draws each change to them
(_on_curves_changed), takes channel drops and hosts the Band RMS cursors.
"""

from dataclasses import replace
import json
import uuid
import pyqtgraph as pg
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication
from PySide6.QtCore import QTimer, Qt, QPoint, QMimeData, Signal
from PySide6.QtGui import QDrag
from typing import Optional, List, Dict, Any

from core.units import (
    UnitPreferences,
)
from core.axis_projections import XAxisDisplay, resolve_x_axis_display
from core.block_kinds import KIND_SPECTRUM
from orchestration.channel_drop import PendingDrops
from view_models.analysis_kinds import ANALYSIS_ORDERS, ANALYSIS_OVERALL_LEVEL, ANALYSIS_SPECTRUM, ANALYSIS_TIME
from core.benchmark import benchmark_step
from core.evaluation import EvaluationConfig
from core.data_block import NVHDataBlock
from core.models import MeasurementRunIndex, ChannelMetadata
from gui.workspace.band_rms_cursors import BandRmsCursorsMixin
from gui.workspace.cursor import CursorMixin
from gui.workspace.highlight import HighlightMixin
from gui.workspace.channel_drop_target import ChannelDropTargetMixin, CHANNEL_DRAG_MIME
from gui.workspace.secondary_axis import SecondaryAxis
from view_models.plot import (
    AcceptOutcome,
    CurveAppended,
    CurvesChange,
    CurvesCleared,
    CurvesReplaced,
    DisplaySettings,
    GraphCurves,
    LiveChannelDrops,
    format_display_unit,
    HiddenReason,
    Trace,
    amplitude_mode_for_kind,
)


# Pen-style name (Qt-free, as carried on Trace.pen) -> Qt.PenStyle for drawing.
_PEN_STYLE_BY_NAME = {
    "solid": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dot": Qt.PenStyle.DotLine,
    "dashdot": Qt.PenStyle.DashDotLine,
}


class GraphDock(ChannelDropTargetMixin, BandRmsCursorsMixin, CursorMixin, HighlightMixin, QWidget):
    """High-performance PyQtGraph canvas sheet widget rendering raw signals time waveforms."""

    # The most drawn curves a dock still gives legend rows. pyqtgraph's
    # LegendItem re-measures every row on each addItem, so a legend costs
    # O(N^2) -- and 2000 rows are unreadable anyway (#441).
    _LEGEND_CURVE_LIMIT = 50

    # Fired the first time this dock's model goes from empty to holding a
    # base trace. Workspace uses it to re-run the Local filter's
    # focus-change routing (FilterRoutingHandler.dock_focus_changed): that
    # routing already runs once at build_shell/tab-focus time, but a fresh
    # dock's model is still None then, so a Local filter's Channel facet
    # comes back empty and never gets a chance to default itself onto this
    # dock's own (still nonexistent) channel -- see gui/handlers/
    # filter_routing.py._apply_mask_filter predicate, which then hides the base trace
    # the moment it actually renders. Not emitted on later renders (unit
    # change, refresh): those don't change which channels this dock offers.
    sig_first_trace_rendered = Signal()

    # Fired every time a trace is appended to an already-rendered dock (a
    # second/third channel dropped in, an overlay curve; once per coalesced
    # batch that added curves). A Local filter's Channel facet is built from this dock's own
    # traces (filter_routing.refresh_filter_panel), and that only
    # gets re-run on a dock-focus or profile-focus change -- so a channel
    # added to the dock that already has focus left the panel showing the
    # stale trace count until something else (Configure Filters' Apply,
    # switching tabs and back) happened to re-trigger it.
    sig_trace_added = Signal()

    # Fired every time this dock's drawn content or its Trace-filter mask
    # could have changed: after every drawn change (a mask change via
    # set_trace_filter, a full model rebuild, a curve removed, a curve appended).
    # The Evaluation card (ADR §1.64 point 5, issue #136) is the one
    # listener -- one signal at this chokepoint instead of a recompute call
    # threaded through every action that can add/remove/hide a curve
    # (channel drop, overlay, live compute, Result Pool load/unload).
    sig_content_or_mask_changed = Signal()

    def __init__(self, parent=None, app_context=None):
        super().__init__(parent)

        # Handed in at construction rather than discovered by climbing
        # self.window().workspace_frame.app_context: a dock built this way can be
        # tested by passing a stub context (or none) directly, with no live
        # window hierarchy behind it. May be None (e.g. the startup placeholder,
        # which never plots real data) -- every read below tolerates that.
        self.app_context = app_context

        # Identifies this dock across an asynchronous round trip. A computation
        # request carries it out and the finished signal carries it back, so the
        # result lands on the dock that asked for it even if the user has since
        # switched tabs -- which on a large file is several seconds of opportunity.
        # Random rather than counted: a restored dock takes back the id it was
        # saved with (Workspace.build_shell, ADR §1.94), and a fresh one must
        # never collide with that.
        self.dock_id: str = f"graph-{uuid.uuid4().hex}"

        # What this dock is showing -- one of view_models.analysis_kinds'
        # ANALYSIS_* names (ADR §1.87). Ribbon
        # actions and the drop router both branch on it. Before it existed they
        # guessed -- from isinstance plus the presence of a run_index, which a
        # spectrum tab and an order tab both satisfy, and from the text of the
        # bottom axis label.
        self.analysis_kind: str = ANALYSIS_TIME

        # Which source channel this dock is showing. Set by Workspace
        # right after construction (open_acc_spectrum_tab / open_acc_order_tracking_tab),
        # not passed to __init__, since a dock is also built before any channel
        # is chosen (see the startup placeholder). tacho_block is only ever
        # populated for an "orders" dock.
        self.run_index: Optional[MeasurementRunIndex] = None
        self.channel_meta: Optional[ChannelMetadata] = None
        self.tacho_block: Optional[NVHDataBlock] = None

        # Which curves this dock holds (CONTEXT.md "Graph curves", #272): the
        # PlotModel (ADR §1.7), the Trace filter mask and the visibility
        # decision through it, the overlay count, the loaded result sets and
        # the applied mask key. Every change ends in _on_curves_changed, the
        # only thing here that draws. Band RMS cursor state (enabled / band /
        # window corrections) lives on model.band_rms_cursors[0].
        self.curves = GraphCurves(on_change=self._on_curves_changed)
        self.live_drops = LiveChannelDrops()
        self.pending_drops = PendingDrops()
        # The dock's Evaluation configuration (ADR §1.64 point 1, issue #138):
        # evaluation algorithm name, parameters, and whether to respect the trace filter.
        # Persisted into TabSpec. Single values are recomputed on demand, not stored.
        self.evaluation_config: EvaluationConfig = EvaluationConfig()
        # The right-hand Y axis for an incompatible-unit overlay. Owns its own
        # ViewBox, range sync and legend entries -- see gui.workspace.secondary_axis.
        # Assigned in init_ui once plot_widget exists.
        self.secondary_axis: Optional[SecondaryAxis] = None
        # The bottom axis as last drawn (_draw_all): its label, unit and the
        # scale every curve's X is drawn with (global X axis unit, issue #459).
        # An append draws with the same one; a change of domain redraws in full.
        self._x_axis: XAxisDisplay = XAxisDisplay("", "")

        self._init_band_rms_cursors()
        self._geometry_initialized: bool = False
        self._drag_start_pos = QPoint()

        self.setAcceptDrops(True)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setObjectName("GraphPlot")  # Help figure target
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.addLegend()
        # PlotItem.addItem/removeItem rebuild the context menu's averaging
        # parameter list from every curve, O(N^2) for a result set of N (#442).
        # No curve here carries plot params, so that list is always empty.
        self.plot_widget.plotItem.updateParamList = lambda: None
        layout.addWidget(self.plot_widget)

        self.secondary_axis = SecondaryAxis(self.plot_widget)
        self._init_cursor()
        self._init_highlight()

    @property
    def _legend_shown(self) -> bool:
        """Whether the drawn curves get legend rows. A full draw decides it
        afresh; an append adds exactly one drawn curve, so _draw_appended
        redraws in full on the one append that crosses the limit."""
        return len(self.curves.visible.draw) <= self._LEGEND_CURVE_LIMIT

    def _unit_preferences(self) -> UnitPreferences:
        return self.app_context.unit_preferences() if self.app_context else UnitPreferences()

    def visible_traces(self) -> List[Trace]:
        """
        This dock's currently drawn curves -- the same visibility decision
        _draw_all() made (Trace filter mask, x-domain fit, third-axis drop),
        not a second one. The Evaluation card's dock adapter
        (gui/workspace/evaluation_adapter.py, ADR §1.64 point 3) reads this
        instead of `_visible`/`_trace_filter` directly.
        """
        return self.curves.visible_traces()

    def all_traces(self) -> List[Trace]:
        """
        Same visibility decision as `visible_traces()` (X-domain fit,
        third-axis drop) but with the Trace filter mask always passing --
        the dock adapter's input when Evaluation's "Respect Trace filter"
        toggle (ADR §1.64 point 1, issue #136) is off. The mask is the only
        thing skipped: it is the one CONTEXT.md calls the Trace filter, not
        the other two structural reasons a curve can't be drawn.
        """
        return self.curves.all_traces()

    def _on_curves_changed(self, change: CurvesChange) -> None:
        """The one place a change to self.curves reaches the screen, and the one
        place the dock's three signals are emitted -- each once, after the
        drawing is settled. A connected slot can call set_trace_filter
        synchronously, which redraws the whole model; emitting before the draw
        finished let that redraw land and then drew the same curve a second
        time (every fresh curve twice in the legend)."""
        if isinstance(change, CurvesCleared):
            self._draw_cleared()
            return
        if isinstance(change, CurvesReplaced):
            with benchmark_step("draw"):
                self._draw_all(change.first_curve)
            first_curve, trace_added = change.first_curve, change.curves_added
        elif isinstance(change, CurveAppended):
            with benchmark_step("draw"):
                self._draw_appended(change.trace, change.outcome)
            first_curve, trace_added = False, True
        else:
            raise TypeError(f"unhandled curves change: {change!r}")
        # May trigger a synchronous re-render of this same model (see the
        # signal's docstring) -- self.curves already holds the model, so that
        # nested draw sees the real trace list, not None.
        if first_curve:
            self.sig_first_trace_rendered.emit()
        if trace_added:
            self.sig_trace_added.emit()
        # Evaluation's "Respect Trace filter" off (issue #136) must see a curve
        # the mask hides via all_traces(), so a HIDDEN_MASK append fires too.
        self.sig_content_or_mask_changed.emit()

    def _draw_all(self, is_first_trace: bool) -> None:
        """
        Draw curves.model onto the canvas -- the one place curves, axes, title,
        locked X range and the secondary axis are put on screen.

        plot_blocks and add_curve hand blocks to self.curves, which builds the model.
        """
        model = self.curves.model
        visible = self.curves.visible
        view = model.view

        # The secondary ViewBox sits on the PlotItem's scene rather than in
        # plot_widget.items, so clear() never reaches it. Torn down first, else
        # curves from the previous plot survive the replot -- most visibly after
        # a global unit change, which redraws every open tab.
        self.secondary_axis.teardown()
        self.plot_widget.clear()
        self.forget_highlight_items()

        # The one visibility decision (issue #70): mask -> X-domain fit ->
        # drop a third secondary unit, taken by self.curves. An appended curve
        # is checked against this same result rather than re-deriving a subset.
        visible_traces = visible.draw

        # Never silently show nothing (ADR §1.25) -- the title is the cheapest
        # spot to say why. resolve_visible_traces decided *which* reason; the
        # wording stays here because it needs view.title and the domain name.
        title = view.title
        reason = visible.hidden_reason
        if reason is HiddenReason.MASK:
            n = visible.total
            title = f"{view.title} — Filter hid {n} of {n} curves"
        elif reason is HiddenReason.X_DOMAIN:
            n = visible.total
            title = (
                f"{view.title} — {n} of {n} curves can't be "
                f"shown against the {model.x_domain or 'current'} axis"
            )
        elif reason is HiddenReason.THIRD_AXIS:
            dropped = visible.third_axis_dropped
            plural = "s" if dropped != 1 else ""
            title = (
                f"{view.title} — {dropped} curve{plural} hidden: "
                f"a third Y-axis unit isn't supported"
            )
        if not self._legend_shown:
            # Worded against the limit, not the count: appends don't retitle.
            title = f"{title} — legend hidden above {self._LEGEND_CURVE_LIMIT} curves"
        self.plot_widget.setTitle(title)
        self._x_axis = self._resolve_x_axis()
        self.plot_widget.setLabel('bottom', self._x_axis.label, self._x_axis.unit)
        self.plot_widget.setLabel('left', view.y_label, view.y_unit)

        for trace in visible_traces:
            self._draw_trace(trace)

        if view.x_range is not None:
            self.plot_widget.setXRange(*(edge * self._x_axis.scale for edge in view.x_range))

        self._refresh_band_rms_cursors()

        if self._geometry_initialized:
            self.apply_viewport_clipping()

        if is_first_trace:
            self.plot_widget.plotItem.showAxis('left')
            self.plot_widget.plotItem.showAxis('bottom')
            self.plot_widget.showGrid(x=True, y=True)

    def _draw_trace(self, trace: Trace) -> None:
        """One curve on screen -- primary axis via plot_widget.plot, an
        incompatible unit onto the secondary ViewBox with its own range sync."""
        pen = pg.mkPen(
            color=trace.pen.color,
            width=trace.pen.width,
            style=_PEN_STYLE_BY_NAME.get(trace.pen.style, Qt.PenStyle.SolidLine),
        )

        # connect='finite' breaks the line at NaN instead of drawing through it.
        # Order cuts use NaN to mark speeds where the order sits above Nyquist or
        # below the frequency resolution, and those must read as gaps.
        x = self.drawn_x(trace.x)
        if trace.axis != "secondary":
            item = self.plot_widget.plot(
                x, trace.y,
                name=trace.label if self._legend_shown else None, pen=pen,
                autoDownsample=False, clipToView=False, connect='finite',
            )
            self.remember_highlight_item(trace, item, pen)
            return

        self.secondary_axis.ensure(
            format_display_unit(trace.unit)
        )
        item = self.secondary_axis.add(trace, pen, in_legend=self._legend_shown, x=x)
        if item is not None:
            self.remember_highlight_item(trace, item, pen)

    def _resolve_x_axis(self) -> XAxisDisplay:
        """The bottom axis as drawn: read off the dock's X domain rather than
        whatever the first-plotted curve happened to set, in the global X
        axis unit (issue #459). A model with no X domain keeps its own labels."""
        model = self.curves.model
        if model.x_domain:
            return resolve_x_axis_display(model.x_domain, self._unit_preferences().x_axis_unit)
        return XAxisDisplay(model.view.x_label, model.view.x_unit)

    def drawn_x(self, x: np.ndarray) -> np.ndarray:
        """``x`` (a curve's X in its quantity's own unit) as drawn on screen.
        The model never holds the rescaled values: the X domain, the Band RMS
        integration and the Evaluation all keep working in the native unit."""
        scale = self._x_axis.scale
        return x if scale == 1.0 else x * scale

    def apply_x_axis_unit(self) -> None:
        """Redraw for a changed global X axis unit and let the view range
        follow the new numbers -- a display rescale, the curves stay put."""
        if self.curves.model is None:
            return
        self.plot_widget.enableAutoRange()
        self._draw_all(is_first_trace=False)

    def _draw_appended(self, trace: Trace, outcome: AcceptOutcome) -> None:
        """
        Draw the one curve self.curves just appended, without redrawing the
        rest -- order cuts and an overlay drop both add curves one at a time in
        a loop, and a full draw per curve would be O(N^2).

        The curve is held either way (a hidden curve stays in the recipe,
        §1.28). One the mask hides while others still show is silently
        skipped; anything that needs the "why hidden" title (mask hid the last
        one, X domain, third secondary unit) was already re-resolved by
        self.curves and is drawn in full.
        """
        if outcome is AcceptOutcome.HIDDEN_MASK:
            return
        # Crossing the legend limit redraws in full, so the legend goes
        # away whole instead of stopping half-filled.
        if (outcome is AcceptOutcome.NEEDS_RENDER
                or len(self.curves.visible.draw) == self._LEGEND_CURVE_LIMIT + 1):
            self._draw_all(is_first_trace=False)
            return

        self._draw_trace(trace)

        if self._geometry_initialized:
            self.apply_viewport_clipping()

    def plot_blocks(self, blocks: List[NVHDataBlock]):
        """
        Plots 1D NVHDataBlocks as this dock's new base. Which model they
        become is decided by self.curves (GraphCurves.show_blocks) on
        block.kind, not by which Qt signal delivered them: a workflow engine
        (§1.6) hands over blocks with no calling context at all.
        """
        self._adopt_kind_of(blocks[0])
        self.curves.show_blocks(blocks, self._display_settings())

    def _adopt_kind_of(self, block: Optional[Any]) -> None:
        """The one rule both ways onto an empty dock follow (#454): a spectrum
        block makes it a spectrum dock, set before drawing so the signals and
        _display_settings() already see it. The first block decides, as in
        GraphCurves.show_blocks."""
        if getattr(block, "kind", None) == KIND_SPECTRUM:
            self.analysis_kind = ANALYSIS_SPECTRUM

    def clear_plot(self, title: str = ""):
        """
        Empties this dock without drawing anything in place of what was there.

        Resets the secondary axis too: its ViewBox sits on the scene rather
        than in plot_widget.items, so clear() alone
        would leave its curves behind.
        """
        self.curves.clear()
        self.plot_widget.setTitle(title)

    def _draw_cleared(self) -> None:
        self.secondary_axis.teardown()
        self.plot_widget.clear()
        self.forget_highlight_items()

        self._remove_band_rms_cursors()

    def add_curve(
        self,
        *,
        x: Optional[np.ndarray] = None,
        y: Optional[np.ndarray] = None,
        source_label: str = "",
        incoming_unit: str = "",
        source_meta: Optional[Dict[str, Any]] = None,
        block: Optional[Any] = None,
        compute_spec: Optional[Dict[str, Any]] = None,
        x_quantity: str = "",
        result_set_id: str = "",
        title: Optional[str] = None,
    ) -> Trace:
        """Adds one curve to this dock via self.curves.add_curve (#276).

        Determines base vs overlay automatically: when empty, sets up the base curve,
        axes, and grid; when not empty, appends an overlay curve. A loop adding
        many curves wraps itself in self.curves.coalesce_changes(), so the batch draws and
        sweeps viewport clipping once.
        """
        if self.curves.is_empty:
            self._adopt_kind_of(block)
        return self.curves.add_curve(
            x=x,
            y=y,
            source_label=source_label,
            incoming_unit=incoming_unit,
            source_meta=source_meta,
            compute_spec=compute_spec,
            x_quantity=x_quantity,
            result_set_id=result_set_id,
            block=block,
            settings=self._display_settings(),
            title=title,
        )

    def _display_settings(self, kind: Optional[str] = None) -> DisplaySettings:
        """The one place a dock reads app_context for how its curves are shown.

        The order cut / Overall Level amplitude is this dock's own View/Amplitude
        (ADR §1.62 point 22): keyed on the dock's own kind (or ``kind``), not on
        the kind of a curve being dropped or loaded onto it -- so an order cut
        dropped onto an Overall Level dock (or the reverse, issue #128) picks up
        whatever RMS/Peak this dock is already showing.
        """
        ctx = self.app_context
        d = DisplaySettings()
        if ctx is None:
            return d
        spectrum = getattr(ctx, "spectrum_settings", None)
        order = getattr(ctx, "order_tracking_settings", None)
        overall = getattr(ctx, "overall_level_settings", None)
        return DisplaySettings(
            prefs=self._unit_preferences(),
            spectrum_format=getattr(spectrum, "spectrum_format", d.spectrum_format),
            spectrum_amplitude_mode=getattr(spectrum, "amplitude_mode", d.spectrum_amplitude_mode),
            decibel_scale=getattr(spectrum, "decibel_scale", d.decibel_scale),
            amplitude_mode=amplitude_mode_for_kind(
                kind if kind is not None else self.analysis_kind,
                getattr(order, "amplitude_mode", d.amplitude_mode),
                getattr(overall, "amplitude_mode", d.amplitude_mode),
            ),
        )

    def rebuild_with_display_settings(
        self,
        spectrum_format: Optional[str] = None,
        amplitude_mode: Optional[str] = None,
        decibel_scale: Optional[bool] = None,
    ) -> None:
        """
        Re-scales the current PlotModel on the fly from canonical data (ADR §1.60).
        Runs synchronously in < 1 ms without re-running FFT or background jobs.
        """
        if self.curves.model is None:
            return
        analysis_kind = self.analysis_kind
        settings = self._display_settings()
        if analysis_kind == ANALYSIS_SPECTRUM:
            # The caller's amplitude_mode is the spectrum's own here.
            overrides = {"spectrum_format": spectrum_format,
                         "spectrum_amplitude_mode": amplitude_mode,
                         "decibel_scale": decibel_scale}
            self.curves.rebuild_spectrum_display(replace(
                settings, **{k: v for k, v in overrides.items() if v is not None}))
        elif analysis_kind in (ANALYSIS_ORDERS, ANALYSIS_OVERALL_LEVEL):
            if amplitude_mode is not None:
                settings = replace(settings, amplitude_mode=amplitude_mode)
            self.curves.rebuild_amplitude_display(settings)

    def iter_all_plot_items(self) -> List[Any]:
        """Every plot item on this dock -- primary axis plus the secondary one.

        The secondary ViewBox sits on the scene rather than in
        plot_widget.plotItem.items, so a caller that only walks the latter (the
        runtime downsample sweep in Workspace) would silently miss the
        right-axis curves.
        """
        items = list(self.plot_widget.plotItem.items)
        items += self.secondary_axis.iter_curves()
        return items

    # Below this point count, clipToView/autoDownsample only add slicing cost
    # to every pan/zoom frame with nothing to show for it -- measured on a
    # 700-point order cut, 100 curves: 19ms/move with clipping vs 12ms
    # without, against a 16ms frame budget at 60fps (BUGS.md K2-redraw).
    # Above it (a multi-million-sample time signal) the same slicing is what
    # keeps panning smooth.
    _CLIP_POINT_THRESHOLD = 20_000

    def apply_viewport_clipping(self) -> None:
        """Sweep clipping across all curves on this dock if geometry has been initialized (#276)."""
        if not self._geometry_initialized:
            return
        self._sweep_clip_flag(self.plot_widget.plotItem.items)
        self._sweep_clip_flag(self.secondary_axis.iter_curves())

    def _sweep_clip_flag(self, items):
        # Graph Defaults can only switch these off (#580): the point-count rule
        # decides where they are worth enabling, the saved preference vetoes it.
        ctx = self.app_context
        allow_auto = getattr(ctx, "perf_auto_mode_active", True) and getattr(ctx, "perf_downsample_enabled", True)
        allow_clip = getattr(ctx, "perf_render_screen_only", True)
        for item in items:
            if not isinstance(item, pg.PlotDataItem):
                continue
            x_data = item.xData
            large = x_data is not None and len(x_data) > self._CLIP_POINT_THRESHOLD
            clip, auto = large and allow_clip, large and allow_auto
            if item.opts.get('clipToView') == clip and item.opts.get('autoDownsample') == auto:
                continue  # already in the right state -- updateItems() would be pure waste
            item.opts['clipToView'] = clip
            item.opts['autoDownsample'] = auto
            item.updateItems()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() > 10 and event.size().height() > 10:
            self._geometry_initialized = True
            # `self` as the receiver context, not just the callable: closing the
            # tab within these 50 ms would otherwise fire the timer at an
            # already-deleted C++ widget, which surfaces to the user as the
            # global crash dialog for a purely cosmetic redraw.
            QTimer.singleShot(50, self, self.apply_viewport_clipping)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self.curves.is_empty:
            super().mouseMoveEvent(event)
            return

        if (event.position().toPoint() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return

        payload_list = self.curves.channel_drop_descriptors()

        if not payload_list:
            super().mouseMoveEvent(event)
            return

        mime_data = QMimeData()
        mime_data.setData(CHANNEL_DRAG_MIME, json.dumps(payload_list).encode("utf-8"))

        drag_session = QDrag(self)
        drag_session.setMimeData(mime_data)
        drag_session.exec(Qt.DropAction.CopyAction)
        event.accept()
