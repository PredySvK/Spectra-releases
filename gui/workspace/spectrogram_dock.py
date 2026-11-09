# =====================================================================
# FILE: gui/workspace/spectrogram_dock.py
# =====================================================================
import uuid
from dataclasses import replace
import pyqtgraph as pg
import numpy as np
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtCore import Qt
from typing import Optional

from core.benchmark import benchmark_step
from core.axis_projections import X_AXIS_NATIVE
from core.evaluation import EvaluationConfig
from core.data_block import NVHDataBlock
from core.models import MeasurementRunIndex, ChannelMetadata
from gui.workspace.plot_title import set_plot_title
from gui.workspace.channel_drop_target import ChannelDropTargetMixin
from gui.workspace.cursor import SpectrogramCursorMixin
from core.units import UnitPreferences
from gui.workspace.display_prefix_axis import DisplayPrefixAxisItem
from gui.workspace.plot_area import style_plot_area
from gui.workspace.workspace_dock import WorkspaceDock
from orchestration.channel_drop import PendingDrops
from view_models.analysis_kinds import ANALYSIS_SPECTROGRAM
from view_models.plot import (
    DisplaySettings,
    DrawnSpectrogram,
    GraphSpectrogram,
    SpectrogramModel,
    build_drawn_spectrogram,
    resolve_display_settings,
)


class SpectrogramDock(ChannelDropTargetMixin, SpectrogramCursorMixin, WorkspaceDock):

    def __init__(self, parent=None, app_context=None):
        super().__init__(parent)

        self.app_context = app_context

        # See GraphDock.dock_id: identifies this dock across an asynchronous
        # round trip so a waterfall lands where it was requested.
        self.dock_id: str = f"spectrogram-{uuid.uuid4().hex}"
        # See GraphDock.analysis_kind. A spectrogram only ever shows one thing.
        self.analysis_kind: str = ANALYSIS_SPECTROGRAM
        self.run_index: Optional[MeasurementRunIndex] = None
        self.channel_meta: Optional[ChannelMetadata] = None
        self.vib_block: Optional[NVHDataBlock] = None
        # The spectrogram this dock holds. Every change ends
        # in _on_spectrogram_changed, the one place it reaches the screen.
        self.spectrogram = GraphSpectrogram(on_change=self._on_spectrogram_changed)
        # The spectrogram as it is on screen; the Cursor reads this same one (#893).
        self.drawn_spectrogram: Optional[DrawnSpectrogram] = None
        self.tacho_block: Optional[NVHDataBlock] = None
        self.pending_drops = PendingDrops()

        # Evaluation configuration.
        self.evaluation_config: EvaluationConfig = EvaluationConfig()

        self.setAcceptDrops(True)
        self.init_ui()

    def _unit_preferences(self) -> UnitPreferences:
        if self.app_context is not None and hasattr(self.app_context, "unit_preferences"):
            return self.app_context.unit_preferences()
        return UnitPreferences()

    @property
    def color_bar_axis(self) -> DisplayPrefixAxisItem:
        return self.lut_widget.item.axis

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.plot_widget = pg.PlotWidget(
            axisItems={
                "bottom": DisplayPrefixAxisItem("bottom", unit_preferences_provider=self._unit_preferences),
                "left": DisplayPrefixAxisItem("left", unit_preferences_provider=self._unit_preferences),
            }
        )
        style_plot_area(self.plot_widget)

        left_axis = self.plot_widget.getAxis('left')
        left_axis.setLabel('Frequency', 'Hz')

        self.plot_widget.getViewBox().disableAutoRange()
        layout.addWidget(self.plot_widget)

        self.image_item = pg.ImageItem()
        self.plot_widget.addItem(self.image_item)

        self.lut_widget = pg.HistogramLUTWidget()
        self.lut_widget.setImageItem(self.image_item)
        self.lut_widget.setFixedWidth(100)
        item = self.lut_widget.item
        item.layout.removeItem(item.axis)
        item.axis = DisplayPrefixAxisItem(
            'left',
            unit_preferences_provider=self._unit_preferences,
            linkView=item.vb,
            maxTickLength=-10,
            parent=item,
        )
        item.layout.addItem(item.axis, 0, 0)
        layout.addWidget(self.lut_widget)

        pos = np.array([0.0, 0.11, 0.34, 0.65, 0.89, 1.0])
        color = np.array([
            [0, 0, 127, 255],
            [0, 0, 255, 255],
            [0, 255, 255, 255],
            [255, 255, 0, 255],
            [255, 0, 0, 255],
            [127, 0, 0, 255]
        ], dtype=np.ubyte)

        jet_colormap = pg.ColorMap(pos, color)
        self.lut_widget.gradient.setColorMap(jet_colormap)
        self._init_cursor()
        self._disable_logarithmic_axes()

    def _disable_logarithmic_axes(self) -> None:
        """No Logarithmic axis on a spectrogram (§1.276): the image is a
        uniform grid, so a log axis would move the axis and leave the picture.
        A non-checkable box ignores setChecked too, so neither a click nor
        setLogMode can switch the plot library into log mode."""
        ctrl = self.plot_widget.plotItem.ctrl
        for box in (ctrl.logXCheck, ctrl.logYCheck):
            box.setCheckable(False)
            box.setEnabled(False)

    def visible_traces(self) -> list:
        """
        Deliberate empty list: a spectrogram has no ``traces`` to mask (ADR
        §1.7, it is one ``ImageItem``, not a curve list). The Evaluation card's
        dock adapter reads `canonical_block()` instead for
        this dock -- Typed orders (#141) and Dominant orders (#142) are the
        Evaluations meant to read a spectrogram, and neither goes through a
        curve list.
        """
        return []

    def all_traces(self) -> list:
        """Deliberate empty list, same reasoning as `visible_traces` -- the
        dock adapter's input when Evaluation's "Respect Trace filter" toggle
        (issue #136) is off gets nothing from a spectrogram either. A
        spectrogram has no per-trace mask to respect in the first place."""
        return []

    def canonical_block(self) -> Optional[NVHDataBlock]:
        """
        The current waterfall's canonical block, publicly -- the
        Evaluation card's dock adapter reads
        this instead of `visible_traces()` for a dock whose content is one
        block rather than a curve list. None before the first waterfall lands.
        """
        return self.spectrogram.block

    def _on_spectrogram_changed(self, model: SpectrogramModel) -> None:
        """
        Draw a SpectrogramModel -- the one place a waterfall is put on screen.

        The dB/log colour transform already happened in the builder; this only
        lays the given matrix onto the image and locks the view to it.
        """

        # Both axes follow the global X axis unit (issue #459): the frequency
        # axis on the left, the bottom one when it is speed. The model keeps
        # its native values; only what is drawn is rescaled (§1.130).
        x_axis_unit = self.app_context.unit_preferences().x_axis_unit if self.app_context else X_AXIS_NATIVE
        with benchmark_step("draw"):
            self.draw_spectrogram(build_drawn_spectrogram(model, x_axis_unit))

    def apply_x_axis_unit(self) -> None:
        """Redraw the held waterfall for a changed global X axis unit."""
        model = self.spectrogram.model
        if model is not None:
            self._on_spectrogram_changed(model)

    def apply_unit_preferences(self) -> None:
        """Rebuild the held waterfall in the changed global units (its colour
        values follow the Display unit, #947) -- in memory, no STFT re-run --
        or, with nothing held, update the axes' and colour bar's display prefixes."""
        if self.spectrogram.model is not None:
            self.rebuild_with_display_settings()
        else:
            self.plot_widget.getAxis('left').update_display_prefix()
            self.plot_widget.getAxis('bottom').update_display_prefix()
            self.color_bar_axis.update_display_prefix()
            self.refresh_cursor_box()

    def _display_settings(self) -> DisplaySettings:
        """The one place this dock reads app_context for how its waterfall is
        shown -- the spectrogram tab's Format, Amplitude and Color scale (#833)."""
        return resolve_display_settings(
            self.analysis_kind,
            prefs=self._unit_preferences(),
            spectrogram=getattr(self.app_context, "spectrogram_settings", None),
        )

    def plot_block(self, block: NVHDataBlock) -> None:
        """Shows ``block`` as this dock's waterfall, in this dock's display settings."""
        self._clear_cursor()
        self.spectrogram.show_block(block, self._display_settings())

    def rebuild_with_display_settings(
        self,
        spectrum_format: Optional[str] = None,
        amplitude_mode: Optional[str] = None,
        color_scale: Optional[str] = None,
        decibel_scale: Optional[bool] = None,
    ) -> None:
        """
        Re-scales the SpectrogramModel on the fly from its canonical block.
        Runs synchronously in < 1 ms without re-running STFT or background jobs.
        The settings are this dock's own (_display_settings); an argument only
        overrides one of them.
        """
        overrides = {"spectrum_format": spectrum_format,
                     "spectrum_amplitude_mode": amplitude_mode,
                     "color_scale": color_scale,
                     "decibel_scale": decibel_scale}
        self.spectrogram.rebuild_display(replace(
            self._display_settings(), **{k: v for k, v in overrides.items() if v is not None}))

    def draw_spectrogram(self, drawn: DrawnSpectrogram) -> None:
        """Put ``drawn`` on screen as given -- axes ascending, units decided (#893)."""
        self.drawn_spectrogram = drawn
        left_axis = self.plot_widget.getAxis('left')
        bottom_axis = self.plot_widget.getAxis('bottom')
        left_axis.set_quantity("frequency")
        bottom_axis.set_quantity(drawn.x_quantity)
        left_axis.setLabel(drawn.y_label, drawn.y_unit)
        bottom_axis.setLabel(text=drawn.x_label, units=drawn.x_unit)

        self.image_item.setImage(drawn.z.T, autoLevels=True)
        x_lo, x_hi = drawn.x_extent
        y_lo, y_hi = drawn.y_extent
        self.image_item.setRect(pg.QtCore.QRectF(x_lo, y_lo, x_hi - x_lo, y_hi - y_lo))

        self.color_bar_axis.setLabel(units=drawn.z_unit)
        self.lut_widget.setLevels(float(drawn.z.min()), float(drawn.z.max()))

        t_min, t_max = float(drawn.x[0]), float(drawn.x[-1])
        f_min, f_max = float(drawn.y[0]), float(drawn.y[-1])
        if t_max <= t_min: t_max = t_min + 1.0
        if f_max <= f_min: f_max = f_min + 1.0
        self.plot_widget.getViewBox().disableAutoRange()
        self.plot_widget.setXRange(t_min, t_max, padding=0.0)
        self.plot_widget.setYRange(f_min, f_max, padding=0.0)
        set_plot_title(self.plot_widget, drawn.title)
        self.refresh_cursor_box()
