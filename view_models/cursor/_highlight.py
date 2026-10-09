"""Which curve the Highlight emphasises: the Cursor's nearest-curve rule, curve only."""

from __future__ import annotations

from typing import Mapping, Optional, Sequence, Tuple

from view_models.plot import Trace

from ._hit_test import AxisTransform, resolve_cursor_point

# Alpha of every curve that is not the highlighted one.
HIGHLIGHT_DIM_ALPHA = 0.25


def resolve_highlighted_trace(
    traces: Sequence[Trace],
    transforms: Mapping[str, AxisTransform],
    mouse_px: Tuple[float, float],
    radius_px: float,
) -> Optional[Trace]:
    """The curve the Cursor would pick at ``mouse_px`` (same radius rule), or None."""
    point = resolve_cursor_point(traces, transforms, mouse_px, radius_px)
    return None if point is None else point.trace
