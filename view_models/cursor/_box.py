"""Cursor Box content and placement."""

from __future__ import annotations

from typing import List, Mapping, Tuple

from core.cursor_config import (
    CursorConfig, FIELD_AMPLITUDE, FIELD_CURVE, FIELD_X, FIELD_Y, FIELD_Z,
)
from view_models.plot import format_display_unit

from ._hit_test import CursorPoint
from ._spectrogram import SpectrogramPoint

_GAP_PX = 14


def format_auto(value: float, *, decibel: bool = False) -> str:
    """4 significant digits; scientific below 1e-3 or from 1e5 (0 stays plain); dB 1 decimal."""
    if decibel:
        return f"{value:.1f}"
    if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e5):
        return f"{value:.3e}"
    return f"{value:.4g}"


def build_cursor_box_lines(
    point: CursorPoint | SpectrogramPoint,
    config: CursorConfig,
    *,
    x_unit: str = "",
    two_axes: bool = False,
    metadata: Mapping[str, Tuple[str, str]] = {},
) -> List[Tuple[str, str]]:
    """(label, text) lines in config order; fields this point cannot answer are skipped.

    ``metadata`` is the curve's ``{key: (label, text)}`` (read_curve_metadata); a
    config key found neither there nor among the values is left out silently.
    """
    if isinstance(point, SpectrogramPoint):
        decibel = "dB" in (point.color_scale or "") or point.z_unit == "dB"
        x_u = x_unit or point.x_unit
        lines: List[Tuple[str, str]] = []
        for key in config.fields:
            if key == FIELD_X:
                lines.append(("X", f"{format_auto(point.x)} {x_u}".strip()))
            elif key == FIELD_Y:
                lines.append(("Y", f"{format_auto(point.y)} {point.y_unit}".strip()))
            elif key == FIELD_Z:
                lines.append(("Z", f"{format_auto(point.z, decibel=decibel)} {point.z_unit}".strip()))
            elif key in metadata:
                lines.append(metadata[key])
        return lines

    trace = point.trace
    unit = format_display_unit(trace.unit)
    decibel = unit == "dB"
    amplitude = (trace.compute_spec or {}).get("amplitude_mode", "")
    lines = []
    for key in config.fields:
        if key == FIELD_X:
            lines.append(("X", f"{format_auto(point.x)} {x_unit}".strip()))
        elif key == FIELD_Y:
            label = "Y (Secondary)" if two_axes and point.secondary else "Y"
            lines.append((label, f"{format_auto(point.y, decibel=decibel)} {unit}".strip()))
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
