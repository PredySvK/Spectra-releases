"""
The spectrogram as it is drawn -- the one shape the image, its axes, the colour
bar and the Cursor all read (#893).

``SpectrogramModel`` keeps native values (ADR §1.130: the global X axis unit is
a display rescale, never a model rebuild). ``build_drawn_spectrogram`` applies
that rescale and lays both axes out ascending, the matrix with them, so nothing
downstream rescales, flips or picks a unit on its own.

Axis letters follow CONTEXT.md "Spectrogram axes": X is the bottom axis (time or
speed), Y the frequency, Z the colour value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

from core.axis_projections import X_AXIS_NATIVE, resolve_x_axis_display

from ._image_extent import resolve_image_axis_extent
from ._legend_settings import format_display_unit
from ._plot_model import SpectrogramModel


@dataclass(frozen=True)
class DrawnSpectrogram:
    """A spectrogram in the units and order it is drawn in.

    ``x`` and ``y`` are ascending cell centres in the displayed unit; ``z`` is
    the colour matrix in ``(y, x)`` order matching them. ``x_extent`` /
    ``y_extent`` are where the image starts and ends along each axis (half a
    cell past the outer centres).
    """

    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    x_extent: Tuple[float, float]
    y_extent: Tuple[float, float]
    x_label: str
    x_unit: str
    x_quantity: str
    y_label: str
    y_unit: str
    z_unit: str
    decibel: bool
    title: str = ""


def _ascending(values: np.ndarray, matrix: np.ndarray, axis: int) -> Tuple[np.ndarray, np.ndarray]:
    if values.size > 1 and values[0] > values[-1]:
        return values[::-1], np.flip(matrix, axis=axis)
    return values, matrix


def build_drawn_spectrogram(model: SpectrogramModel, x_axis_unit: str = X_AXIS_NATIVE) -> DrawnSpectrogram:
    """``model`` as it is drawn under the global X axis unit ``x_axis_unit``."""
    frequency_axis = resolve_x_axis_display("frequency", x_axis_unit)
    bottom_axis = resolve_x_axis_display(model.x_quantity, x_axis_unit)

    x = np.asarray(model.x, dtype=np.float64) * bottom_axis.scale
    y = np.asarray(model.y, dtype=np.float64) * frequency_axis.scale
    z = np.asarray(model.z)
    x, z = _ascending(x, z, axis=1)
    y, z = _ascending(y, z, axis=0)

    decibel = "dB" in (model.color_scale or "")
    return DrawnSpectrogram(
        x=x,
        y=y,
        z=z,
        x_extent=resolve_image_axis_extent(x),
        y_extent=resolve_image_axis_extent(y),
        x_label=model.x_label,
        x_unit=bottom_axis.unit if bottom_axis.scale != 1.0 else model.x_unit,
        x_quantity=model.x_quantity,
        y_label=frequency_axis.label,
        y_unit=frequency_axis.unit,
        z_unit="dB" if decibel else format_display_unit(model.z_unit),
        decibel=decibel,
        title=model.title,
    )
