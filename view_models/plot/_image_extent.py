"""The span one axis of a spectrogram image covers (renderer and cursor share it)."""

from __future__ import annotations

import numpy as np


def resolve_image_axis_extent(values) -> tuple[float, float]:
    """Return ``(low, high)``: where the image cells along one axis start and end.

    Each value is the centre of a cell, so the image reaches half a bin past
    the first and last value (an even grid of ``(n - 1)`` steps). One bin, or
    values that do not span anything, get a unit-wide cell (+-0.5). An empty
    axis has no extent and returns ``(0.0, 0.0)``. The order of ``values`` does
    not matter, so a descending axis spans the same range as an ascending one.
    """
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return 0.0, 0.0
    v_min, v_max = float(np.min(arr)), float(np.max(arr))
    if arr.size > 1 and v_max > v_min:
        half_step = (v_max - v_min) / (arr.size - 1) / 2.0
        return v_min - half_step, v_max + half_step
    return v_min - 0.5, v_max + 0.5
