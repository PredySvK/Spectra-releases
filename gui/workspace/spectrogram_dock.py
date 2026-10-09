# =====================================================================
# FILE: gui/workspace/spectrogram_dock.py
# =====================================================================
import uuid
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
from orchestration.channel_drop import PendingDrops
from view_models.analysis_kinds import ANALYSIS_SPECTROGRAM
from view_models.plot import GraphSpectrogram, SpectrogramModel


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
        # The spectrogram this dock holds (ADR §1.7, #301). Every change ends
        # in _on_spectrogram_changed, the one place it reaches the screen.
        self.spectrogram = GraphSpectrogram(on_change=self._on_spectrogram_changed)
        self.tacho_block: Optional[NVHDataBlock] = None
        self.pending_drops = PendingDrops()

        # Evaluation configuration (ADR §1.64 point 1, issue #138).
        self.evaluation_config: EvaluationConfig = EvaluationConfig()

        self.setAcceptDrops(True)
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.plot_widget = pg.PlotWidget()

        bottom_axis = self.plot_widget.getAxis('bottom')
        bottom_axis.enableAutoSIPrefix(False)
        bottom_axis.autoSIPrefix = False

        left_axis = self.plot_widget.getAxis('left')
        left_axis.setLabel('Frequency', 'Hz')
        left_axis.enableAutoSIPrefix(False)
        left_axis.autoSIPrefix = False

        self.plot_widget.getViewBox().disableAutoRange()
        layout.addWidget(self.plot_widget)

        self.image_item = pg.ImageItem()
        self.plot_widget.addItem(self.image_item)

        self.lut_widget = pg.HistogramLUTWidget()
        self.lut_widget.setImageItem(self.image_item)
        self.lut_widget.setFixedWidth(100)
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
        dock adapter (ADR §1.64 point 3) reads `canonical_block()` instead for
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
        The current waterfall's canonical block (ADR §1.60), publicly -- the
        Evaluation card's dock adapter (ADR §1.64 point 3, issue #141) reads
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
        self.plot_widget.getAxis('left').setLabel(frequency_axis.label, frequency_axis.unit)
        with benchmark_step("draw"):
            self.render_spectrogram_matrix(
                model.freqs * frequency_axis.scale, model.zvals * bottom_axis.scale, model.image,
                z_label=model.z_label, z_unit=z_unit,
            )
        self.plot_widget.setTitle(model.title)

    def apply_x_axis_unit(self) -> None:
        """Redraw the held waterfall for a changed global X axis unit."""
        model = self.spectrogram.model
        if model is not None:
            self._on_spectrogram_changed(model)

    def rebuild_with_display_settings(
        self,
        spectrum_format: Optional[str] = None,
        amplitude_mode: Optional[str] = None,
        color_scale: Optional[str] = None,
        decibel_scale: Optional[bool] = None,
    ) -> None:
        """
        Re-scales the SpectrogramModel on the fly from its canonical block (ADR §1.60).
        Runs synchronously in < 1 ms without re-running STFT or background jobs.
        """
        cfg = getattr(self.app_context, "spectrogram_settings", None) if self.app_context else None
        self.spectrogram.rebuild_display(
            color_scale=color_scale if color_scale is not None else getattr(cfg, "color_scale", "Linear"),
            spectrum_format=spectrum_format if spectrum_format is not None else getattr(cfg, "spectrum_format", "linear"),
            amplitude_mode=amplitude_mode if amplitude_mode is not None else getattr(cfg, "amplitude_mode", "rms"),
            decibel_scale=decibel_scale,
        )

    @staticmethod
    def _axis_extent(values, v_min: float, v_max: float) -> tuple[float, float]:
        n = len(values)
        span = v_max - v_min
        if n > 1 and span > 0:
            step = span / (n - 1)
            return v_min - step / 2.0, span + step
        return v_min - 0.5, 1.0

    def render_spectrogram_matrix(self, frequencies, times, magnitude_matrix, z_label="Time", z_unit="s"):
        if len(times) > 1 and times[0] > times[-1]:
            times = times[::-1]
            magnitude_matrix = magnitude_matrix[:, ::-1]

        self.image_item.setImage(magnitude_matrix.T, autoLevels=True)

        t_min, t_max = float(np.min(times)), float(np.max(times))
        f_min, f_max = float(np.min(frequencies)), float(np.max(frequencies))

        rect_x, rect_w = self._axis_extent(times, t_min, t_max)
        rect_y, rect_h = self._axis_extent(frequencies, f_min, f_max)

        rect = pg.QtCore.QRectF(rect_x, rect_y, rect_w, rect_h)
        self.image_item.setRect(rect)

        if t_max <= t_min: t_max = t_min + 1.0
        if f_max <= f_min: f_max = f_min + 1.0

        bottom_axis = self.plot_widget.getAxis('bottom')
        bottom_axis.setLabel(f"{z_label} [{z_unit}]", units=None)
        bottom_axis.enableAutoSIPrefix(False)
        bottom_axis.autoSIPrefix = False
        bottom_axis.setScale(1.0)

        self.lut_widget.setLevels(float(magnitude_matrix.min()), float(magnitude_matrix.max()))
        self.plot_widget.getViewBox().disableAutoRange()
        self.plot_widget.setXRange(t_min, t_max, padding=0.0)
        self.plot_widget.setYRange(f_min, f_max, padding=0.0)
