"""Cursor Box content and placement."""

from __future__ import annotations

from typing import List, Mapping, Tuple

from core.cursor_config import (
    CursorConfig, FIELD_AMPLITUDE, FIELD_CURVE, FIELD_X, FIELD_Y, FIELD_Z,
)
from core.units import UnitPreferences
from view_models.display_prefix import resolve_number_format
from view_models.plot import format_display_unit, resolve_ordinate_quantity

from ._hit_test import CursorPoint
from ._spectrogram import SpectrogramPoint

_GAP_PX = 14


def build_cursor_box_lines(
    point: CursorPoint | SpectrogramPoint,
    config: CursorConfig,
    *,
    x_unit: str = "",
    x_quantity: str = "",
    two_axes: bool = False,
    metadata: Mapping[str, Tuple[str, str]] = {},
    prefs: UnitPreferences | None = None,
) -> List[Tuple[str, str]]:
    """(label, text) lines in config order; fields this point cannot answer are skipped.

    ``x_quantity`` is the graph's X domain; with the curve's own Y quantity it
    picks the Display prefix row for a Hz value (speed or frequency).
    ``metadata`` is the curve's ``{key: (label, text)}`` (read_curve_metadata); a
    config key found neither there nor among the values is left out silently.
    """
    def text(value: float, unit: str, *, quantity: str = "", db: bool = False) -> str:
        return resolve_number_format(unit, prefs, quantity=quantity, db=db).format_with_unit(value)

    if isinstance(point, SpectrogramPoint):
        decibel = "dB" in (point.color_scale or "") or point.z_unit == "dB"
        x_u = x_unit or point.x_unit
        lines: List[Tuple[str, str]] = []
        for key in config.fields:
            if key == FIELD_X:
                lines.append(("X", text(point.x, x_u, quantity=point.x_quantity)))
            elif key == FIELD_Y:
                lines.append(("Y", text(point.y, point.y_unit, quantity="frequency")))
            elif key == FIELD_Z:
                lines.append(("Z", text(point.z, point.z_unit, db=decibel)))
            elif key in metadata:
                lines.append(metadata[key])
        return lines

    trace = point.trace
    unit = format_display_unit(trace.unit)
    decibel = unit == "dB"
    amplitude = trace.amplitude_mode
    lines = []
    for key in config.fields:
        if key == FIELD_X:
            lines.append(("X", text(point.x, x_unit, quantity=x_quantity)))
        elif key == FIELD_Y:
            label = "Y (Secondary)" if two_axes and point.secondary else "Y"
            lines.append((label, text(point.y, unit, quantity=resolve_ordinate_quantity(trace), db=decibel)))
        elif key == FIELD_CURVE and trace.label:
            lines.append(("Curve", trace.label))
        elif key == FIELD_AMPLITUDE and amplitude:
            lines.append(("Amplitude", {"rms": "RMS", "peak": "Peak"}.get(amplitude, str(amplitude))))
        elif key in metadata:
            lines.append(metadata[key])
    return lines


def resolve_box_position(
    box_size: Tuple[float, float], mouse_px: Tuple[float, float],
    canvas_rect: Tuple[float, float, float, float],
) -> Tuple[float, float]:
    """Top-left of the box: right/below the mouse, flipped on each axis that would overflow.

    ``canvas_rect`` is (left, top, right, bottom).
    """
    w, h = box_size
    mx, my = mouse_px
    left, top, right, bottom = canvas_rect
    x = mx + _GAP_PX
    if x + w > right:
        x = mx - _GAP_PX - w
    y = my + _GAP_PX
    if y + h > bottom:
        y = my - _GAP_PX - h
    return max(x, left), max(y, top)
