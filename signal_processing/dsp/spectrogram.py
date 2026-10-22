# =====================================================================
# FILE: signal_processing/dsp/spectrogram.py
# =====================================================================
"""
Recipe: a tracked waterfall (rpm-tracked or time-tracked), built from the
steps in signal_processing/dsp/steps/:

    cut_trigger_blocks    -> Windowed analysis blocks, one per tracking trigger
    canonical_power_matrix -> Blocks to Unscaled power to canonical bin energy
                              (P_canon) in squared units, batch by batch, as a 2D matrix

One row per tracking trigger, one column per frequency bin. Like the other
recipes this is short on purpose: tracking logic lives in
signal_processing.dsp.tracking, cutting and windowing live in the steps, and
this file only threads the pieces together.
"""

from typing import Optional, Tuple

import numpy as np

from signal_processing.dsp.tracking import TrackingPlan
from signal_processing.dsp.tracked_matrix import (
    WindowDescription, compute_tracked_power_matrix, require_plan,
)


def compute_tracked_spectrogram_with_window(
    vib_data: np.ndarray,
    fs: float,
    fft_size: int,
    window_type: str = "hann",
    plan: Optional[TrackingPlan] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, WindowDescription]:
    """
    Computes a tracked waterfall as canonical bin energy (P_canon) per bin in
    squared units; Format x Amplitude is applied at display time.
    The window description rides along so a caller building the result block does
    not generate the same window a second time.
    """
    require_plan(plan)

    matrix = compute_tracked_power_matrix(
        vib_data, fs, fft_size, window_type, plan,
        no_trigger_message="No tracking triggers generated. Adjust Sweep direction or limits.",
    )
    # Transpose to (frequency, z) -- pyqtgraph and build_spectrogram_block both
    # expect frequency as the first axis, but every row above is one trigger.
    return matrix.frequencies, plan.axis_values, matrix.p_canon.T, matrix.window
