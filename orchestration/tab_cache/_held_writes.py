"""`HeldTabCacheWrites`: Tab cache files an Untitled project keeps in memory until its first Save."""

import dataclasses
from typing import Any, Callable, Dict, Hashable, Iterable, List, Optional, Tuple


@dataclasses.dataclass(frozen=True)
class HeldTabCacheWrite:
    """
    One Tab cache file not written yet. `name` is already the one the
    `TraceSpec` saves, so the first Save names it; `on_failed(name)`
    is what the curve's owner does when the write later fails.
    """
    dock_id: str
    name: str
    channel_name: str
    blocks: Tuple[Any, ...]
    recipe: Optional[dict]
    on_failed: Optional[Callable[[str], None]] = None


class HeldTabCacheWrites:
    """
    What an Untitled project would have written to its Tab cache: it has no
    folder yet, so the results wait here and go to disk on the first Save
   . Nothing reaches the disk before that.

    Any curve of a tab can be held -- the base curve, a spectrogram, a
    dropped channel -- under its `TabCacheCurve` ("this curve of this tab"),
    the key its file name is stored under too: a newer result under the same
    key (a Refresh) replaces the older one, so only the latest is ever
    written. Closing a tab drops its curves.
    """

    def __init__(self):
        self._held: Dict[Tuple[str, Hashable], HeldTabCacheWrite] = {}

    def hold(self, key: Hashable, write: HeldTabCacheWrite) -> None:
        self._held[(write.dock_id, key)] = write

    def discard_dock(self, dock_id: str) -> None:
        """Forgets every curve of a tab that was closed."""
        for slot in [slot for slot in self._held if slot[0] == dock_id]:
            del self._held[slot]

    def take(self, referenced_names: Iterable[str]) -> List[HeldTabCacheWrite]:
        """
        Hands over the held writes the saved project names and forgets all of
        them: a held result whose name the project does not save (its curve
        was removed) would only be a file nobody reads.
        """
        referenced = set(referenced_names)
        taken = [write for write in self._held.values() if write.name in referenced]
        self._held.clear()
        return taken

    def __len__(self) -> int:
        return len(self._held)
