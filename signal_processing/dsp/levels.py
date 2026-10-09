# =====================================================================
# FILE: signal_processing/dsp/levels.py
# =====================================================================
"""
Recipes over one fixed frequency band, built from canonical bin energy
(P_canon, ADR §1.60, §1.61, §1.62):

Band RMS (CONTEXT.md) -- the RMS content of the band in one spectrum:

    band_integration.integrate_band -> direct Parseval sum over band
    sqrt                            -> Linear RMS

Overall Level (CONTEXT.md) -- the same number for every tracking step:

    cut_trigger_blocks    -> Windowed analysis blocks, one per tracking trigger
    canonical_power_matrix -> Blocks to Unscaled power to canonical bin energy
                              (P_canon), batch by batch, as a 2D matrix
    integrate_band_rows   -> the fixed band, row by row
    sqrt                  -> Linear RMS per step

Every KIND_SPECTRUM/KIND_SPECTROGRAM block stores P_canon, so there is no
other spectrum to integrate: a non-canonical caller is a caller error, not a
second code path. Both recipes share the bin weights, so a point of the curve
is the Band RMS of that step's spectrum.
"""

from typing import Tuple

import numpy as np

from core.benchmark import benchmark_step
from signal_processing.dsp.windows import generate_window
from signal_processing.dsp.tracking import TrackingPlan
from signal_processing.dsp.preconditions import require_alignable
from signal_processing.dsp.steps.frame_cutting import cut_trigger_blocks
from signal_processing.dsp.steps.frame_fft import canonical_power_matrix
from signal_processing.dsp.steps.band_integration import integrate_band, integrate_band_rows


def compute_band_rms(frequencies: np.ndarray, p_canon: np.ndarray, *,
                      f_start=None, f_stop=None) -> float:
    """Band RMS of canonical bin energy `p_canon` between f_start and f_stop."""
    frequencies = np.asarray(frequencies, dtype=np.float64)
    p_canon = np.asarray(p_canon, dtype=np.float64)
    if len(frequencies) < 2 or len(p_canon) == 0:
        return 0.0

    integral = integrate_band(
        p_canon, frequencies, spectrum_format="canonical",
        f_start=f_start, f_stop=f_stop,
    )
    return float(np.sqrt(max(0.0, integral)))


def compute_tracked_overall_level(
        vib_data: np.ndarray, fs: float, fft_size: int, window_type: str, *,
        f_start: float, f_stop: float, plan: TrackingPlan = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Axis values (from `plan`) and one Linear RMS level per tracking step over
    [f_start, f_stop]. The band arrives already clipped to Nyquist -- choosing
    it is the service's decision, not maths.
    """
    if plan is None:
        raise ValueError("A TrackingPlan is required.")

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
        raise ValueError("No tracking triggers generated for Overall Level. Adjust Sweep direction or limits.")

    t_idx = plan.trigger_indices
    win, _, _, _ = generate_window(window_type, fft_size)
    sum_w2 = np.sum(win ** 2)

    with benchmark_step("cut_window_fft"):
        cut_rows, coverage_gain = cut_trigger_blocks(vib_data, t_idx, win)
        frequencies = np.fft.rfftfreq(fft_size, 1.0 / fs)
        p_canon_matrix = canonical_power_matrix(cut_rows, coverage_gain, len(frequencies),
                                                fft_size=fft_size, sum_w2=sum_w2)

    with benchmark_step("band_integration"):
        band_energy = integrate_band_rows(
            p_canon_matrix, frequencies, spectrum_format="canonical",
            f_start=f_start, f_stop=f_stop,
        )
    return plan.axis_values, np.sqrt(np.maximum(0.0, band_energy))
