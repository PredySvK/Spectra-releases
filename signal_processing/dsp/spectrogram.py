# =====================================================================
# FILE: signal_processing/dsp/spectrogram.py
# =====================================================================
"""
Recipe: a tracked waterfall (rpm-tracked or time-tracked), built from the
steps in signal_processing/dsp/steps/ (ADR §1.58, §1.60):

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

from core.benchmark import benchmark_step
from core.dsp_configs import (
    VALID_AMPLITUDE_MODES,
    VALID_SPECTRUM_FORMATS,
    normalize_dsp_choice,
)
from signal_processing.dsp.windows import generate_window
from signal_processing.dsp.tracking import TrackingPlan
from signal_processing.dsp.preconditions import require_alignable
from signal_processing.dsp.steps.frame_cutting import cut_trigger_blocks
from signal_processing.dsp.steps.frame_fft import canonical_power_matrix
from signal_processing.dsp.steps.spectrum_scaling import scale_canonical_to_amplitude


def compute_tracked_spectrogram(
    vib_data: np.ndarray,
    fs: float,
    fft_size: int,
    window_type: str = "hann",
    amplitude_mode: str = "rms",
    spectrum_format: str = "canonical",
    plan: Optional[TrackingPlan] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Computes a tracked waterfall as canonical bin energy (P_canon) per bin
    in squared units by default, or scaled to a legacy display format (ADR §1.60).
    """
    if plan is None:
        raise ValueError("A TrackingPlan is required.")

    if amplitude_mode != "rms":
        normalize_dsp_choice(amplitude_mode, VALID_AMPLITUDE_MODES, "amplitude_mode")
    if spectrum_format != "canonical":
        normalize_dsp_choice(spectrum_format, VALID_SPECTRUM_FORMATS, "spectrum_format")

    require_alignable(vib_data, fft_size)

    if not plan.matches(fs, len(vib_data)):
        raise ValueError(
            f"Tracking plan does not fit this request: plan was built for "
            f"{plan.n_samples} samples at {plan.fs} Hz; request is "
            f"{len(vib_data)} samples at {fs} Hz."
        )

    if plan.trigger_indices.size == 0:
        if plan.step <= 0:
            raise ValueError(f"Tracking step must be positive, got {plan.step}.")
        raise ValueError("No tracking triggers generated. Adjust Sweep direction or limits.")

    t_idx = plan.trigger_indices
    t_val = plan.axis_values

    win, acf, ecf_linear, enbw_factor = generate_window(window_type, fft_size)
    sum_w2 = np.sum(win ** 2)

    with benchmark_step("cut_window_fft"):
        cut_rows, coverage_gain = cut_trigger_blocks(vib_data, t_idx, win)
        frequencies = np.fft.rfftfreq(fft_size, 1.0 / fs)
        p_canon_matrix = canonical_power_matrix(cut_rows, coverage_gain, len(frequencies),
                                                fft_size=fft_size, sum_w2=sum_w2)

    # Transpose to (frequency, z) -- pyqtgraph and build_spectrogram_block both
    # expect frequency as the first axis, but every row above is one trigger.
    p_canon_t = p_canon_matrix.T
    if spectrum_format == "canonical":
        magnitude_matrix = p_canon_t
    else:
        df = frequencies[1] - frequencies[0]
        magnitude_matrix = scale_canonical_to_amplitude(
            p_canon_t, spectrum_format=spectrum_format, amplitude_mode=amplitude_mode,
            acf=acf, ecf_linear=ecf_linear, df=df, fft_size=fft_size,
        )

    return frequencies, t_val, magnitude_matrix
