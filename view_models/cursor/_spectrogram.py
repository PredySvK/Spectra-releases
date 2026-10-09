"""Pure spectrogram pixel read under the mouse without snap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from view_models.plot import SpectrogramModel, format_display_unit


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

    f_min, f_max = float(np.min(freqs_disp)), float(np.max(freqs_disp))
    n_f = len(freqs_disp)
    if n_f > 1 and f_max > f_min:
        step_f = (f_max - f_min) / (n_f - 1)
        f_lo = f_min - step_f / 2.0
        f_hi = f_max + step_f / 2.0
    else:
        f_lo = f_min - 0.5
        f_hi = f_max + 0.5

    z_min, z_max = float(np.min(zvals_disp)), float(np.max(zvals_disp))
    n_z = len(zvals_disp)
    if n_z > 1 and z_max > z_min:
        step_z = (z_max - z_min) / (n_z - 1)
        z_lo = z_min - step_z / 2.0
        z_hi = z_max + step_z / 2.0
    else:
        z_lo = z_min - 0.5
        z_hi = z_max + 0.5

    if y < f_lo or y > f_hi or x < z_lo or x > z_hi:
        return None

    f_idx = int(np.argmin(np.abs(freqs_disp - y)))
    z_idx = int(np.argmin(np.abs(zvals_disp - x)))
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
    )
