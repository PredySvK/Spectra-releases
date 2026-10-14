"""
Qt-free curve carousel and the rendering mode a graph draws in.

A graph holding a curve above ``LARGE_CURVE_POINTS`` draws through OpenGL,
every other one through the raster viewport. A carousel curve keeps its slot;
its colour and line style follow from the slot and the graph's mode.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Iterable, Optional, Set, Tuple

from ._plot_model import Pen, Trace

# Above this many points a curve is large: it gets clipToView/autoDownsample
# and puts its graph on the OpenGL viewport.
LARGE_CURVE_POINTS = 20_000

# The raster carousel's line styles, one per round of hues. Qt-free names;
# gui/ maps them to Qt pen styles.
LINE_STYLES = ("solid", "dash", "dot", "dashdot", "dashdotdot", "longdash")

# How many hues one lightness round of the curve palette has (§1.158).
_HUES = 12


class RenderingMode(Enum):
    """How a graph's viewport draws its curves."""

    OPENGL = "opengl"
    RASTER = "raster"


@dataclass(frozen=True)
class CurveLook:
    """The colour, line style (one of ``LINE_STYLES``) and width a curve is drawn with."""

    color: str
    style: str
    width: float


def resolve_rendering_mode(traces: Iterable[Trace]) -> RenderingMode:
    """OpenGL when any drawn curve is large, raster otherwise. ``traces`` are
    the curves actually drawn, on either Y axis."""
    if any(len(trace.x) > LARGE_CURVE_POINTS for trace in traces):
        return RenderingMode.OPENGL
    return RenderingMode.RASTER


def resolve_curve_look(pen: Pen, mode: RenderingMode, palette: Tuple[str, ...]) -> CurveLook:
    """How a curve with ``pen`` is drawn in ``mode``.

    A pen without a slot (the base curve) keeps its own colour, solid. OpenGL
    walks the whole palette solid (§1.162); raster walks the first round's
    twelve hues, then the next line style, and starts over after 72 slots.
    """
    if pen.slot is None:
        return CurveLook(color=pen.color, style="solid", width=pen.width)
    if mode is RenderingMode.OPENGL:
        return CurveLook(color=resolve_carousel_colour(pen.slot, palette), style="solid", width=pen.width)
    if not palette:
        raise ValueError("Curve palette must not be empty")
    hues = palette[:_HUES]
    style = LINE_STYLES[(pen.slot // len(hues)) % len(LINE_STYLES)]
    return CurveLook(color=hues[pen.slot % len(hues)], style=style, width=pen.width)


def resolve_carousel_colour(index_counter: int, palette: Tuple[str, ...]) -> str:
    """
    Hex colour for overlay curve N.

    Walks the palette in order, so past the twelfth curve the same hues come
    back in the next lightness round; past the last round it starts over.
    """
    if not palette:
        raise ValueError("Curve palette must not be empty")
    return palette[index_counter % len(palette)]


class HeldPens:
    """The carousel slots of the held curves, kept so a caller adding curves
    one by one picks the next one without rescanning every held curve (#442)."""

    def __init__(self) -> None:
        self._slots: Set[int] = set()
        self._lowest_free = 0

    def hold(self, slot: Optional[int]) -> None:
        if slot is not None:
            self._slots.add(slot)

    def free_index(self) -> int:
        """The lowest carousel slot no held curve uses.

        Curves stay visually distinct even after earlier overlays are removed
        or hidden by a trace filter. Slots only get held, never released, so
        the search resumes where the last one stopped.
        """
        while self._lowest_free in self._slots:
            self._lowest_free += 1
        return self._lowest_free
