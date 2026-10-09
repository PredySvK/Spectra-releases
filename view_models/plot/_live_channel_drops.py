"""Bookkeeping of the channels live-dropped onto one graph (Qt-free)."""

from typing import Any, Dict, FrozenSet, List, Set


class LiveChannelDrops:
    """Which live-dropped channels a graph already took, and which are still
    waiting for their worker result. Lives beside the graph's curves; clearing
    the curves does not touch it."""

    def __init__(self) -> None:
        self._claimed: Set[Any] = set()
        self._pending: List[Dict[str, Any]] = []

    @property
    def pending(self) -> List[Dict[str, Any]]:
        """Live-dropped channels whose worker result has not been folded in yet."""
        return list(self._pending)

    def pending_descriptors(self) -> List[Dict[str, Any]]:
        """The pending entries as drop descriptors: each carries the orders of
        its memo key as ``orders_to_extract``."""
        return [
            {**entry, "orders_to_extract": dict(entry["memo_key"].config_items).get("orders_to_extract", ())}
            for entry in self._pending
        ]

    @property
    def claimed(self) -> FrozenSet[Any]:
        return frozenset(self._claimed)

    def claim(self, key: Any) -> bool:
        """Accepts a live-dropped channel (``build_channel_key``) once; False
        when this graph already took it, so a second drop is a no-op."""
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True

    def release(self, key: Any) -> None:
        """Nothing will ever land for ``key`` (failed, cancelled, evicted):
        let the user drop it again."""
        self._claimed.discard(key)

    def add_pending(self, entry: Dict[str, Any]) -> None:
        self._pending.append(entry)

    def take_pending(self) -> List[Dict[str, Any]]:
        """Hands over every pending entry and empties the list; the caller
        puts back (add_pending) the ones still in flight."""
        taken, self._pending = self._pending, []
        return taken
