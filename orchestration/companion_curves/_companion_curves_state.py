"""What one graph dock remembers between two companion-curve passes."""

from typing import AbstractSet, Iterable, Set


class CompanionCurvesState:
    """Order curves a dock has already looked at, and the partners it added itself.

    Owned by the dock.
    """

    def __init__(self) -> None:
        self._seen: Set[tuple] = set()
        self._added: Set[tuple] = set()

    def plan_fresh(self, current: AbstractSet[tuple]) -> Set[tuple]:
        """The curves in `current` whose partners have not been looked for yet.

        Partners never look for partners of their own (#509); a removed one is
        forgotten, so dropping it again by hand counts as the user's.
        """
        self._added -= self._seen - current
        fresh = set(current) - self._seen - self._added
        self._seen = set(current)
        return fresh

    def record_added(self, identities: Iterable[tuple]) -> None:
        """Partners this dock is about to receive from a companion pass."""
        self._added.update(identities)
