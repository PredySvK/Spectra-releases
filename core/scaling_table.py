# =====================================================================
# FILE: core/scaling_table.py
# =====================================================================
"""
The scaling table (Format x Amplitude, ACF/ECF correction, PSD, edge
correction) that turns Unscaled power (CONTEXT.md) into canonical bin energy
(P_canon, CONTEXT.md) and canonical bin energy into a displayed Format x
Amplitude view. Lives in `core/` rather than `signal_processing/` because
`core/data_block.py` needs the same formula in `NVHDataBlock.to_display_values`
and `core/` cannot import from `signal_processing/` (ADR §1.61, completing
§1.58 point 3 and §1.60). `signal_processing/dsp/steps/spectrum_scaling.py`
calls this module rather than keeping its own copy.

`scale_canonical_to_amplitude` takes `acf` and `ecf_linear` as separate
arguments and folds them into one `ratio = acf / ecf_linear`: the window's
Amplitude Correction Factor (ACF) restores the height of a single tone read
off one bin, while the Energy Correction Factor (ECF) is what a band
integral (levels.py's Band RMS) would need instead, because it sums energy
across many bins rather than reading one bin's height. `compute_band_rms`
sidesteps both by integrating canonical bin energy (P_canon) directly,
before either correction is applied.

`nyquist_is_real` is the one place that answers "does this frequency axis
carry a real, unshared Nyquist bin" -- both `fft_size` even and `n_freqs`
actually reaching all the way to it are required, because a caller can hand a
frequency axis that was truncated before scaling.
"""

from typing import Optional

import numpy as np

from core.dsp_configs import (
    VALID_AMPLITUDE_MODES,
    VALID_SPECTRUM_FORMATS,
    normalize_dsp_choice,
)


def nyquist_is_real(fft_size: int, n_freqs: int) -> bool:
    """True if bin `n_freqs - 1` is a real, unshared Nyquist bin of an rfft of size `fft_size`."""
    return (fft_size % 2 == 0) and (n_freqs == fft_size // 2 + 1)


def _edge_corrected(n_freqs: int, doubled_value: float, nyquist_real: bool) -> np.ndarray:
    """
    A single-sided doubling factor per bin: `doubled_value` for every positive
    bin, 1.0 at DC (never doubled -- it has no negative-frequency twin to fold
    in) and at Nyquist too, but only when `nyquist_real` is True.
    """
    factor = np.full(n_freqs, doubled_value, dtype=np.float64)
    factor[0] = 1.0
    if nyquist_real:
        factor[-1] = 1.0
    return factor


def compute_canonical_power(
    unscaled_power: np.ndarray,
    fft_size: int,
    sum_w2: float,
) -> np.ndarray:
    """
    Scale unscaled power (|X[k]|^2) to canonical single-sided bin energy (P_canon) in squared units.

    P_canon[k] = factor[k] * |X[k]|^2 / (fft_size * sum_w2)
    with factor 2 for f > 0, and 1 at DC and Nyquist.
    Supports 1D (n_freqs,) or multi-dimensional arrays where frequency is the last axis.
    """
    n_freqs = unscaled_power.shape[-1]
    factor = _edge_corrected(n_freqs, 2.0, nyquist_is_real(fft_size, n_freqs))
    scale = factor / (fft_size * sum_w2)
    return unscaled_power * scale


def scale_canonical_to_amplitude(
    p_canon: np.ndarray,
    *,
    spectrum_format: str,
    amplitude_mode: str,
    acf: float = 1.0,
    ecf_linear: float = 1.0,
    df: float = 1.0,
    fft_size: Optional[int] = None,
) -> np.ndarray:
    """
    Scale canonical bin energy (g^2) to the requested Format x Amplitude combination.

    Supports 1D spectra (freqs,) and 2D spectrograms (freqs, times).
    Frequency axis is assumed to be along axis 0.
    """
    amplitude_mode = normalize_dsp_choice(amplitude_mode, VALID_AMPLITUDE_MODES, "amplitude_mode")
    spectrum_format = normalize_dsp_choice(spectrum_format, VALID_SPECTRUM_FORMATS, "spectrum_format")

    n_freqs = p_canon.shape[0] if p_canon.ndim > 0 else 1
    nyquist_real = nyquist_is_real(fft_size, n_freqs) if fft_size is not None else True

    edge_factor = _edge_corrected(n_freqs, 2.0, nyquist_real)
    if p_canon.ndim > 1:
        edge_factor = edge_factor.reshape((n_freqs,) + (1,) * (p_canon.ndim - 1))

    if spectrum_format == "psd":
        return p_canon / df

    ratio = acf / (ecf_linear if ecf_linear else 1.0)
    if spectrum_format == "power":
        power = p_canon * (ratio ** 2)
        if amplitude_mode == "peak":
            power = power * edge_factor
        return power

    # linear
    if amplitude_mode == "peak":
        return np.sqrt(np.maximum(0.0, p_canon * edge_factor)) * ratio
    return np.sqrt(np.maximum(0.0, p_canon)) * ratio
