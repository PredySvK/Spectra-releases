# =====================================================================
# FILE: gui/workspace/spectral_requests.py
# =====================================================================
"""
Controller orchestrating asynchronous spectral (1D), tracked waterfall (2D),
and dynamic Order Cut computations. Features strict sampling frequency validation.

Lives in gui/, not signal_processing/: this is Qt threading orchestration
(job dispatch, worker signals, when to fire a computation and how to get its
result back to the UI thread) plus an AppContext reference for logging --
both presentation-layer concerns. signal_processing/ stays free of Qt and of
AppContext; it holds dsp/ (pure numpy/scipy) and result_blocks.py (the
synchronous path this controller's jobs ultimately call into).

Dispatch goes through QtJobRunner's "interactive" lane (ADR 1.13), not
QThreadPool.globalInstance(): the global pool has no size cap of its own, so
running heavy numpy work on it alongside a QtJobRunner batch (e.g. Calculate &
Save Data) meant up to 2x CPU oversubscription -- exactly what the two lanes
exist to prevent (BUGS.md K2-threading). Each request carries
slot_key=f"spectral:{widget_tag}", so a second Refresh (or a channel switch)
on the same dock supersedes the first in the queue and shows a Cancel button
in the status bar; QtJobRunner drops a superseded step's result itself
(job.cancel_token.is_cancelled guards on_step), so the slot is the whole of
this class's answer to "is this result still current?" (ADR §1.84).
"""

from functools import partial
from typing import Optional
from PySide6.QtCore import QObject, Signal
from signal_processing.result_blocks import (
    compute_spectrum, compute_spectrogram, compute_order_cuts, compute_overall_level,
    build_overall_level_missing_line, TrackingScratch,
)
from core.data_block import NVHDataBlock
from core.dsp_configs import SpectrumConfig, SpectrogramConfig, OrderTrackingConfig, OverallLevelConfig


class SpectralRequests(QObject):
    # Every signal carries the widget_tag of the dock that made the request.
    # Results arrive seconds after they are asked for, by which time the user may
    # have switched tabs, so the tag is what keeps a result attached to its origin
    # instead of landing on whatever happens to be on screen.
    #
    # Emits: (widget_tag, NVHDataBlock)
    spectrum_ready = Signal(str, object)
    # Emits: (widget_tag, NVHDataBlock)
    waterfall_ready = Signal(str, object)
    # Emits: (widget_tag, list[NVHDataBlock])
    order_cuts_ready = Signal(str, list)
    # Emits: (widget_tag, NVHDataBlock)
    overall_level_ready = Signal(str, object)
    # Emits: (widget_tag, error_message)
    computation_failed = Signal(str, str)

    def __init__(self, app_context, job_manager):
        super().__init__()
        self.app_context = app_context
        self.job_manager = job_manager
        # One TrackingPlan bag for every dock: a click on another channel of the
        # same file (same tacho, same sweep) reuses the plan instead of
        # rebuilding it (#500, ADR §1.133).
        self._tracking = TrackingScratch()

    @staticmethod
    def _slot_key(widget_tag: str) -> str:
        return f"spectral:{widget_tag}"

    def forget(self, widget_tag: str) -> None:
        """
        Stops a closed dock's computation, if one is still running -- its
        result has nowhere to land. Called from Workspace.close_specific_tab.
        Safe for a tag never seen.
        """
        self.job_manager.cancel_slot(self._slot_key(widget_tag))

    def invalidate(self, widget_tag: str) -> None:
        """
        Supersedes any in-flight computation for a dock without dispatching a
        new one, by cancelling the job holding this dock's slot. A
        result-cache hit (analysis_tabs._orders_plot_cache_hit and its
        siblings) plots directly, bypassing request_*(), so without this a
        slow recompute for the previous FFT settings could land seconds later
        and overwrite the freshly plotted cached curves (audit 02, finding
        S3/3.2).
        """
        self.job_manager.cancel_slot(self._slot_key(widget_tag))

    def request_1d_spectrum(self, time_block: NVHDataBlock, config: SpectrumConfig,
                            widget_tag: str = "graph_dock"):
        """
        Submits result_blocks.compute_spectrum -- the same path a batch
        result set is built through (#103) -- rather than a raw DSP function
        with fs, window factors and Remove DC worked out here. The worker
        thread hands back a finished NVHDataBlock; the handler only has to
        emit it -- a superseded job never reaches it.
        """
        try:

            self.job_manager.submit(
                "1D Spectrum", fn=compute_spectrum,
                kwargs=dict(time_block=time_block, config=config),
                lane="interactive", slot_key=self._slot_key(widget_tag),
                on_step=lambda payload, _idx: self._on_1d_spectrum_finished(widget_tag, payload),
                on_error=lambda message, _idx: self._on_computation_failed(widget_tag, message),
            )
        except Exception as e:
            self._on_computation_failed(widget_tag, str(e))

    def request_tracked_waterfall(self, vib_block: NVHDataBlock, tacho_block: NVHDataBlock,
                                  config: SpectrogramConfig,
                                  widget_tag: str = "spectrogram_dock"):
        """Submits result_blocks.compute_spectrogram -- see request_1d_spectrum."""
        try:

            self.job_manager.submit(
                "2D Waterfall", fn=self._tracking.compute, args=(compute_spectrogram,),
                kwargs=dict(vib_block=vib_block, tacho_block=tacho_block, config=config),
                lane="interactive", slot_key=self._slot_key(widget_tag),
                on_step=lambda payload, _idx: self._on_tracked_waterfall_finished(widget_tag, payload),
                on_error=lambda message, _idx: self._on_computation_failed(widget_tag, message),
            )
        except Exception as e:
            self._on_computation_failed(widget_tag, str(e))

    def request_order_extraction(self, vib_block: NVHDataBlock, tacho_block: NVHDataBlock,
                                 config: OrderTrackingConfig,
                                 widget_tag: str = "graph_dock",
                                 with_overall_level: bool = False):
        """Submits result_blocks.compute_order_cuts -- see request_1d_spectrum.
        `with_overall_level` adds the Overall Level and Residual curves to the same computation (ADR §1.141)."""
        try:
            if tacho_block is None:
                raise ValueError("Tacho channel is strictly required for Order Tracking.")

            compute_fn = compute_order_cuts
            if with_overall_level:
                compute_fn = partial(compute_order_cuts, with_overall_level=True)

            def _on_step(payload, _idx):
                missing = build_overall_level_missing_line(payload) if with_overall_level else None
                if missing:
                    self.app_context.log(missing)
                self._on_order_extraction_finished(widget_tag, payload)

            self.job_manager.submit(
                "Order Cuts", fn=self._tracking.compute, args=(compute_fn,),
                kwargs=dict(vib_block=vib_block, tacho_block=tacho_block, config=config),
                lane="interactive", slot_key=self._slot_key(widget_tag),
                on_step=_on_step,
                on_error=lambda message, _idx: self._on_computation_failed(widget_tag, message),
            )
        except Exception as e:
            self._on_computation_failed(widget_tag, str(e))

    def request_overall_level(self, vib_block: NVHDataBlock, tacho_block: Optional[NVHDataBlock],
                              config: OverallLevelConfig,
                              widget_tag: str = "graph_dock"):
        """Submits result_blocks.compute_overall_level -- see request_1d_spectrum."""
        try:
            if config.tracking_mode == "rpm" and tacho_block is None:
                raise ValueError("Tacho channel is strictly required for Overall Level tracked against RPM.")


            self.job_manager.submit(
                "Overall Level", fn=self._tracking.compute, args=(compute_overall_level,),
                kwargs=dict(vib_block=vib_block, tacho_block=tacho_block, config=config),
                lane="interactive", slot_key=self._slot_key(widget_tag),
                on_step=lambda payload, _idx: self._on_overall_level_finished(widget_tag, payload),
                on_error=lambda message, _idx: self._on_computation_failed(widget_tag, message),
            )
        except Exception as e:
            self._on_computation_failed(widget_tag, str(e))

    # The three handlers below get a finished NVHDataBlock (or, for order cuts,
    # a list of them) straight from result_blocks and only have to emit it -- unlike the raw DSP payload this used to unpack,
    # nothing here re-derives the unit, the name, or the metadata a second time.

    def _on_1d_spectrum_finished(self, widget_tag, spectral_block):
        self.spectrum_ready.emit(widget_tag, spectral_block)

    def _on_tracked_waterfall_finished(self, widget_tag, spectrogram_block):
        self.waterfall_ready.emit(widget_tag, spectrogram_block)

    def _on_order_extraction_finished(self, widget_tag, blocks):
        self.order_cuts_ready.emit(widget_tag, blocks)

    def _on_overall_level_finished(self, widget_tag, block):
        self.overall_level_ready.emit(widget_tag, block)

    def _on_computation_failed(self, widget_tag, error_message):
        self.computation_failed.emit(widget_tag, error_message)
