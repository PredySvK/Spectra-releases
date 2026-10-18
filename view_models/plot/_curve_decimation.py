"""
Qt-free rule for how a plotted curve is clipped and downsampled (#665 C27).

The curve's point count decides first: at or below ``LARGE_CURVE_POINTS`` the
slicing only costs time on every pan/zoom frame (measured on a 700-point order
cut, 100 curves: 19 ms/move with clipping vs 12 ms without, against a 16 ms
frame budget -- BUGS.md K2-redraw, #580). Above it (a multi-million-sample time
signal) the same slicing keeps panning smooth. The saved Graph Rendering
preferences can only switch that large-curve behaviour off; a manual factor
replaces "auto" and, like it, applies to large curves only.
"""

from dataclasses import dataclass

from ._graph_colours import LARGE_CURVE_POINTS


@dataclass(frozen=True)
class CurveDecimation:
    """clip to the visible range, auto-downsample, or downsample by ``factor`` (1 = off)."""

    clip: bool
    auto: bool
    factor: int


_NONE = CurveDecimation(clip=False, auto=False, factor=1)


def resolve_curve_decimation(
    point_count: int,
    *,
    render_screen_only: bool,
    downsample_enabled: bool,
    auto_mode: bool,
    manual_factor: int,
) -> CurveDecimation:
    """The clip / auto / factor triple for a curve of ``point_count`` points."""
    if point_count <= LARGE_CURVE_POINTS:
        return _NONE
    if not downsample_enabled:
        return CurveDecimation(clip=render_screen_only, auto=False, factor=1)
    if auto_mode:
        return CurveDecimation(clip=render_screen_only, auto=True, factor=1)
    return CurveDecimation(clip=render_screen_only, auto=False, factor=max(1, int(manual_factor)))
