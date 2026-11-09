# =====================================================================
# FILE: gui/workspace/secondary_axis.py
# =====================================================================
"""
The right-hand Y axis a GraphDock opens for an overlay curve whose unit cannot
be reconciled with the primary axis (a Pa microphone trace on a g accelerometer
graph).

Lives in gui/ because it is pure pyqtgraph -- it owns a pg.ViewBox on the
PlotItem's scene, the bidirectional Y-range sync between that ViewBox and the
primary one, and the legend entries for its curves. Colocated with graph_dock.py
because it is that dock's rendering concern, not a workspace-wide service.

GraphDock holds one SecondaryAxis and drives it with ensure() / add() /
apply_logarithmic_axes() / teardown(); the ViewBox, the sync handlers and the
legend bookkeeping never leak past that interface.

On a Logarithmic axis (§1.276) the secondary ViewBox and its curves follow
the primary axis: log X always (the X is shared), log Y together with the
primary Y. The dock hands in its screen rules; this class never reads the
plot menu's switches.
"""

from typing import Any, Callable, List, Optional, Sequence, Tuple
from core.axis_projections import AxisScreenRule
from core.units import UnitPreferences
from gui.workspace.display_prefix_axis import DisplayPrefixAxisItem

import numpy as np
import pyqtgraph as pg

from view_models.plot import Trace


Range = Sequence[float]


def project_synced_range(
    driver_old: Range, driver_new: Range, follower_old: Range
) -> Tuple[float, float]:
    """Project the driver axis's range change onto the follower axis.

    All three ranges are screen coordinates (what ViewBox.viewRange gives: the
    log10 of the value on a Logarithmic axis, §1.276), so a log Y axis
    is panned and zoomed by the same fraction of its screen span as a linear
    one. The caller re-takes its old ranges whenever the screen rule changes
    -- an old linear range against a new log10 one would carry no meaning.

    Both sync directions (primary drives secondary, secondary drives primary)
    use the identical normalisation: express the driver's new bounds as
    fractions of its old span, then place the follower's new bounds at the same
    fractions of its own old span. A zero-span driver carries no information, so
    the follower is returned unchanged.
    """
    d_old_min, d_old_max = driver_old
    d_span = d_old_max - d_old_min
    if d_span == 0:
        return float(follower_old[0]), float(follower_old[1])

    d_new_min, d_new_max = driver_new
    f_old_min, f_old_max = follower_old
    f_span = f_old_max - f_old_min

    norm_min = (d_new_min - d_old_min) / d_span
    norm_max = (d_new_max - d_old_min) / d_span
    return f_old_min + norm_min * f_span, f_old_min + norm_max * f_span


class SecondaryAxis:
    """The dock's secondary right Y axis: ViewBox lifecycle + range sync + legend."""

    def __init__(
        self,
        plot_widget: pg.PlotWidget,
        unit_preferences_provider: Optional[Callable[[], UnitPreferences]] = None,
    ) -> None:
        self._plot_widget = plot_widget
        self._unit_preferences_provider = unit_preferences_provider
        right_axis = plot_widget.plotItem.getAxis("right")
        if isinstance(right_axis, DisplayPrefixAxisItem) and unit_preferences_provider is not None:
            right_axis._unit_preferences_provider = unit_preferences_provider
        self._view_box: Optional[pg.ViewBox] = None
        self._unit: str = ""
        # (signal, handler) pairs, so teardown can undo exactly these rather
        # than clearing every subscriber on the primary ViewBox.
        self._connections: List[Tuple[Any, Any]] = []
        # Curve items added straight to the legend -- they live in the secondary
        # ViewBox, not plot_widget.items, so neither plot_widget.clear() nor the
        # legend's own auto-sync ever removes their legend entry.
        self._legend_items: List[Any] = []
        self._p1_last_yrange: Range = [0.0, 1.0]
        self._p2_last_yrange: Range = [0.0, 1.0]
        self._is_syncing = False

    # -- introspection -----------------------------------------------------

    @property
    def unit(self) -> str:
        return self._unit

    @property
    def is_active(self) -> bool:
        return self._view_box is not None

    @property
    def view_box(self) -> Optional[pg.ViewBox]:
        return self._view_box

    def iter_curves(self) -> List[Any]:
        """Every item on the secondary ViewBox -- the caller filters for type.

        The dock folds this into iter_all_plot_items() (routing, downsample
        sweep); nothing reaches for the ViewBox itself.
        """
        if self._view_box is None:
            return []
        return list(self._view_box.addedItems)

    # -- lifecycle -------------------------------------------------------------

    def ensure(self, unit: str, quantity: str = "") -> None:
        """Build (or rebuild for a new unit) the right axis and its ViewBox.

        Already built for the same unit: no-op. Built for a different unit: torn
        down and rebuilt -- a second incompatible unit needs a fresh axis, not
        one stacked on top of the first. ``quantity`` is the curve's Y quantity
        (resolve_ordinate_quantity), the Display prefix row for a Hz axis.
        """
        right_axis = self._plot_widget.plotItem.getAxis("right")
        if isinstance(right_axis, DisplayPrefixAxisItem):
            right_axis.set_quantity(quantity)
        if self._view_box is not None:
            if self._unit == unit:
                return
            self.teardown()

        self._unit = unit
        plot_item = self._plot_widget.plotItem

        plot_item.showAxis("right")
        plot_item.getAxis("right").setLabel("Secondary Amplitude", unit)

        self._view_box = pg.ViewBox()
        plot_item.scene().addItem(self._view_box)

        plot_item.getAxis("right").linkToView(self._view_box)
        self._view_box.setXLink(plot_item.vb)

        def sync_view_matrices_geometry():
            if self._view_box is not None:
                self._view_box.setGeometry(plot_item.vb.sceneBoundingRect())
                self._view_box.linkedViewChanged(plot_item.vb, self._view_box.XAxis)

        plot_item.vb.sigResized.connect(sync_view_matrices_geometry)
        sync_view_matrices_geometry()

        self._p1_last_yrange = plot_item.vb.viewRange()[1]
        self._p2_last_yrange = self._view_box.viewRange()[1]
        self._is_syncing = False

        def on_main_y_changed(vb, new_range):
            if self._is_syncing or self._view_box is None:
                return
            # project_synced_range handles a zero-span driver, but the old code
            # returned here *without* updating _p1_last_yrange -- keep that so the
            # extraction stays behaviour-for-behaviour identical.
            if self._p1_last_yrange[1] - self._p1_last_yrange[0] == 0:
                return
            p2_new = project_synced_range(
                self._p1_last_yrange, new_range, self._p2_last_yrange
            )
            self._is_syncing = True
            self._view_box.setYRange(p2_new[0], p2_new[1], padding=0)
            self._p1_last_yrange = new_range
            self._p2_last_yrange = p2_new
            self._is_syncing = False

        def on_sec_y_changed(vb, new_range):
            if self._is_syncing or plot_item.vb is None:
                return
            if self._p2_last_yrange[1] - self._p2_last_yrange[0] == 0:
                return
            p1_new = project_synced_range(
                self._p2_last_yrange, new_range, self._p1_last_yrange
            )
            self._is_syncing = True
            plot_item.vb.setYRange(p1_new[0], p1_new[1], padding=0)
            self._p2_last_yrange = new_range
            self._p1_last_yrange = p1_new
            self._is_syncing = False

        plot_item.vb.sigYRangeChanged.connect(on_main_y_changed)
        self._view_box.sigYRangeChanged.connect(on_sec_y_changed)

        self._connections = [
            (plot_item.vb.sigResized, sync_view_matrices_geometry),
            (plot_item.vb.sigYRangeChanged, on_main_y_changed),
            (self._view_box.sigYRangeChanged, on_sec_y_changed),
        ]

    def add(
        self, trace: Trace, pen, *, in_legend: bool, x: np.ndarray,
        x_rule: AxisScreenRule, y_rule: AxisScreenRule,
    ) -> Optional[Any]:
        """Draw one curve onto the secondary ViewBox with its own initial range.
        ``x`` is the curve's X as the dock draws it (the global X axis unit,
        issue #459), not ``trace.x``. ``x_rule`` / ``y_rule`` are the dock's
        screen rules right now, so a curve added while a Logarithmic axis is on
        is drawn in log mode like the primary ones (§1.276). Returns the
        drawn item (None without an axis)."""
        if self._view_box is None:
            return None

        curve_item = pg.PlotDataItem(
            x, trace.y, pen=pen,
            autoDownsample=False, clipToView=False, connect="finite",
        )
        self._view_box.addItem(curve_item)

        self._set_view_log_mode(x_rule, y_rule)
        curve_item.setLogMode(x_rule.logarithmic, y_rule.logarithmic)
        self._fit_y_range([trace.y], y_rule)
        self._take_sync_baselines()

        legend = self._plot_widget.plotItem.legend
        if legend is not None and in_legend:
            # Suffixed so a mixed accel+mic overlay reads unambiguously -- the
            # axis unit alone (Pa vs g) is not a reliable enough cue once two
            # physical domains share one graph.
            legend.addItem(curve_item, f"{trace.label}  ▸ right axis")
            self._legend_items.append(curve_item)
        return curve_item

    def apply_logarithmic_axes(self, x_rule: AxisScreenRule, y_rule: AxisScreenRule) -> None:
        """Follow a switch of log X / log Y (§1.276): the ViewBox and every
        curve on it take the primary axis' log mode, the Y range is fitted to
        the curves again in screen coordinates and the range sync starts from
        the new ranges. The switch only asks the primary ViewBox for an auto
        range, which it would otherwise run at the next paint and the sync
        would then project with the old linear range against the new log10 one,
        moving this range off the curve (#990). So the primary range is settled
        first; the fit then wins and both sync baselines are screen coordinates
        of the same rule. No axis: nothing to do."""
        if self._view_box is None:
            return
        self._plot_widget.plotItem.vb.updateAutoRange()
        self._set_view_log_mode(x_rule, y_rule)
        curves = [item for item in self._view_box.addedItems if isinstance(item, pg.PlotDataItem)]
        for curve_item in curves:
            curve_item.setLogMode(x_rule.logarithmic, y_rule.logarithmic)
        self._fit_y_range([curve_item.getOriginalDataset()[1] for curve_item in curves], y_rule)
        self._take_sync_baselines()

    def _set_view_log_mode(self, x_rule: AxisScreenRule, y_rule: AxisScreenRule) -> None:
        # The ViewBox uses its log mode only to bound the range it accepts.
        self._view_box.setLogMode("x", x_rule.logarithmic)
        self._view_box.setLogMode("y", y_rule.logarithmic)

    def _fit_y_range(self, ys: Sequence[Optional[np.ndarray]], y_rule: AxisScreenRule) -> None:
        """Fit the Y range to ``ys`` (native values) as they sit on screen."""
        # Finite only: an order cut legitimately carries NaN where the order is
        # unmeasurable, and on a log axis a value <= 0 has no screen position;
        # either would collapse the range.
        shown = [np.atleast_1d(y_rule.to_screen(y)) for y in ys if y is not None and len(y)]
        values = np.concatenate(shown) if shown else np.empty(0)
        finite_values = values[np.isfinite(values)]
        if not finite_values.size:
            return
        y_min = float(np.min(finite_values))
        y_max = float(np.max(finite_values))
        y_pad = (y_max - y_min) * 0.05 if y_max != y_min else 1.0
        self._is_syncing = True
        self._view_box.setYRange(y_min - y_pad, y_max + y_pad, padding=0)
        self._is_syncing = False

    def _take_sync_baselines(self) -> None:
        self._p1_last_yrange = self._plot_widget.plotItem.vb.viewRange()[1]
        self._p2_last_yrange = self._view_box.viewRange()[1]

    def teardown(self) -> None:
        """Remove the axis, its ViewBox, its legend entries and its sync wiring.

        The ViewBox holds curves plot_widget.clear() cannot see, and the sync
        handlers are attached to the *primary* ViewBox, so rebuilding without
        disconnecting stacks another set on every switch of secondary unit --
        each one still driving a ViewBox nobody can see.
        """
        if self._view_box is None:
            return

        plot_item = self._plot_widget.plotItem

        for signal, handler in self._connections:
            try:
                signal.disconnect(handler)
            except (RuntimeError, TypeError):
                pass
        self._connections = []

        if plot_item.legend is not None:
            for curve_item in self._legend_items:
                plot_item.legend.removeItem(curve_item)
        self._legend_items = []

        self._view_box.clear()
        scene = plot_item.scene()
        if scene is not None:
            scene.removeItem(self._view_box)

        self._view_box = None
        self._unit = ""
        plot_item.hideAxis("right")
