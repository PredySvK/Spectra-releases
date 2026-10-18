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
from signal_processing.dsp.tracking import TrackingPlan
from signal_processing.dsp.tracked_matrix import compute_tracked_power_matrix, require_plan
from signal_processing.dsp.steps.band_integration import integrate_band, integrate_band_rows


def compute_band_rms(frequencies: np.ndarray, p_canon: np.ndarray, *,
                      f_start=None, f_stop=None) -> float:
    """
    Band RMS of canonical bin energy `p_canon` between f_start and f_stop.
    Raises on a NaN bin inside the band: an unmeasurable band is not zero
    energy, and the readout shows the error as unavailable (#673).
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    p_canon = np.asarray(p_canon, dtype=np.float64)
    if len(frequencies) < 2 or len(p_canon) == 0:
        return 0.0

    integral = integrate_band(
        p_canon, frequencies, spectrum_format="canonical",
        f_start=f_start, f_stop=f_stop,
    )
    if np.isnan(integral):
        raise ValueError("The spectrum has invalid (NaN) values inside the band.")
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
    require_plan(plan)
    matrix = compute_tracked_power_matrix(
        vib_data, fs, fft_size, window_type, plan,
        no_trigger_message="No tracking triggers generated for Overall Level. Adjust Sweep direction or limits.",
    )

    with benchmark_step("band_integration"):
        band_energy = integrate_band_rows(
            matrix.p_canon, matrix.frequencies, spectrum_format="canonical",
            f_start=f_start, f_stop=f_stop,
        )
    return plan.axis_values, np.sqrt(np.maximum(0.0, band_energy))
