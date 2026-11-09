"""Where one graph's Track cursor line stands, kept in the curves' own X unit."""

from __future__ import annotations

from typing import Optional, Tuple

from core.axis_projections import AxisScreenRule


class TrackCursorState:
    """The line's place on one graph (each graph has its own), without Qt.

    Held in native X, so a change of X axis unit (Hz to RPM) leaves the line on
    the same physical place. A change of X domain or switching the tool off drops
    it; the line then comes back in the middle of the visible X.
    """

    def __init__(self) -> None:
        self._x: Optional[float] = None
        # The X domain of the place (PlotModel.x_domain); "" is a domain too ("not decided").
        self._x_domain = ""

    @property
    def x(self) -> Optional[float]:
        """The line's native X, or None while it has no place yet."""
        return self._x

    def place(self, x_domain: str, axis: AxisScreenRule, view_range: Tuple[float, float]) -> float:
        """Native X of the line on a graph of ``x_domain`` showing ``view_range`` (ViewBox coordinates).

        ``x_domain`` is the graph's ``PlotModel.x_domain``: always a string, ""
        while the graph has not decided one. Keeps the place it has; takes the middle of ``view_range`` when it has none,
        when the X domain changed, or when ``axis`` has no screen position for it (log X at X <= 0).
        """
        if self._x is None or x_domain != self._x_domain or not axis.has_screen_position(self._x):
            low, high = view_range
            self._x = float(axis.to_native((low + high) / 2.0))
            self._x_domain = x_domain
        return self._x

    def move_to(self, view_x: float, axis: AxisScreenRule) -> float:
        """The user moved the line to ``view_x`` (ViewBox coordinate); its native X."""
        self._x = float(axis.to_native(view_x))
        return self._x

    def forget(self) -> None:
        """The tool went off: the next ``place`` starts in the middle again."""
        self._x = None
        self._x_domain = ""
