"""Pure spectrogram pixel read under the mouse without snap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from view_models.plot import SpectrogramModel, format_display_unit, resolve_image_axis_extent


@dataclass(frozen=True)
class SpectrogramPoint:
    """A point under the mouse on a spectrogram (no snap)."""

    x: float
    y: float
    z: float
    x_unit: str = ""
    y_unit: str = ""
    z_unit: str = ""
    color_scale: str = ""
    # The bottom axis's quantity (SpectrogramModel.z_quantity: "time" or "rpm").
    x_quantity: str = ""


def _cell_under(values: np.ndarray, position: float) -> Optional[int]:
    """Index of the image cell drawn at ``position`` along one axis, else None.

    The image is an even grid over ``resolve_image_axis_extent``; a descending
    axis is drawn flipped (the dock reverses it), so index 0 sits at the high end.
    """
    low, high = resolve_image_axis_extent(values)
    if not (low <= position <= high):
        return None
    n = values.size
    cell = int((position - low) / (high - low) * n)
    cell = min(max(cell, 0), n - 1)
    if n > 1 and values[0] > values[-1]:
        cell = n - 1 - cell
    return cell


def resolve_spectrogram_pixel(
    model: SpectrogramModel,
    x: float,
    y: float,
    *,
    x_scale: float = 1.0,
    y_scale: float = 1.0,
    x_unit: Optional[str] = None,
    y_unit: Optional[str] = None,
    z_unit: Optional[str] = None,
) -> Optional[SpectrogramPoint]:
    """Read X, Y, Z under the mouse on a spectrogram without snap.

    Returns None if the mouse lies outside the image extent.
    ``x`` and ``y`` are coordinates in the displayed unit.
    """
    if model is None or getattr(model, "image", None) is None:
        return None

    freqs = np.asarray(getattr(model, "freqs", None), dtype=float)
    zvals = np.asarray(getattr(model, "zvals", None), dtype=float)
    image = np.asarray(model.image)
    if freqs.size == 0 or zvals.size == 0 or image.size == 0:
        return None

    freqs_disp = freqs * y_scale
    zvals_disp = zvals * x_scale

    f_idx = _cell_under(freqs_disp, y)
    z_idx = _cell_under(zvals_disp, x)
    if f_idx is None or z_idx is None:
        return None
    z_val = float(image[f_idx, z_idx])

    actual_x_unit = getattr(model, "z_unit", "") if x_unit is None else x_unit
    actual_y_unit = "Hz" if y_unit is None else y_unit

    color_scale = getattr(model, "color_scale", "") or ""
    if z_unit is not None:
        actual_z_unit = z_unit
    elif "dB" in color_scale:
        actual_z_unit = "dB"
    else:
        block = getattr(model, "block", None)
        raw_unit = getattr(block, "value_unit", getattr(model, "value_unit", ""))
        actual_z_unit = format_display_unit(raw_unit)

    return SpectrogramPoint(
        x=x,
        y=y,
        z=z_val,
        x_unit=actual_x_unit,
        y_unit=actual_y_unit,
        z_unit=actual_z_unit,
        color_scale=color_scale,
        x_quantity=getattr(model, "z_quantity", ""),
    )
