"""Cursor Box content and placement, and the text of one curve field."""

from __future__ import annotations

from types import MappingProxyType
from typing import List, Mapping, Optional, Tuple

from core.cursor_config import (
    CursorConfig, FIELD_AMPLITUDE, FIELD_CURVE, FIELD_X, FIELD_Y, FIELD_Z,
)
from core.units import UnitPreferences
from view_models.display_prefix import resolve_number_format
from view_models.plot import Trace, format_display_unit, resolve_ordinate_quantity

from ._hit_test import CursorPoint
from ._spectrogram import SpectrogramPoint

# A curve without metadata; read-only, so a shared default can never be filled in.
_NO_METADATA: Mapping[str, Tuple[str, str]] = MappingProxyType({})

_GAP_PX = 14


def build_cursor_box_lines(
    point: CursorPoint | SpectrogramPoint,
    config: CursorConfig,
    *,
    x_unit: str = "",
    x_quantity: str = "",
    two_axes: bool = False,
    metadata: Mapping[str, Tuple[str, str]] = _NO_METADATA,
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
        decibel = point.decibel
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

    lines = []
    for key in config.fields:
        if key == FIELD_X:
            lines.append(("X", text(point.x, x_unit, quantity=x_quantity)))
            continue
        line = build_curve_field(
            point.trace, key, point.y, two_axes=two_axes, metadata=metadata, prefs=prefs)
        if line is not None:
            lines.append(line)
    return lines


def build_curve_field(
    trace: Trace,
    key: str,
    y: float,
    *,
    two_axes: bool = False,
    metadata: Mapping[str, Tuple[str, str]] = _NO_METADATA,
    prefs: UnitPreferences | None = None,
) -> Optional[Tuple[str, str]]:
    """``(label, text)`` of one field of one curve at the value ``y``, or None.

    The one place a curve's field becomes text, so a Cursor Box line and a Track
    table cell agree. ``y`` is in the curve's displayed unit (``Trace.y``); no
    picked point is needed. Answers Y, Curve, Amplitude and the curve's
    ``metadata`` (read_curve_metadata); None for a field the curve has no value
    for and for X and Z, which belong to the graph, not the curve.
    """
    if key == FIELD_Y:
        unit = format_display_unit(trace.unit)
        label = "Y (Secondary)" if two_axes and trace.axis == "secondary" else "Y"
        number_format = resolve_number_format(
            unit, prefs, quantity=resolve_ordinate_quantity(trace), db=unit == "dB")
        return label, number_format.format_with_unit(y)
    if key == FIELD_CURVE:
        return ("Curve", trace.label) if trace.label else None
    if key == FIELD_AMPLITUDE:
        amplitude = trace.amplitude_mode
        if not amplitude:
            return None
        return "Amplitude", {"rms": "RMS", "peak": "Peak"}.get(amplitude, str(amplitude))
    if key in (FIELD_X, FIELD_Z):
        return None
    return metadata.get(key)


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
