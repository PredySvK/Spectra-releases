"""Bookkeeping for live Orders computed one job per dropped channel."""

from collections import OrderedDict
from typing import Dict, Hashable, Optional, Tuple

# Cap on memoized live-compute results. A long analysis session can drop many
# channels (each a distinct file/channel/DSP-settings combo) onto a result
# dock; without a bound the memo would grow for the whole session, since reset()
# only fires on a workspace directory reload. 64 covers any realistic active
# comparison while keeping the least-recently-used blocks from piling up.
RESULT_MEMO_LIMIT = 64


class LiveOrderMemo:
    """
    Which live order results are ready and which are in flight. No Qt, no
    threads of its own: the caller dispatches the jobs and reports back what
    happened.

    A memo key is opaque here -- any hashable the caller builds per (file,
    channel, settings).

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
        """Forget every result and tag; returns the tags that were still in flight."""
        pending_tags = tuple(self._pending)
        self._pending.clear()
        self._results.clear()
        return pending_tags
