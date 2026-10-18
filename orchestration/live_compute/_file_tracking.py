"""Each source file's own tacho block and TrackingPlan bag inside one worker call."""

import dataclasses
from typing import Callable, Optional

from orchestration.live_compute._live_result import LiveResult, run_live_compute
from signal_processing.result_blocks import TrackingScratch


class FileTracking:
    """
    The per-file tracking context one batch worker carries across its channels.

    A dropped or overlaid batch routinely spans several files. Tracking file B's
    vibration against file A's speed profile is silently wrong rather than an
    error (compute_order_cuts only checks sample count, which files from one
    test campaign share), so the tacho is read once PER FILE and never lent to
    another. The TrackingPlan bag is per file for the same reason: its channels
    build one TrackingPlan between them (#99), and another file builds its own.

    Lives for one worker call only, so it keeps every file it met -- unlike
    the cross-job bag a live view keeps, which holds only the latest.
    """

    def __init__(self):
        self._tacho_by_path: dict = {}
        self._tracking_by_path: dict = {}

    def seed_tacho(self, file_path, tacho_block) -> None:
        """Reuse a tacho block the dock already holds for `file_path`."""
        if tacho_block is not None:
            self._tacho_by_path[file_path] = tacho_block

    def run(self, request, finder: Optional[Callable] = None):
        """
        `run_live_compute` for one channel of this batch: its file's tacho, once
        read, is handed to the next channel of that file, and every channel of
        a file computes with that file's TrackingScratch. A hit reads nothing,
        so the tacho is read by the first miss of a file, not up front.
        """
        file_path = request.run_index.file_path
        tacho_block = self._tacho_by_path.get(file_path)
        if tacho_block is not None and request.tacho_block is None:
            request = dataclasses.replace(request, tacho_block=tacho_block)
        tracking = self._tracking_by_path.setdefault(file_path, TrackingScratch())
        result = run_live_compute(request, finder, tracking)
        if isinstance(result, LiveResult) and result.tacho_block is not None:
            self._tacho_by_path[file_path] = result.tacho_block
        return result
