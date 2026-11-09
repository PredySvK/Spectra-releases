"""Nearest real sample of the nearest curve, measured in screen pixels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

import numpy as np

from core.axis_projections import AxisScreenRule
from view_models.plot import Trace


@dataclass(frozen=True)
class AxisTransform:
    """Data -> pixel for one Y axis: ``px = value * scale + offset``.

    Where a value sits on screen is ``x_rule`` / ``y_rule`` (the one native ->
    screen rule, core.axis_projections, §1.276), handed over as the dock has them:
    the X axis unit scale and the Logarithmic axes are in them. ``x_scale`` maps
    *screen* X to pixels; only the pixel step is here.
    """

    x_scale: float
    x_offset: float
    y_scale: float
    y_offset: float
    x_rule: AxisScreenRule = AxisScreenRule()
    y_rule: AxisScreenRule = AxisScreenRule()


@dataclass(frozen=True)
class CursorPoint:
    """The picked sample. ``x`` is in the display unit, ``y`` in the trace's unit."""

    trace: Trace
    index: int
    x: float
    y: float
    secondary: bool
    distance_px: float


def _is_monotonic(x: np.ndarray) -> bool:
    d = np.diff(x)
    return bool(np.all(d >= 0) or np.all(d <= 0))


def _x_pixels(x: np.ndarray, t: AxisTransform) -> np.ndarray:
    """Pixel X of native ``x``; a sample log X cannot draw (X <= 0) comes out non-finite."""
    return t.x_rule.to_screen(x) * t.x_scale + t.x_offset


def _native_x_span(mx: float, radius_px: float, t: AxisTransform) -> Tuple[float, float]:
    """Native X edges of the pixels within ``radius_px`` of ``mx``, in ascending order."""
    edges = (np.array([mx - radius_px, mx + radius_px]) - t.x_offset) / t.x_scale
    low, high = sorted(t.x_rule.to_native(edges))
    return float(low), float(high)


def resolve_cursor_point(
    traces: Sequence[Trace],
    transforms: Mapping[str, AxisTransform],
    mouse_px: Tuple[float, float],
    radius_px: float,
) -> Optional[CursorPoint]:
    """The sample within ``radius_px`` of the mouse nearest to it, or None.

    ``transforms`` is keyed by ``Trace.axis``; a trace whose axis has no transform
    is skipped. Only ``traces`` are candidates (the visible ones).
    """
    mx, my = mouse_px
    best: Optional[CursorPoint] = None
    for trace in traces:
        t = transforms.get(trace.axis)
        if t is None or len(trace.x) == 0:
            continue
        x = np.asarray(trace.x, dtype=float)
        if t.x_rule.scale * t.x_scale == 0:
            continue
        lo, hi = 0, len(x)
        if _is_monotonic(x):
            # Only samples whose pixel X lies within the radius are candidates.
            low, high = _native_x_span(mx, radius_px, t)
            asc = x[0] <= x[-1]
            ordered = x if asc else x[::-1]
            a = int(np.searchsorted(ordered, low, side="left"))
            b = int(np.searchsorted(ordered, high, side="right"))
            lo, hi = (a, b) if asc else (len(x) - b, len(x) - a)
            if lo >= hi:
                continue
        # ponytail: monotonicity re-checked per call (O(N) diff); cache per trace if profiling asks.
        x_px = _x_pixels(x[lo:hi], t)
        y = np.asarray(trace.y[lo:hi], dtype=float)
        y_px = t.y_rule.to_screen(y) * t.y_scale + t.y_offset
        dist = np.hypot(x_px - mx, y_px - my)
        dist = np.where(np.isfinite(dist), dist, np.inf)
        k = int(np.argmin(dist))
        d = float(dist[k])
        if d > radius_px or (best is not None and d >= best.distance_px):
            continue
        i = lo + k
        best = CursorPoint(trace, i, float(trace.x[i]) * t.x_rule.scale, float(trace.y[i]),
                           trace.axis == "secondary", d)
    return best
