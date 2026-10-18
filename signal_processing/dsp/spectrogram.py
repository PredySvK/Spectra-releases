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

from core.dsp_configs import (
    VALID_AMPLITUDE_MODES,
    VALID_SPECTRUM_FORMATS,
    normalize_dsp_choice,
)
from signal_processing.dsp.tracking import TrackingPlan
from signal_processing.dsp.tracked_matrix import (
    WindowDescription, compute_tracked_power_matrix, require_plan,
)
from signal_processing.dsp.steps.spectrum_scaling import scale_canonical_to_amplitude


def compute_tracked_spectrogram_with_window(
    vib_data: np.ndarray,
    fs: float,
    fft_size: int,
    window_type: str = "hann",
    amplitude_mode: str = "rms",
    spectrum_format: str = "canonical",
    plan: Optional[TrackingPlan] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, WindowDescription]:
    """
    Computes a tracked waterfall as canonical bin energy (P_canon) per bin
    in squared units by default, or scaled to a legacy display format.
    The window description rides along so a caller building the result block does
    not generate the same window a second time.
    """
    require_plan(plan)

    if amplitude_mode != "rms":
        normalize_dsp_choice(amplitude_mode, VALID_AMPLITUDE_MODES, "amplitude_mode")
    if spectrum_format != "canonical":
        normalize_dsp_choice(spectrum_format, VALID_SPECTRUM_FORMATS, "spectrum_format")

    matrix = compute_tracked_power_matrix(
        vib_data, fs, fft_size, window_type, plan,
        no_trigger_message="No tracking triggers generated. Adjust Sweep direction or limits.",
    )
    frequencies, window = matrix.frequencies, matrix.window
    t_val = plan.axis_values

    # Transpose to (frequency, z) -- pyqtgraph and build_spectrogram_block both
    # expect frequency as the first axis, but every row above is one trigger.
    p_canon_t = matrix.p_canon.T
    if spectrum_format == "canonical":
        magnitude_matrix = p_canon_t
    else:
        df = frequencies[1] - frequencies[0]
        magnitude_matrix = scale_canonical_to_amplitude(
            p_canon_t, spectrum_format=spectrum_format, amplitude_mode=amplitude_mode,
            acf=window.acf, ecf_linear=window.ecf_linear, df=df, fft_size=fft_size,
        )

    return frequencies, t_val, magnitude_matrix, window


def compute_tracked_spectrogram(
    vib_data: np.ndarray,
    fs: float,
    fft_size: int,
    window_type: str = "hann",
    amplitude_mode: str = "rms",
    spectrum_format: str = "canonical",
    plan: Optional[TrackingPlan] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """`compute_tracked_spectrogram_with_window` without the window description."""
    return compute_tracked_spectrogram_with_window(
        vib_data, fs, fft_size, window_type, amplitude_mode, spectrum_format, plan)[:3]
