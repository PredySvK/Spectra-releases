"""
view_models.track_cursor -- What the Track cursor reads and the Track table says, without Qt.

Architecture:
- View-model floor (Floor 3): given the drawn curves and the X of a vertical
  line, each curve's value there and the Track table (CONTEXT.md "Track
  cursor", "Track table"); gui/workspace/track_cursor draws the line and the
  table and reads the mouse.
- Reading: build_track_curves prepares the drawn curves once per redraw into
  TrackCurves: X checked for monotonicity, metadata read once, the columns and
  how X is written decided. resolve_track_value reads one curve at an X, linear
  between the samples around it, None ("—") outside the curve, next to NaN or on
  an X that is not strictly monotonic.
- Table: build_track_table(track_curves, x, max_rows=, max_columns=) -- a move
  of the line passes only X and what fits -- puts X above and one row per curve
  below: main Y axis from the highest value, then the right Y axis, every "—"
  last, ties in legend order; columns follow a CursorConfig's Priority, each
  cell through view_models.cursor.build_curve_field so it reads as the Cursor
  Box does. A long cell ends in "…"; rows and columns past what gui says fits
  become "… and N more" and "+N columns".
- State: TrackCursorState keeps one graph's line in native X; the graph's
  core.axis_projections.AxisScreenRule (X axis unit scale, log X, §1.276)
  turns it into ViewBox coordinates and back.

What does NOT belong here: Qt widgets or the mouse (gui/), the persisted field
list's shape (core/cursor_config), the Cursor's nearest-sample pick (view_models.cursor).
"""

from ._track_cursor_state import TrackCursorState
from ._track_curve import MetadataReader, TrackCurve, TrackCurves, build_track_curves, resolve_track_value
from ._track_table import MAX_CELL_CHARS, MISSING_VALUE, TrackRow, TrackTable, build_track_table

__all__ = [
    "MAX_CELL_CHARS",
    "MISSING_VALUE",
    "MetadataReader",
    "TrackCurve",
    "TrackCurves",
    "TrackCursorState",
    "TrackRow",
    "TrackTable",
    "build_track_curves",
    "build_track_table",
    "resolve_track_value",
]
