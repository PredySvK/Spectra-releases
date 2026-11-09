# =====================================================================
# FILE: gui/workspace/graph_dock.py
# =====================================================================
"""
GraphDock: one graph tab's PyQtGraph canvas. Its curves live in
view_models.plot.GraphCurves; the dock draws each change to them
(_on_curves_changed), takes channel drops and hosts the Band RMS cursors,
the Track cursor and Legend Settings.
"""

from dataclasses import replace
import json
import uuid
import pyqtgraph as pg
import numpy as np
from PySide6.QtWidgets import QVBoxLayout, QApplication
from PySide6.QtCore import QTimer, Qt, QPoint, QMimeData
from PySide6.QtGui import QDrag
from typing import Optional, List, Dict, Any, Tuple

from core.units import (
    UnitPreferences,
)
from core.axis_projections import (
    AxisScreenRule, XAxisDisplay, resolve_log_axis_floor, resolve_x_axis_display,
    resolve_x_axis_screen_rule,
)
from core.block_kinds import KIND_SPECTRUM
from orchestration.channel_drop import PendingDrops
from orchestration.companion_curves import CompanionCurvesState
from view_models.analysis_kinds import (
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTRUM,
    ANALYSIS_TIME,
)
from core.benchmark import benchmark_step
from core.evaluation import EvaluationConfig
from core.data_block import NVHDataBlock
from core.models import MeasurementRunIndex, ChannelMetadata
from gui.workspace.plot_title import set_plot_title
from gui.workspace.band_rms_cursors import BandRmsCursorsMixin
from gui.workspace.cursor import CursorMixin
from gui.workspace.highlight import HighlightMixin, HighlightSample
from gui.workspace.legend_settings import LegendSettingsMixin
from gui.workspace.track_cursor import TrackCursorMixin
from gui.workspace.plot_area import GRAPH_TOKENS, style_plot_area
from gui.workspace.channel_drop_target import ChannelDropTargetMixin, CHANNEL_DRAG_MIME
from gui.workspace.display_prefix_axis import DisplayPrefixAxisItem
from gui.workspace.secondary_axis import SecondaryAxis
from gui.workspace.workspace_dock import WorkspaceDock
from view_models.plot import (
    AcceptOutcome,
    BandRmsBandMoved,
    CurveAppended,
    CurvesChange,
    CurvesCleared,
    CurvesReplaced,
    DisplaySettings,
    resolve_display_settings,
    GraphCurves,
    format_display_unit,
    HiddenReason,
    resolve_curve_decimation,
    resolve_ordinate_quantity,
    RenderingMode,
    Trace,
    resolve_curve_look,
    resolve_rendering_mode,
)

# The raster carousel's line styles (view_models.plot.LINE_STYLES) as Qt pens.
# Long dash has no Qt built-in: a custom pattern, in pen widths.
_QT_LINE_STYLES = {
    "solid": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dot": Qt.PenStyle.DotLine,
    "dashdot": Qt.PenStyle.DashDotLine,
    "dashdotdot": Qt.PenStyle.DashDotDotLine,
}
_LONG_DASH_PATTERN = [12, 4]


class GraphDock(ChannelDropTargetMixin, BandRmsCursorsMixin, TrackCursorMixin, CursorMixin, HighlightMixin,
                LegendSettingsMixin, WorkspaceDock):
    """High-performance PyQtGraph canvas sheet widget rendering raw signals time waveforms."""

    # The most drawn curves a dock still gives legend rows. pyqtgraph's
    # LegendItem re-measures every row on each addItem, so a legend costs
    # O(N^2) -- and 2000 rows are unreadable anyway (#441).
    _LEGEND_CURVE_LIMIT = 50

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
        # ANALYSIS_* names. Ribbon
        # actions and the drop router both branch on it. Before it existed they
        # guessed -- from isinstance plus the presence of a run_index, which a
        # spectrum tab and an order tab both satisfy, and from the text of the
        # bottom axis label.
        self.analysis_kind: str = ANALYSIS_TIME

        # Which source channel this dock is showing. Set by Workspace
        # right after construction (build_shell),
        # not passed to __init__, since a dock is also built before any channel
        # is chosen (see the startup placeholder). tacho_block is only ever
        # populated for an "orders" dock.
        self.run_index: Optional[MeasurementRunIndex] = None
        self.channel_meta: Optional[ChannelMetadata] = None
        self.tacho_block: Optional[NVHDataBlock] = None

        # Which curves this dock holds (CONTEXT.md "Graph curves", #272): the
        # PlotModel, the Trace filter mask and the visibility
        # decision through it, the overlay count, the loaded result sets and
        # the applied mask key and the Band RMS band. Every change ends in
        # _on_curves_changed, the only thing here that draws.
        self.curves = GraphCurves(on_change=self._on_curves_changed,
                                  base_curve_color=GRAPH_TOKENS.base_curve)
        self.pending_drops = PendingDrops()
        self.companion_curves = CompanionCurvesState()
        # The dock's Evaluation configuration:
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

        self.plot_widget = pg.PlotWidget(
            axisItems={
                "bottom": DisplayPrefixAxisItem("bottom", unit_preferences_provider=self._unit_preferences),
                "left": DisplayPrefixAxisItem("left", unit_preferences_provider=self._unit_preferences),
                "right": DisplayPrefixAxisItem("right", unit_preferences_provider=self._unit_preferences),
            }
        )
        self.plot_widget.setObjectName("GraphPlot")  # Help figure target
        # The axes read the log switches through the dock (§1.276), not the
        # library's own log mode; they exist before the switches do.
        for side, x_axis in (("bottom", True), ("left", False), ("right", False)):
            self.plot_widget.getAxis(side).set_shown_rule_provider(
                lambda x_axis=x_axis: self._shown_value_rule(x_axis=x_axis))
        # A new plot widget draws as main.py configured (OpenGL); every full
        # draw then picks the mode its curves need (_apply_rendering_mode).
        self._rendering_mode = (RenderingMode.OPENGL if pg.getConfigOption('useOpenGL')
                                else RenderingMode.RASTER)
        style_plot_area(self.plot_widget)
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.addLegend(labelTextColor=GRAPH_TOKENS.axis, sampleType=HighlightSample)
        # PlotItem.addItem/removeItem rebuild the context menu's averaging
        # parameter list from every curve, O(N^2) for a result set of N (#442).
        # No curve here carries plot params, so that list is always empty.
        self.plot_widget.plotItem.updateParamList = lambda: None
        layout.addWidget(self.plot_widget)

        self.secondary_axis = SecondaryAxis(self.plot_widget, unit_preferences_provider=self._unit_preferences)
        self._init_cursor()
        self._init_highlight()
        self._init_track_cursor()
        self._init_legend_settings()
        self._track_cursor_refresh = QTimer(self)
        self._track_cursor_refresh.setSingleShot(True)
        self._track_cursor_refresh.setInterval(0)
        self._track_cursor_refresh.timeout.connect(self.refresh_track_cursor)
        # Connected after PlotItem's own updateLogMode (PlotItem.__init__), so the
        # hook runs with the ViewBox and the primary curves already switched.
        ctrl = self.plot_widget.plotItem.ctrl
        ctrl.logXCheck.toggled.connect(self._on_log_x_toggled)
        ctrl.logYCheck.toggled.connect(self._on_log_y_toggled)

    def _logarithmic_axes(self) -> Tuple[bool, bool]:
        """(log X, log Y) as switched in the plot library's menu (Plot Options >
        Transforms) -- the one place in gui/ that reads those switches (§1.276).
        The state lives in the menu: it belongs to this graph, survives a replot
        and a Refresh, and is never saved into the project."""
        ctrl = self.plot_widget.plotItem.ctrl
        return ctrl.logXCheck.isChecked(), ctrl.logYCheck.isChecked()

    def x_screen_rule(self) -> AxisScreenRule:
        """Where a native X (the model's unit) sits on screen right now: the
        X axis unit scale of the axis as last drawn, then log10 on a
        Logarithmic axis (§1.276). Everything placed on X goes through it."""
        return resolve_x_axis_screen_rule(self._x_axis, self._logarithmic_axes()[0])

    def y_screen_rule(self) -> AxisScreenRule:
        """Where a Y value sits on screen right now: as it is, or its log10 on
        a Logarithmic Y axis (§1.276)."""
        return AxisScreenRule(logarithmic=self._logarithmic_axes()[1])

    def _shown_value_rule(self, *, x_axis: bool) -> AxisScreenRule:
        """Where a value as the axis shows it (the Display unit, no X axis unit
        scale) sits on the axis ticks: the rule the axis labels read (§1.276)."""
        return AxisScreenRule(logarithmic=self._logarithmic_axes()[0 if x_axis else 1])

    def _on_log_x_toggled(self, _checked: bool) -> None:
        # Looked up at call time, so a test (or a subclass) sees the call.
        self.apply_logarithmic_axes()

    def _on_log_y_toggled(self, _checked: bool) -> None:
        # A log Y switch leaves the X range as the user left it.
        self.apply_logarithmic_axes(reset_x_range=False)

    def apply_logarithmic_axes(self, *, reset_x_range: bool = True) -> None:
        """The hook a switch of log X / log Y ends in (§1.276): put back on
        screen, through x_screen_rule / y_screen_rule, everything Spectra itself
        places on the axes -- the library only re-transforms the ViewBox and the
        curves it added. Synchronous on the GUI thread: a few values, no curve
        data, no disk. Steps that follow the switch belong here, in this order:
        the secondary axis and its curves, the bottom axis labels, the Band RMS
        band, the X range, the Track cursor line on its native X, and last the
        Cursor Box that reads all of them. ``reset_x_range`` is False for a
        switch of log Y alone, which keeps the X range as the user left it."""
        if self.curves.model is None:
            return
        # The library asked for an auto range of both axes with the switch; it
        # would run at the next paint. A log Y switch keeps the X range as it is.
        kept_x_range = None if reset_x_range else tuple(self.plot_widget.plotItem.vb.viewRange()[0])
        self.secondary_axis.apply_logarithmic_axes(self.x_screen_rule(), self.y_screen_rule())
        for side in ("bottom", "left", "right"):
            self.plot_widget.getAxis(side).update_display_prefix()
        self.refresh_band_rms_cursors()
        if reset_x_range:
            self._place_x_range()
        else:
            self.plot_widget.setXRange(*kept_x_range, padding=0)
        self.refresh_track_cursor()
        self.refresh_cursor_box()

    def log_x_floor(self) -> Optional[float]:
        """The lower edge of a Logarithmic X axis: the smallest positive X of
        the visible curves (§1.276). The one place it is worked out -- the X
        range and the Band RMS band both clip to it."""
        return resolve_log_axis_floor(*(trace.x for trace in self.curves.visible.draw))

    def _place_x_range(self) -> None:
        """Put the model's locked X range (native unit, left as it is) on the
        view through x_screen_rule: scaled to the X axis unit, log10 on a
        Logarithmic X axis. A lower edge with no screen position there (0 Hz,
        a negative rpm) becomes the smallest positive X of the visible curves
        (§1.276); an edge that still has none leaves the range alone."""
        x_range = self.curves.model.view.x_range
        if x_range is None:
            return
        rule = self.x_screen_rule()
        low, high = x_range
        if rule.logarithmic and not rule.has_screen_position(low):
            floor = self.log_x_floor()
            if floor is None:
                return
            low = floor
        edges = (rule.to_screen(low), rule.to_screen(high))
        if all(np.isfinite(edges)) and edges[0] < edges[1]:
            self.plot_widget.setXRange(*edges)

    @property
    def _legend_shown(self) -> bool:
        """Whether the drawn curves get legend rows. A full draw decides it
        afresh; an append adds exactly one drawn curve, so _draw_appended
        redraws in full on the one append that crosses the limit."""
        return len(self.curves.visible.draw) <= self._LEGEND_CURVE_LIMIT

    def _unit_preferences(self) -> UnitPreferences:
        if self.app_context is not None and hasattr(self.app_context, "unit_preferences"):
            return self.app_context.unit_preferences()
        return UnitPreferences()

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
        toggle is off. The mask is the only
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
        if isinstance(change, BandRmsBandMoved):
            self._show_band_rms_readout()
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

        # Never silently show nothing -- the title is the cheapest
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
        elif reason is HiddenReason.FORMAT:
            hidden = visible.format_dropped
            plural = "s" if hidden != 1 else ""
            title = (
                f"{view.title} — {hidden} curve{plural} hidden: "
                f"Linear average shows only the Linear format"
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
        set_plot_title(self.plot_widget, title)
        self._x_axis = self._resolve_x_axis()
        self.plot_widget.getAxis('bottom').set_quantity(model.x_domain)
        self.plot_widget.getAxis('left').set_quantity(view.y_quantity)
        self.plot_widget.setLabel('bottom', self._x_axis.label, self._x_axis.unit)
        self.plot_widget.setLabel('left', view.y_label, view.y_unit)

        self._apply_rendering_mode(resolve_rendering_mode(visible_traces))
        for trace in visible_traces:
            self._draw_trace(trace)

        self._place_x_range()

        self.refresh_band_rms_cursors()
        self.refresh_cursor_box()
        self.refresh_track_cursor()

        if self._geometry_initialized:
            self.apply_viewport_clipping()

        if is_first_trace:
            self.plot_widget.plotItem.showAxis('left')
            self.plot_widget.plotItem.showAxis('bottom')
            self.plot_widget.showGrid(x=True, y=True)

    def _draw_trace(self, trace: Trace) -> None:
        """One curve on screen -- primary axis via plot_widget.plot, an
        incompatible unit onto the secondary ViewBox with its own range sync."""
        pen = self._curve_pen(trace)

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
            format_display_unit(trace.unit), quantity=resolve_ordinate_quantity(trace)
        )
        item = self.secondary_axis.add(
            trace, pen, in_legend=self._legend_shown, x=x,
            x_rule=self.x_screen_rule(), y_rule=self.y_screen_rule(),
        )
        if item is not None:
            self.remember_highlight_item(trace, item, pen)

    def _curve_pen(self, trace: Trace) -> Any:
        """The Qt pen ``trace`` is drawn with in the dock's rendering mode."""
        look = resolve_curve_look(trace.pen, self._rendering_mode, GRAPH_TOKENS.curve_palette)
        pen = pg.mkPen(color=look.color, width=look.width)
        if look.style == "longdash":
            pen.setDashPattern(_LONG_DASH_PATTERN)
        else:
            pen.setStyle(_QT_LINE_STYLES[look.style])
        return pen

    def _apply_rendering_mode(self, mode: RenderingMode) -> None:
        """Switch the viewport to ``mode``. Rebuilds the viewport
        widget, so only on a change; the Cursor and Highlight watch the
        viewport for the mouse leaving and are put on the new one."""
        if mode is self._rendering_mode:
            return
        self._rendering_mode = mode
        self.plot_widget.useOpenGL(mode is RenderingMode.OPENGL)
        self._install_hover_viewport_filter()

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

    def apply_unit_preferences(self) -> None:
        """
        Follow changed global unit preferences: the axes' display prefixes,
        the curves themselves whatever this dock's Analysis kind,
        and the Cursor Box.

        The rebuild re-scales from the untouched ``y_raw``
        (``GraphCurves.rebuild_units``) -- no disk, no DSP, and the frame
        (title, axes) is preserved rather than reset (a time-record
        replacement would relabel a spectrum / order-cut dock as a time
        record while the curve stays put, audit 02/9.1).
        """
        # All three are DisplayPrefixAxisItems (init_ui); the secondary Y axis
        # draws on the "right" one, so it follows here too.
        for axis_name in ("bottom", "left", "right"):
            self.plot_widget.getAxis(axis_name).update_display_prefix()
        self._rebuild_units()
        self.refresh_cursor_box()
        self.refresh_track_cursor()

    def _rebuild_units(self) -> None:
        model = self.curves.model
        if model is None:
            return
        # The model's own analysis_kind has to agree with the dock's: a dock
        # tagged e.g. "spectrum" over a plain time-built model (no real
        # spectrum draw ever landed yet) is left alone rather than routed into
        # a redraw whose view (title, axis labels) belongs to a different
        # analysis kind.
        if model.analysis_kind != self.analysis_kind:
            return
        self.curves.rebuild_units(self._unit_preferences())

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
        # away whole instead of stopping half-filled; so does a large curve
        # landing on a raster graph, which must switch it to OpenGL.
        if (outcome is AcceptOutcome.NEEDS_RENDER
                or len(self.curves.visible.draw) == self._LEGEND_CURVE_LIMIT + 1
                or (self._rendering_mode is RenderingMode.RASTER
                    and resolve_rendering_mode([trace]) is RenderingMode.OPENGL)):
            self._draw_all(is_first_trace=False)
            return

        self._draw_trace(trace)
        # Curves arrive one at a time in a loop; the Track cursor reads every
        # drawn curve, so it is refreshed once after the loop, not per curve.
        self._track_cursor_refresh.start()

        if self._geometry_initialized:
            self.apply_viewport_clipping()

    def plot_blocks(self, blocks: List[NVHDataBlock]):
        """
        Plots 1D NVHDataBlocks as this dock's new base. Which model they
        become is decided by self.curves (GraphCurves.show_blocks) on
        block.kind, not by which Qt signal delivered them: a workflow engine
        (§1.6) hands over blocks with no calling context at all.
        """
        self._clear_cursor()
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
        set_plot_title(self.plot_widget, title)

    def _draw_cleared(self) -> None:
        self.secondary_axis.teardown()
        self.plot_widget.clear()
        self.forget_highlight_items()

        self._remove_band_rms_cursors()
        self._clear_cursor()
        self.refresh_track_cursor()

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

    def _display_settings(self) -> DisplaySettings:
        """The one place a dock reads app_context for how its curves are shown;
        which ribbon config belongs to which kind is resolve_display_settings'
        (#833). The order cut / Overall Level amplitude is this dock's own
        View/Amplitude."""
        ctx = self.app_context
        return resolve_display_settings(
            self.analysis_kind,
            prefs=self._unit_preferences(),
            spectrum=getattr(ctx, "spectrum_settings", None),
            order_tracking=getattr(ctx, "order_tracking_settings", None),
            overall_level=getattr(ctx, "overall_level_settings", None),
        )

    def rebuild_with_display_settings(
        self,
        spectrum_format: Optional[str] = None,
        amplitude_mode: Optional[str] = None,
        decibel_scale: Optional[bool] = None,
    ) -> None:
        """
        Re-scales the current PlotModel on the fly from canonical data.
        Runs synchronously in < 1 ms without re-running FFT or background jobs.
        The settings are this dock's own (_display_settings); an argument only
        overrides one of them.
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

    def apply_viewport_clipping(self) -> None:
        """Sweep clipping/downsampling across all curves on this dock if geometry has been
        initialized (#276). The one GUI application of ``resolve_curve_decimation``: a resize
        and a Settings change both end here (#665 C27)."""
        if not self._geometry_initialized:
            return
        self._sweep_clip_flag(self.iter_all_plot_items())

    def _sweep_clip_flag(self, items):
        ctx = self.app_context
        prefs = dict(
            render_screen_only=getattr(ctx, "perf_render_screen_only", True),
            downsample_enabled=getattr(ctx, "perf_downsample_enabled", True),
            auto_mode=getattr(ctx, "perf_auto_mode_active", True),
            manual_factor=getattr(ctx, "perf_manual_factor", 1),
        )
        for item in items:
            if not isinstance(item, pg.PlotDataItem):
                continue
            x_data = item.xData
            rule = resolve_curve_decimation(0 if x_data is None else len(x_data), **prefs)
            if (item.opts.get('clipToView') == rule.clip and item.opts.get('autoDownsample') == rule.auto
                    and item.opts.get('downsample') == rule.factor):
                continue  # already in the right state -- updateItems() would be pure waste
            item.setDownsampling(rule.factor, auto=rule.auto, method=None)
            item.setClipToView(rule.clip)

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
