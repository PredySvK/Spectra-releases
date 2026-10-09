# =====================================================================
# FILE: gui/workspace/live_order_results.py
# =====================================================================
"""
Background compute for channels dropped live onto a result-content dock
(ARCHITECTURE_DECISIONS §1.30, see gui.handlers.live_channel_drop.
LiveChannelDropHandler). Mirrors the Qt threading
orchestration workflow_run_bridge.py and spectral_requests.py already
use around signal_processing: this owns the live-result cache and Qt signal
bridge, while QtJobRunner owns queueing and task bookkeeping. It never owns the
DSP math itself, which stays in signal_processing/.

A cache miss here used to run DataAccessor.fetch_channel_data (disk I/O) and
compute_order_cuts (FFT + order tracking) straight on the GUI thread inside
the drop handler, freezing the app on a large source file. Both now happen on
a worker thread; the drop handler only ever sees a result that is already
there or dispatches a request and moves on.

The result-set cache lookup moved onto this worker too (ADR §1.54, issue #84):
the drop handler no longer asks the cache synchronously (an HDF5 read on the
GUI thread) and no longer shows a "compute this? [Yes]/[No]" dialog on a miss.
The worker body asks the cache first -- via the hardcoded-write_index=False
background entry point -- and rebuilds the blocks from the stored amplitudes on
a hit, or computes them on a miss; either way the verdict arrives through the
same channel_ready callback.
"""
import os
from contextlib import contextmanager
from typing import Optional

from PySide6.QtCore import QObject, Signal

from core.dsp_configs import OrderTrackingConfig
from core.jobs import JobRecord, job_step
from orchestration.channel_drop import ResultContentMemoKey
from orchestration.jobs import JobRunner
from orchestration.live_compute import LiveOrderMemo, lookup_or_compute_order_cuts


class LiveOrderResults(QObject):
    # Emitted once per finished task, success or failure. Carries no payload --
    # by the time a background task lands, the dock it was requested for may
    # have closed, so the caller (main_window.py's settle timer, via
    # gui.handlers.live_channel_drop.LiveChannelDropHandler.refresh_pending) re-derives
    # what is actually still wanted from every open dock's own pending list,
    # rather than being handed a result it would otherwise have to decide
    # whether to discard.
    channel_ready = Signal()

    def __init__(self, app_context, job_manager: JobRunner):
        super().__init__()
        self.app_context = app_context
        self.job_manager = job_manager
        # LRU memo, pending tags and the shared TrackingPlan bag (#99), never
        # written to disk -- persisting live-computed results is the batch save
        # workflow's job.
        self._memo = LiveOrderMemo()
        self._batch = None
        self._slots = set()

    def reset(self) -> None:
        """
        Drops every memoized result and pending-task bookkeeping.

        The key now carries the source file's size/mtime, so a re-measured file
        no longer needs this to avoid a stale hit; what this still does is drop
        results for files that are leaving the pool entirely. Called wherever a
        workspace directory or a project is (re)loaded -- see
        ProjectDocumentHandler.load_directory_into_workspace and load_project_pool.
        In-flight jobs are cancelled through their slots. QtJobRunner drops
        results from cancelled jobs, and the memo forgetting their tags also
        protects the direct-handler path used by tests.
        """
        self._memo.reset()
        for slot in list(self._slots):
            self.job_manager.cancel_slot(slot)

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
        plan_scratch = self._memo.plan_scratch_for(
            key.file_path, key.size, key.mtime_ns, getattr(tacho_meta, "index", None), config)
        item = (tag, key, run, tacho_meta, channel_meta, config, plan_scratch)
        if self._batch is not None:
            self._batch[1].append(item)
        else:
            self._submit(None, [item])

    def _submit(self, label: Optional[str], items: list) -> None:
        """One job for `items`; a lone channel keeps its own label and stays quiet."""
        tags = [item[0] for item in items]
        steps = []
        for tag, key, run, tacho_meta, channel_meta, config, plan_scratch in items:
            # The cache is keyed under the channel's own name; channel_meta.index
            # (passed along inside) tells two same-named channels apart.
            step_label = f"Order tracking — {channel_meta.name} ({os.path.basename(key.file_path)})"
            steps.append(job_step(
                step_label, lookup_or_compute_order_cuts,
                self.app_context.project_session, run, tacho_meta,
                channel_meta, channel_meta.name, config, key.use_cache,
                plan_scratch=plan_scratch,
            ))
        slot = self._slot_key(tags[0])
        self._slots.add(slot)
        try:
            self.job_manager.submit(
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

    def _on_finished(self, tag: str, payload) -> None:
        order_blocks, result_set_label = payload
        entry = self._memo.finish(tag, order_blocks)
        if entry is None:
            return
        _, channel_name = entry
        if result_set_label is not None:
            # The hit/miss verdict lands on the GUI thread here (ADR §1.54); the
            # single-dock path logs the same "no recompute" line.
            self.app_context.log(
                f"PROJECT: Live channel '{channel_name}' loaded from result set "
                f"'{result_set_label}' -- FFT settings unchanged, no recompute needed."
            )
        self.channel_ready.emit()

    def _on_error(self, tag: str, message: str) -> None:
        entry = self._memo.release(tag)
        if entry is not None:
            key, channel_name = entry
            self.app_context.log(
                f"ERROR: Apply (live) failed for '{channel_name}' in '{key.file_path}': {message}"
            )
        self.channel_ready.emit()
