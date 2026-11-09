"""The drawn curves made ready, once per redraw, to be read at any X of the Track cursor's line."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np

from core.cursor_config import DEFAULT_TRACK_TABLE_FIELDS, FIELD_X, FIELD_Z, VALUE_FIELDS, CursorConfig
from core.units import UnitPreferences
from view_models.cursor import build_curve_field
from view_models.display_prefix import NumberFormat, resolve_number_format
from view_models.plot import Trace

# The curve's own metadata fields: {key: (label, text)} (view_models.cursor.read_curve_metadata).
MetadataReader = Callable[[Trace, Iterable[str]], Mapping[str, Tuple[str, str]]]


@dataclass(frozen=True, eq=False)
class TrackCurve:
    """A drawn curve with what does not change while the line moves.

    ``legend_index`` is the curve's place in the legend (the draw order), which
    breaks a tie between equal values. ``readable`` is False for an X that is not
    strictly monotonic: such a curve passes some X more than once and is never read.
    ``metadata`` is read once, here, not on every move of the line.
    """

    trace: Trace
    legend_index: int
    metadata: Mapping[str, Tuple[str, str]] = field(default_factory=dict)
    # X rising (a falling curve is turned round once) and the Y beside it; None when unreadable.
    _x: Optional[np.ndarray] = field(default=None, repr=False)
    _y: Optional[np.ndarray] = field(default=None, repr=False)

    @property
    def readable(self) -> bool:
        """Whether the line can read this curve: its X is strictly monotonic."""
        return self._x is not None

    def resolve_value(self, x: float) -> Optional[float]:
        """Y at ``x`` (the curve's own X unit), linear between the two samples around it.

        None outside the curve, next to a NaN sample, and for an unreadable curve.
        """
        xs, ys = self._x, self._y
        if xs is None or ys is None or not np.isfinite(x):
            return None
        if x < xs[0] or x > xs[-1]:
            return None
        right = int(np.searchsorted(xs, x, side="left"))
        if xs[right] == x:
            value = float(ys[right])
            return value if np.isfinite(value) else None
        x0, x1 = float(xs[right - 1]), float(xs[right])
        y0, y1 = float(ys[right - 1]), float(ys[right])
        if not (np.isfinite(y0) and np.isfinite(y1)):
            return None
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


@dataclass(frozen=True, eq=False)
class TrackCurves:
    """Everything the Track table needs that does not change while the line moves.

    ``curves`` in legend order; ``columns`` are the ``(key, label)`` of the
    columns that can be shown, in ``CursorConfig`` Priority: a field no curve
    answers has none, X and Z never are columns. ``x_format`` and ``x_scale``
    write the line's X as the axis shows it; ``prefs`` write each cell.
    Built by ``build_track_curves``.
    """

    curves: Tuple[TrackCurve, ...]
    columns: Tuple[Tuple[str, str], ...]
    x_format: NumberFormat
    x_scale: float = 1.0
    prefs: Optional[UnitPreferences] = None


def _rising(x: np.ndarray, y: np.ndarray) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """``(x, y)`` with X strictly rising, or None when X is not strictly monotonic."""
    if x.size < 2:
        return (x, y) if x.size == 1 and np.isfinite(x[0]) else None
    step = np.diff(x)
    if np.all(step > 0):
        return x, y
    if np.all(step < 0):
        return x[::-1], y[::-1]
    return None


def _track_curve(trace: Trace, index: int, metadata: Mapping[str, Tuple[str, str]]) -> TrackCurve:
    x = np.asarray(trace.x, dtype=float)
    y = np.asarray(trace.y, dtype=float)
    rising = _rising(x, y) if x.shape == y.shape else None
    if rising is None:
        return TrackCurve(trace, index, metadata)
    return TrackCurve(trace, index, metadata, rising[0], rising[1])


def _columns(curves: Sequence[TrackCurve], config: CursorConfig,
             prefs: Optional[UnitPreferences]) -> Tuple[Tuple[str, str], ...]:
    """The columns some curve answers; the first curve that has the field names it.

    Whether a curve has a field and what it is called does not depend on its
    value, so Y is asked at 0.
    """
    columns = []
    for key in config.fields:
        if key in (FIELD_X, FIELD_Z):
            continue
        label = next((found[0] for found in (
            build_curve_field(curve.trace, key, 0.0, metadata=curve.metadata, prefs=prefs) for curve in curves)
            if found is not None), None)
        if label is not None:
            columns.append((key, label))
    return tuple(columns)


def build_track_curves(
    traces: Sequence[Trace],
    config: CursorConfig = CursorConfig(DEFAULT_TRACK_TABLE_FIELDS),
    *,
    metadata_reader: Optional[MetadataReader] = None,
    x_scale: float = 1.0,
    x_unit: str = "",
    x_quantity: str = "",
    prefs: UnitPreferences | None = None,
) -> TrackCurves:
    """The drawn ``traces`` (legend order) made ready for the line; once per redraw.

    Checks each curve's X once, reads ``config``'s metadata fields once per curve
    with ``metadata_reader`` (none when the choice holds only value fields),
    decides the columns and how X is written (``x_scale`` turns native X into the
    axis's ``x_unit``, Hz to RPM), so a move of the line only interpolates.
    """
    keys = tuple(key for key in config.fields if key not in VALUE_FIELDS)
    curves = tuple(
        _track_curve(trace, index, metadata_reader(trace, keys) if metadata_reader is not None and keys else {})
        for index, trace in enumerate(traces)
    )
    return TrackCurves(
        curves=curves,
        columns=_columns(curves, config, prefs),
        x_format=resolve_number_format(x_unit, prefs, quantity=x_quantity),
        x_scale=x_scale,
        prefs=prefs,
    )


def resolve_track_value(curve: TrackCurve, x: float) -> Optional[float]:
    """The curve's Y at ``x`` (its own X unit); see TrackCurve.resolve_value."""
    return curve.resolve_value(x)
