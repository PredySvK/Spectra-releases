"""Pending drop record of one dock (Qt-free)."""

from typing import Any, Dict, Iterable, Set

from orchestration.channel_drop._routing import drop_keys


class PendingDrops:
    """Channels a dock accepted from a drop but has not drawn yet.

    Claimed when a batch is accepted, released when its curves land or its job
    fails. Batches add to each other and release independently (#286).
    """

    def __init__(self) -> None:
        self._keys: Set[tuple] = set()

    def claim(self, descriptors: Iterable[Dict[str, Any]]) -> None:
        self._keys.update(key for desc in descriptors for key in drop_keys(desc))

    def release(self, descriptors: Iterable[Dict[str, Any]]) -> None:
        for desc in descriptors:
            self._keys.difference_update(drop_keys(desc))

    def keys(self, live_descriptors: Iterable[Dict[str, Any]] = ()) -> Set[tuple]:
        """Every pending key, including result-content live orders (the
        ``pending_descriptors()`` of ``LiveChannelDrops``)."""
        keys = set(self._keys)
        for desc in live_descriptors:
            keys.update(drop_keys(desc))
        return keys
