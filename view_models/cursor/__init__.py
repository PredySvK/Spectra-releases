"""
view_models.cursor -- What the Cursor (hover tool) picks and shows, without Qt.

Architecture:
- View-model floor (Floor 3): given curves, a data->pixel transform per axis and
  a mouse position, which sample is under the mouse and what the Cursor Box says.
- Picking: resolve_cursor_point snaps to the nearest real sample of the nearest
  curve, judged in screen pixels (AxisTransform carries the transform as plain numbers).
- Box: build_cursor_box_lines turns the picked point and a CursorConfig into
  ordered (label, text) lines (number formatting "Auto"); read_curve_metadata
  reads the curve's own metadata fields for them; resolve_box_position
  places the box next to the mouse and flips it at the graph edges.
- Highlight: resolve_highlighted_trace names the curve to emphasise (the Cursor's
  nearest-curve rule); HIGHLIGHT_DIM_ALPHA is how faint the others become.

What does NOT belong here: Qt widgets or drawing (gui/), the persisted
field list's shape (core/cursor_config), Band RMS Cursors or other helper lines
(only the traces passed in are ever candidates).
"""

from ._box import build_cursor_box_lines, format_auto, resolve_box_position
from ._highlight import HIGHLIGHT_DIM_ALPHA, resolve_highlighted_trace
from ._hit_test import AxisTransform, CursorPoint, resolve_cursor_point
from ._metadata import read_curve_metadata
from ._spectrogram import SpectrogramPoint, resolve_spectrogram_pixel

__all__ = [
    "HIGHLIGHT_DIM_ALPHA",
    "AxisTransform",
    "CursorPoint",
    "SpectrogramPoint",
    "build_cursor_box_lines",
    "format_auto",
    "read_curve_metadata",
    "resolve_box_position",
    "resolve_cursor_point",
    "resolve_highlighted_trace",
    "resolve_spectrogram_pixel",
]
