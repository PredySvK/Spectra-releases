"""Pure spectrogram pixel read under the mouse without snap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from view_models.plot import DrawnSpectrogram


@dataclass(frozen=True)
class SpectrogramPoint:
    """A point under the mouse on a spectrogram (no snap)."""

    x: float
    y: float
    z: float
    x_unit: str = ""
    y_unit: str = ""
    z_unit: str = ""
    decibel: bool = False
    # The bottom axis's quantity ("time" or "rpm").
    x_quantity: str = ""


def _cell_under(values: np.ndarray, extent: tuple[float, float], position: float) -> Optional[int]:
    """Index of the image cell drawn at ``position`` along one ascending axis, else None.

    The image is an even grid of ``values.size`` cells over ``extent``.
    """
    low, high = extent
    if not (low <= position <= high):
        return None
    n = values.size
    cell = int((position - low) / (high - low) * n)
    return min(max(cell, 0), n - 1)


def resolve_spectrogram_pixel(drawn: Optional[DrawnSpectrogram], x: float, y: float) -> Optional[SpectrogramPoint]:
    """Read X, Y, Z under the mouse on the spectrogram as it is drawn, without snap.

    ``x`` and ``y`` are coordinates in the displayed unit. Returns None if the
    mouse lies outside the image. Units and cells come from ``drawn`` alone, so
    the box says exactly what the image and colour bar show (#893).
    """
    if drawn is None or drawn.x.size == 0 or drawn.y.size == 0 or drawn.z.size == 0:
        return None
    y_idx = _cell_under(drawn.y, drawn.y_extent, y)
    x_idx = _cell_under(drawn.x, drawn.x_extent, x)
    if y_idx is None or x_idx is None:
        return None
    return SpectrogramPoint(
        x=x,
        y=y,
        z=float(drawn.z[y_idx, x_idx]),
        x_unit=drawn.x_unit,
        y_unit=drawn.y_unit,
        z_unit=drawn.z_unit,
        decibel=drawn.decibel,
        x_quantity=drawn.x_quantity,
    )
