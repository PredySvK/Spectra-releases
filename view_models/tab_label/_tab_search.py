"""Pure Python tab search filtering logic (#848)."""

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class TabSearchEntry:
    index: int
    title: str
    tooltip: str = ""
    is_active: bool = False


def filter_tab_entries(entries: Iterable[TabSearchEntry], query: str) -> List[TabSearchEntry]:
    """Filters tab entries matching `query` against title or tooltip (case-insensitive)."""
    q = query.strip().lower()
    if not q:
        return list(entries)
    return [
        entry for entry in entries
        if q in entry.title.lower() or q in entry.tooltip.lower()
    ]
