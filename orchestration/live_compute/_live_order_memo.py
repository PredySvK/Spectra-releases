"""Bookkeeping for live Orders computed one job per dropped channel (ADR §1.30, §1.117)."""

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Hashable, Optional, Tuple

from core.dsp_configs import OrderTrackingConfig

# Cap on memoized live-compute results. A long analysis session can drop many
# channels (each a distinct file/channel/DSP-settings combo) onto a result
# dock; without a bound the memo would grow for the whole session, since reset()
# only fires on a workspace directory reload. 64 covers any realistic active
# comparison while keeping the least-recently-used blocks from piling up.
RESULT_MEMO_LIMIT = 64


@dataclass(frozen=True)
class _PlanIdentity:
    """What one TrackingPlan is built from: a file as it is on disk, its tacho, its sweep."""

    file_path: str
    size: object
    mtime_ns: object
    tacho_index: object
    step: float
    direction: str
    hysteresis: float


class LiveOrderMemo:
    """
    Which live order results are ready, which are in flight, and the one
    TrackingPlan bag the in-flight jobs of one file share. No Qt, no threads of
    its own: the caller dispatches the jobs and reports back what happened.

    A memo key is opaque here -- any hashable the caller builds per (file,
    channel, settings); the plan bag is asked for with named fields instead, so
    nothing depends on where those sit inside the key.

    Each request gets a tag of its own: a job has no natural per-key generation,
    and reset() makes every outstanding tag stale, so a job landing after it
    caches nothing.
    """

    def __init__(self, limit: int = RESULT_MEMO_LIMIT):
        self._limit = limit
        self._results: "OrderedDict[Hashable, list]" = OrderedDict()
        # tag -> (key, channel name the tag logs under: the key holds only the
        # channel's index, which tells same-named channels apart but reads badly).
        self._pending: Dict[str, Tuple[Hashable, str]] = {}
        self._next_tag = 0
        # (identity, (lock, scratch)) for the file/tacho/sweep the latest request
        # computes against: N channels dropped from one file are N jobs, and this
        # is what lets them build one TrackingPlan between them (#99). Holds one
        # file's plan only (~8 bytes per tacho sample): channels interleaved
        # across files rebuild it, the price of not keeping a 15 MB plan per file
        # for the whole session (ADR §1.117).
        self._plan: Tuple[Optional[_PlanIdentity], Optional[Tuple[threading.Lock, dict]]] = (None, None)

    def result_for(self, key) -> Optional[list]:
        if key not in self._results:
            return None
        self._results.move_to_end(key)  # mark as most-recently used
        return self._results[key]

    def is_pending(self, key) -> bool:
        return any(pending_key == key for pending_key, _ in self._pending.values())

    def begin(self, key, channel_name: str) -> Optional[str]:
        """A new tag for `key`, or None if it already has a result or is in flight."""
        if key in self._results or self.is_pending(key):
            return None
        self._next_tag += 1
        tag = str(self._next_tag)
        self._pending[tag] = (key, channel_name)
        return tag

    def plan_scratch_for(self, file_path: str, size, mtime_ns, tacho_index,
                         config: OrderTrackingConfig) -> Tuple[threading.Lock, dict]:
        """The `(lock, scratch)` bag shared by every job of this file, tacho and sweep."""
        identity = _PlanIdentity(file_path, size, mtime_ns, tacho_index,
                                 config.step, config.direction, config.hysteresis)
        if self._plan[0] != identity:
            self._plan = (identity, (threading.Lock(), {}))
        return self._plan[1]

    def finish(self, tag: str, blocks: list) -> Optional[Tuple[Hashable, str]]:
        """
        Memoise `tag`'s result; returns its (key, channel name), or None when the
        tag went stale (reset, or already released) and nothing was stored.
        """
        entry = self._pending.pop(tag, None)
        if entry is None:
            return None
        key = entry[0]
        self._results[key] = blocks
        self._results.move_to_end(key)
        while len(self._results) > self._limit:
            self._results.popitem(last=False)
        return entry

    def release(self, tag: str) -> Optional[Tuple[Hashable, str]]:
        """Drop `tag` without a result (failed or cancelled), so its key can be asked again."""
        return self._pending.pop(tag, None)

    def reset(self) -> Tuple[str, ...]:
        """Forget every result, tag and plan; returns the tags that were still in flight."""
        pending_tags = tuple(self._pending)
        self._pending.clear()
        self._results.clear()
        self._plan = (None, None)
        return pending_tags
