# =====================================================================
# FILE: gui/workspace/spectrogram_dock.py
# =====================================================================
import uuid
from dataclasses import replace
import pyqtgraph as pg
import numpy as np
from PySide6.QtWidgets import QWidget, QHBoxLayout
from PySide6.QtCore import Qt
from typing import Optional

from core.benchmark import benchmark_step
from core.axis_projections import X_AXIS_NATIVE, resolve_x_axis_display
from core.evaluation import EvaluationConfig
from core.data_block import NVHDataBlock
from core.models import MeasurementRunIndex, ChannelMetadata
from gui.workspace.channel_drop_target import ChannelDropTargetMixin
from gui.workspace.cursor import SpectrogramCursorMixin
from core.units import UnitPreferences
from gui.workspace.display_prefix_axis import DisplayPrefixAxisItem
from gui.workspace.plot_area import style_plot_area
from orchestration.channel_drop import PendingDrops
from view_models.analysis_kinds import ANALYSIS_SPECTROGRAM
from view_models.plot import (
    DisplaySettings,
    GraphSpectrogram,
    SpectrogramModel,
    resolve_display_settings,
    resolve_image_axis_extent,
)


class SpectrogramDock(ChannelDropTargetMixin, SpectrogramCursorMixin, QWidget):

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
        self.hide_cursor_box()
        # Both axes follow the global X axis unit (issue #459): the frequency
        # axis on the left, the bottom one when it is speed. The model keeps
        # its native values; only what is drawn is rescaled.
        x_axis_unit = self.app_context.unit_preferences().x_axis_unit if self.app_context else X_AXIS_NATIVE
        frequency_axis = resolve_x_axis_display("frequency", x_axis_unit)
        bottom_axis = resolve_x_axis_display(model.z_quantity, x_axis_unit)
        z_unit = bottom_axis.unit if bottom_axis.scale != 1.0 else model.z_unit
        self.plot_widget.getAxis('left').set_quantity("frequency")
        self.plot_widget.getAxis('bottom').set_quantity(model.z_quantity)
        self.plot_widget.getAxis('left').setLabel(frequency_axis.label, frequency_axis.unit)
        color_scale = getattr(model, "color_scale", "") or ""
        if "dB" in color_scale:
            mag_unit = "dB"
        else:
            block = getattr(model, "block", None)
            mag_unit = getattr(model, "value_unit", "") or getattr(block, "value_unit", "")
        with benchmark_step("draw"):
            self.render_spectrogram_matrix(
                model.freqs * frequency_axis.scale, model.zvals * bottom_axis.scale, model.image,
                z_label=model.z_label, z_unit=z_unit, mag_unit=mag_unit,
            )
        self.plot_widget.setTitle(model.title)

    def apply_x_axis_unit(self) -> None:
        """Redraw the held waterfall for a changed global X axis unit."""
        model = self.spectrogram.model
        if model is not None:
            self._on_spectrogram_changed(model)

    def apply_unit_preferences(self) -> None:
        """Update axes and colour bar display prefixes when unit preferences change."""
        model = self.spectrogram.model
        if model is not None:
            self._on_spectrogram_changed(model)
        else:
            self.plot_widget.getAxis('left').update_display_prefix()
            self.plot_widget.getAxis('bottom').update_display_prefix()
            self.color_bar_axis.update_display_prefix()

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

    def render_spectrogram_matrix(self, frequencies, times, magnitude_matrix, z_label="Time", z_unit="s", mag_unit: str = ""):
        if len(times) > 1 and times[0] > times[-1]:
            times = times[::-1]
            magnitude_matrix = magnitude_matrix[:, ::-1]
        if len(frequencies) > 1 and frequencies[0] > frequencies[-1]:
            frequencies = frequencies[::-1]
            magnitude_matrix = magnitude_matrix[::-1, :]

        self.image_item.setImage(magnitude_matrix.T, autoLevels=True)

        t_min, t_max = float(np.min(times)), float(np.max(times))
        f_min, f_max = float(np.min(frequencies)), float(np.max(frequencies))

        x_lo, x_hi = resolve_image_axis_extent(times)
        y_lo, y_hi = resolve_image_axis_extent(frequencies)
        rect = pg.QtCore.QRectF(x_lo, y_lo, x_hi - x_lo, y_hi - y_lo)
        self.image_item.setRect(rect)

        if t_max <= t_min: t_max = t_min + 1.0
        if f_max <= f_min: f_max = f_min + 1.0

        bottom_axis = self.plot_widget.getAxis('bottom')
        bottom_axis.setLabel(text=z_label, units=z_unit)

        self.color_bar_axis.setLabel(units=mag_unit)
        self.lut_widget.setLevels(float(magnitude_matrix.min()), float(magnitude_matrix.max()))
        self.plot_widget.getViewBox().disableAutoRange()
        self.plot_widget.setXRange(t_min, t_max, padding=0.0)
        self.plot_widget.setYRange(f_min, f_max, padding=0.0)
