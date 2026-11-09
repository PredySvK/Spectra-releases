"""What the Track table says: X above, then one row per drawn curve in sorted order."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

from core.cursor_config import FIELD_Y
from view_models.cursor import build_curve_field
from view_models.plot import Trace

from ._track_curve import TrackCurve, TrackCurves, resolve_track_value

# The cell of a curve that has no value there (outside it, NaN, X not monotonic, field absent).
MISSING_VALUE = "—"

# A longer cell (or column label) ends in "…", so one curve always stays on one line.
MAX_CELL_CHARS = 32


@dataclass(frozen=True)
class TrackRow:
    """One curve: its Y at the line (None = no value) and one cell per header column."""

    trace: Trace
    value: Optional[float]
    cells: Tuple[str, ...]


@dataclass(frozen=True)
class TrackTable:
    """``x_line`` is the ``(label, text)`` above the table; ``rows`` are already in order.

    ``right_axis_from`` is the index in ``rows`` where the right Y axis group
    starts under the main rows (None: no right Y axis row shown, or no main row
    above it to set it apart from). ``hidden_rows`` and
    ``hidden_columns`` count what did not fit; ``more_rows`` / ``more_columns``
    say it ("" when everything fits).
    """

    x_line: Tuple[str, str]
    header: Tuple[str, ...]
    rows: Tuple[TrackRow, ...]
    right_axis_from: Optional[int] = None
    hidden_rows: int = 0
    hidden_columns: int = 0

    @property
    def more_rows(self) -> str:
        return f"… and {self.hidden_rows} more" if self.hidden_rows else ""

    @property
    def more_columns(self) -> str:
        if not self.hidden_columns:
            return ""
        return f"+{self.hidden_columns} column{'' if self.hidden_columns == 1 else 's'}"


def _clip(text: str) -> str:
    return text if len(text) <= MAX_CELL_CHARS else text[:MAX_CELL_CHARS - 1] + "…"


_MAIN, _RIGHT, _MISSING = 0, 1, 2


def _row_group(curve: TrackCurve, value: Optional[float]) -> int:
    if value is None:
        return _MISSING
    return _RIGHT if curve.trace.axis == "secondary" else _MAIN


def _row_order(curve: TrackCurve, value: Optional[float]) -> Tuple[int, float, int]:
    # Main Y axis, then the right one, each from the highest value; every "—" last.
    # Equal values keep legend order.
    return _row_group(curve, value), (0.0 if value is None else -value), curve.legend_index


def _group_thousands(text: str) -> str:
    """``15466 RPM`` -> ``15 466 RPM`` (no-break spaces); a number under 1000 is unchanged."""
    match = re.match(r"^(-?)(\d{4,})(?!\d)(.*)$", text)
    if match is None:
        return text
    sign, digits, rest = match.groups()
    groups = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return f"{sign}{chr(0xA0).join(groups)}{rest}"


def build_track_table(
    track_curves: TrackCurves,
    x: float,
    *,
    max_rows: Optional[int] = None,
    max_columns: Optional[int] = None,
) -> TrackTable:
    """The Track table for the line at ``x`` (the curves' own X unit).

    ``track_curves`` (``build_track_curves``, once per redraw) already holds the
    columns, how X is written and the unit preferences, so a move passes only X
    and what fits. Numbers and units are written as in the Cursor Box. A cell
    longer than ``MAX_CELL_CHARS`` ends in "…".

    ``max_rows`` / ``max_columns`` are how many curve lines and columns fit on
    screen (gui measures them; None = all). Rows past the fit are the lowest in
    the order and give way to one closing line, which takes one of the
    ``max_rows``; at least one curve row stays, so below two lines the table
    is taller than the fit. Columns past the fit are the lowest Priority. The order of
    the rows never depends on which columns are shown.
    """
    curves, columns, prefs = track_curves.curves, track_curves.columns, track_curves.prefs
    x_text = _group_thousands(track_curves.x_format.format_with_unit(x * track_curves.x_scale))
    values = [resolve_track_value(curve, x) for curve in curves]
    shown = columns if max_columns is None else columns[:max(max_columns, 0)]
    order = sorted(range(len(curves)), key=lambda i: _row_order(curves[i], values[i]))
    if max_rows is not None and len(order) > max_rows:
        # One curve row always stays, even where the closing line then does not fit.
        order = order[:max(max_rows - 1, 1)]

    # Cells are formatted only for the rows and columns that are shown, so a
    # move costs the rows that fit, not every curve.
    def cell(i: int, key: str) -> str:
        value = values[i]
        found = build_curve_field(
            curves[i].trace, key, 0.0 if value is None else value, metadata=curves[i].metadata, prefs=prefs)
        if found is None or (key == FIELD_Y and value is None):
            return MISSING_VALUE
        return found[1] or MISSING_VALUE

    rows = tuple(
        TrackRow(curves[i].trace, values[i], tuple(_clip(cell(i, key)) for key, _label in shown))
        for i in order
    )
    groups = [_row_group(curves[i], values[i]) for i in order]
    return TrackTable(
        x_line=("X", x_text),
        header=tuple(_clip(label) for _key, label in shown),
        rows=rows,
        right_axis_from=groups.index(_RIGHT) if _RIGHT in groups and _MAIN in groups else None,
        hidden_rows=len(curves) - len(rows),
        hidden_columns=len(columns) - len(shown),
    )
