"""Nearest real sample of the nearest curve, measured in screen pixels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

import numpy as np

from view_models.plot import Trace


@dataclass(frozen=True)
class AxisTransform:
    """Data -> pixel for one Y axis: ``px = value * scale + offset``.

    ``x_scale`` includes the global X axis unit (display = native * ``x_display``),
    so ``x_scale`` maps *display* X to pixels. ``log_y`` means the axis shows log10(y).
    """

    x_scale: float
    x_offset: float
    y_scale: float
    y_offset: float
    x_display: float = 1.0
    log_y: bool = False


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
        k = t.x_display * t.x_scale
        if k == 0:
            continue
        lo, hi = 0, len(x)
        if _is_monotonic(x):
            # Only samples whose pixel X lies within the radius are candidates.
            edges = sorted(((mx - radius_px - t.x_offset) / k, (mx + radius_px - t.x_offset) / k))
            asc = x[0] <= x[-1]
            ordered = x if asc else x[::-1]
            a = int(np.searchsorted(ordered, edges[0], side="left"))
            b = int(np.searchsorted(ordered, edges[1], side="right"))
            lo, hi = (a, b) if asc else (len(x) - b, len(x) - a)
            if lo >= hi:
                continue
        # ponytail: monotonicity re-checked per call (O(N) diff); cache per trace if profiling asks.
        x_px = x[lo:hi] * k + t.x_offset
        y = np.asarray(trace.y[lo:hi], dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            y_data = np.log10(y) if t.log_y else y
        y_px = y_data * t.y_scale + t.y_offset
        dist = np.hypot(x_px - mx, y_px - my)
        dist = np.where(np.isfinite(dist), dist, np.inf)
        k = int(np.argmin(dist))
        d = float(dist[k])
        if d > radius_px or (best is not None and d >= best.distance_px):
            continue
        i = lo + k
        best = CursorPoint(trace, i, float(trace.x[i]) * t.x_display, float(trace.y[i]),
                           trace.axis == "secondary", d)
    return best
