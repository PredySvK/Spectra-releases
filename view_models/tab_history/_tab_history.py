"""Pure Python (Qt-free) MRU tab history and cycling state (#846)."""

from typing import Any, Collection, List, Optional, Tuple


class TabHistory:
    """Tracks tab identifiers in most-recently-used (MRU) order and manages

    Ctrl+Tab cycling state without Qt dependencies (#846).
    """

    def __init__(self) -> None:
        self._items: List[Any] = []
        self._cycle_index: Optional[int] = None

    @property
    def order(self) -> Tuple[Any, ...]:
        """Current MRU order of tab identifiers (index 0 is the most recent)."""
        return tuple(self._items)

    @property
    def is_cycling(self) -> bool:
        """True while a Ctrl+Tab cycle is active."""
        return self._cycle_index is not None

    @property
    def current_cycle_item(self) -> Optional[Any]:
        """The item currently highlighted by the active cycle."""
        if self._cycle_index is not None and 0 <= self._cycle_index < len(self._items):
            return self._items[self._cycle_index]
        return None

    def record_active(self, tab_id: Any) -> None:
        """Records `tab_id` as the active tab, moving it to the front of MRU.

        Ignored if a cycle is currently active so cycling does not mutate
        the reference snapshot before commit.
        """
        if self.is_cycling or tab_id is None:
            return
        if tab_id in self._items:
            self._items.remove(tab_id)
        self._items.insert(0, tab_id)

    def remove(self, tab_id: Any) -> None:
        """Removes `tab_id` from history when closed."""
        if tab_id in self._items:
            self._items.remove(tab_id)
        if self._cycle_index is not None:
            if not self._items:
                self._cycle_index = None
            elif self._cycle_index >= len(self._items):
                self._cycle_index = len(self._items) - 1

    def sync(self, current_tab_ids: Collection[Any]) -> None:
        """Synchronizes history with the currently existing tab IDs.

        Preserves MRU order for tabs that still exist, prunes removed ones,
        and appends any newly introduced tabs that haven't been activated yet.
        """
        valid_set = set(current_tab_ids)
        new_items = [tid for tid in self._items if tid in valid_set]
        for tid in current_tab_ids:
            if tid not in new_items:
                new_items.append(tid)
        self._items = new_items
        if self._cycle_index is not None:
            if not self._items:
                self._cycle_index = None
            elif self._cycle_index >= len(self._items):
                self._cycle_index = len(self._items) - 1

    def start_cycle(self, direction: int = 1) -> Optional[Any]:
        """Begins a Ctrl+Tab cycle.

        direction: 1 for forward (Ctrl+Tab), -1 for backward (Ctrl+Shift+Tab).
        Returns the selected tab ID or None if fewer than 2 tabs exist.
        """
        if len(self._items) < 2:
            self._cycle_index = None
            return None

        if direction >= 0:
            self._cycle_index = 1
        else:
            self._cycle_index = len(self._items) - 1
        return self.current_cycle_item

    def step_cycle(self, direction: int = 1) -> Optional[Any]:
        """Advances the cycle by `direction` (+1 or -1).

        Wraps around if reaching either end.
        """
        if not self._items:
            self._cycle_index = None
            return None
        if self._cycle_index is None:
            return self.start_cycle(direction)

        step = 1 if direction >= 0 else -1
        self._cycle_index = (self._cycle_index + step) % len(self._items)
        return self.current_cycle_item

    def finish_cycle(self) -> Optional[Any]:
        """Commits the active cycle, placing the selected tab at the front of MRU.

        Returns the committed tab ID.
        """
        if self._cycle_index is None or not self._items:
            self._cycle_index = None
            return None

        selected = self._items[self._cycle_index]
        self._cycle_index = None
        # Move selected to front
        self._items.remove(selected)
        self._items.insert(0, selected)
        return selected

    def cancel_cycle(self) -> Optional[Any]:
        """Cancels the active cycle without changing MRU order.

        Returns the tab ID that was active when the cycle started (index 0).
        """
        self._cycle_index = None
        return self._items[0] if self._items else None
