# =====================================================================
# FILE: gui/workspace/live_order_results.py
# =====================================================================
"""
Background compute for channels dropped live onto a result-content dock
(ARCHITECTURE_DECISIONS §1.30, see gui.handlers.live_channel_drop.
LiveChannelDropHandler). Mirrors the Qt threading orchestration
workflow_run_bridge.py already uses around signal_processing: this owns the
live-result cache and Qt signal bridge, while QtJobRunner owns queueing and
task bookkeeping. It never owns the DSP math itself, which stays in
signal_processing/.

A cache miss here used to run DataAccessor.fetch_channel_data (disk I/O) and
compute_order_cuts (FFT + order tracking) straight on the GUI thread inside
the drop handler, freezing the app on a large source file. Both now happen on
a worker thread; the drop handler only ever sees a result that is already
there or dispatches a request and moves on.

The result-set cache lookup moved onto this worker too:
the drop handler no longer asks the cache synchronously (an HDF5 read on the
GUI thread) and no longer shows a "compute this? [Yes]/[No]" dialog on a miss.
Each channel is one `live_compute.run_live_compute` step: it asks
the cache first -- via the hardcoded-write_index=False background entry point --
and rebuilds the blocks from the stored amplitudes on a hit without reading the
channel, or reads and computes them on a miss; either way the verdict arrives
through the same channel_ready callback.
"""
import os
from contextlib import contextmanager
from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.block_kinds import KIND_ORDER_CUT
from core.dsp_configs import OrderTrackingConfig
from core.jobs import JobRecord, job_step
from orchestration.channel_drop import ResultContentMemoKey
from orchestration.jobs import JobRunner
from orchestration.live_compute import (
    LiveFailure, LiveOrderMemo, LiveRequest, build_cache_hit_line, resolve_cache_finder, run_live_compute,
)
from signal_processing.result_blocks import TrackingScratch


class LiveOrderResults(QObject):
    # Emitted once per finished task, success or failure. Carries no payload --
    # by the time a background task lands, the dock it was requested for may
    # have closed, so the caller (main_window.py's settle timer, via
    # gui.handlers.live_channel_drop.LiveChannelDropHandler.refresh_pending) re-derives
    # what is actually still wanted from every open dock's own pending list,
    # rather than being handed a result it would otherwise have to decide
    # whether to discard.
    channel_ready = Signal()

    def __init__(self, app_context, job_runner: JobRunner):
        super().__init__()
        self.app_context = app_context
        self.job_runner = job_runner
        # LRU memo and pending tags, never written to disk -- persisting
        # live-computed results is the batch save workflow's job.
        self._memo = LiveOrderMemo()
        # One TrackingPlan bag for every job: N channels dropped from one file
        # are N steps, and this is what lets them build one plan between them
        # (#99). It keeps the latest tacho's plan only.
        self._tracking = TrackingScratch()
        self._batch = None
        self._slots = set()

    def reset(self) -> None:
        """
        Drops every memoized result and pending-task bookkeeping.

        The key now carries the source file's size/mtime, so a re-measured file
        no longer needs this to avoid a stale hit; what this still does is drop
        results for files that are leaving the pool entirely. Called wherever a
        project is (re)loaded, a dropped data folder included -- see the
        project swap (orchestration.project_swap).
        In-flight jobs are cancelled through their slots. QtJobRunner drops
        results from cancelled jobs, and the memo forgetting their tags also
        protects the direct-handler path used by tests.
        """
        self._memo.reset()
        self._tracking = TrackingScratch()
        for slot in list(self._slots):
            self.job_runner.cancel_slot(slot)

    @staticmethod
    def _slot_key(tag: str) -> str:
        return f"live-order:{tag}"

    def result_for(self, key: ResultContentMemoKey) -> Optional[list]:
        return self._memo.result_for(key)

    def is_pending(self, key: ResultContentMemoKey) -> bool:
        return self._memo.is_pending(key)

    @contextmanager
    def batch(self, label: str):
        """Requests made inside this block become one job, one step per channel (#468)."""
        self._batch = (label, [])
        try:
            yield
        finally:
            _, items = self._batch
            self._batch = None
            if items:
                self._submit(label if len(items) > 1 else None, items)

    def request(self, key: ResultContentMemoKey, run, tacho_meta, channel_meta,
                config: OrderTrackingConfig) -> None:
        """No-op if this key already has a result or is already in flight."""
        tag = self._memo.begin(key, channel_meta.name)
        if tag is None:
            return
        item = (tag, key, LiveRequest(
            run_index=run, channel_meta=channel_meta, block_kind=KIND_ORDER_CUT,
            config=config, tacho_meta=tacho_meta))
        if self._batch is not None:
            self._batch[1].append(item)
        else:
            self._submit(None, [item])

    def _submit(self, label: Optional[str], items: list) -> None:
        """One job for `items`; a lone channel keeps its own label and stays quiet."""
        tags = [item[0] for item in items]
        session = getattr(self.app_context, "project_session", None)
        steps = []
        for _tag, key, request in items:
            finder = resolve_cache_finder(session, key.use_cache)
            step_label = (f"Order tracking — {request.channel_meta.name} "
                          f"({os.path.basename(key.file_path)})")
            steps.append(job_step(
                step_label, run_live_compute, request, finder, self._tracking))
        slot = self._slot_key(tags[0])
        self._slots.add(slot)
        try:
            self.job_runner.submit(
                label or steps[0][0],
                steps=steps,
                lane="interactive",
                slot_key=slot,
                quiet=len(items) == 1,
                on_step=lambda payload, index: self._on_finished(tags[index], payload),
                on_error=lambda message, index: self._on_error(tags[index], message),
                on_done=lambda record: self._on_done(tags, slot, record),
            )
        except Exception as error:
            self._slots.discard(slot)
            for tag in tags:
                self._memo.release(tag)
            self.app_context.log(
                f"ERROR: Apply (live) failed for {len(items)} channel(s) "
                f"in '{items[0][1].file_path}': {error}"
            )
            self.channel_ready.emit()

    def _on_done(self, tags: list, slot: str, record: Optional[JobRecord] = None) -> None:
        self._slots.discard(slot)
        # Tags still pending: the job was cancelled or superseded before their step
        # ran (#381). Releasing lets the channel be requested again and wakes docks.
        if any([self._memo.release(tag) for tag in tags]):
            self.channel_ready.emit()

    def _on_finished(self, tag: str, result) -> None:
        for line in result.notices:
            self.app_context.log(line)
        if isinstance(result, LiveFailure):
            self._on_error(tag, result.message)
            return
        entry = self._memo.finish(tag, list(result.blocks))
        if entry is None:
            return
        _, channel_name = entry
        if result.from_cache:
            # The hit/miss verdict lands on the GUI thread here; the
            # single-dock path logs the same "no recompute" line.
            self.app_context.log(build_cache_hit_line(
                f"Live channel '{channel_name}'", result.result_set_label))
        self.channel_ready.emit()

    def _on_error(self, tag: str, message: str) -> None:
        entry = self._memo.release(tag)
        if entry is not None:
            key, channel_name = entry
            self.app_context.log(
                f"ERROR: Apply (live) failed for '{channel_name}' in '{key.file_path}': {message}"
            )
        self.channel_ready.emit()
