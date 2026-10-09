# =====================================================================
# FILE: signal_processing/dsp/steps/band_integration.py
# =====================================================================
"""
Step: band integration over a per-bin energy spectrum, with fractional bin
weights (ADR §1.58 point 4, §1.60).

Band RMS (signal_processing/dsp/levels.py) integrates a single fixed
[f_start, f_stop] with `integrate_band`; Overall Level (same module) integrates
that fixed band over every row of a tracked matrix with `integrate_band_rows`.
Both take their bin weights from `fixed_band_weights`, because a point of the
Overall Level curve must equal the Band RMS readout over the same spectrum
(ADR §1.62 point 1). Order cut (dsp/order_cut.py)
integrates a band whose centre and width move with rpm, one row per tracking
trigger, with `integrate_moving_band` -- the vectorised gather orders.py used
to do inline, moved here so the fixed-band and moving-band cases cannot drift
apart on the fractional-weight math they share. Residual (ADR §1.141)
integrates the fixed band outside the union of several moving bands with
`integrate_band_rows_outside_moving_bands`.
"""

import numpy as np


def measure_main_lobe_width_bins(window: np.ndarray, oversample: int = 16) -> float:
    """
    Width of a window's main lobe in FFT bins, from first null to first null.

    Measured from the window itself rather than looked up in a table, so it stays
    correct for any window the tool grows later. Costs one padded FFT per call.

    Rectangular gives 2 bins, Hann and Hamming 4, Blackman 6, flat-top about 10.
    This is the narrowest band that can hold all of a tone's energy, which is what
    an order cut has to integrate over to report the right amplitude.

    The null is found as the first *deep* local minimum rather than by walking
    downhill from DC. A flat-top window is built to have a flat top in the
    frequency domain, so its response barely falls at first and a downhill walk
    stops immediately -- which would report a main lobe of a fraction of a bin
    for the very window that has the widest one.
    """
    n = len(window)
    spectrum = np.abs(np.fft.rfft(window, n=n * oversample))
    peak = spectrum[0]
    if peak <= 0.0:
        return 2.0

    slope = np.diff(spectrum)
    local_minima = np.flatnonzero((slope[:-1] < 0.0) & (slope[1:] >= 0.0)) + 1

    # Keep only minima that are true nulls. Numerical ripple across a flat top can
    # register as a minimum, but never at less than one percent of the peak.
    nulls = local_minima[spectrum[local_minima] < peak * 0.01]
    if nulls.size == 0:
        return 2.0

    return 2.0 * float(nulls[0]) / oversample


def fixed_band_weights(frequencies: np.ndarray, *, f_start=None, f_stop=None) -> np.ndarray:
    """
    The fraction of each bin inside [f_start, f_stop], every bin spanning
    +/- df/2 around its centre. `frequencies` must hold at least two bins.

    A hard in/out cutoff would flip a bin between 0% and 100% as a dragged band
    crosses it, producing a visible staircase in the readout even though the
    true band content changes continuously.
    """
    df = frequencies[1] - frequencies[0]
    lower = -np.inf if f_start is None else float(f_start)
    upper = np.inf if f_stop is None else float(f_stop)
    bin_lo = frequencies - (df / 2.0)
    bin_hi = frequencies + (df / 2.0)
    overlap = np.minimum(upper, bin_hi) - np.maximum(lower, bin_lo)
    return np.clip(overlap / df, 0.0, 1.0)


def integrate_band(energy_spectrum: np.ndarray, frequencies: np.ndarray, *,
                    spectrum_format: str = "canonical", f_start=None, f_stop=None) -> float:
    """
    Weighted sum of `energy_spectrum` (canonical bin energy P_canon or ECF-scaled
    power/PSD) over [f_start, f_stop], with `fixed_band_weights`.

    Returns 0.0 for an empty band. `spectrum_format == "psd"` multiplies by
    df (a density needs the bin width to become energy); "power", "canonical", and
    "linear" do not, because their per-bin values are already energy, not
    density.
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    energy_spectrum = np.asarray(energy_spectrum, dtype=np.float64)
    if len(frequencies) < 2 or len(energy_spectrum) == 0:
        return 0.0
    df = frequencies[1] - frequencies[0]
    weight = fixed_band_weights(frequencies, f_start=f_start, f_stop=f_stop)

    if not np.any(weight > 0.0):
        return 0.0

    if spectrum_format == "psd":
        return float(df * np.sum(weight * energy_spectrum))
    return float(np.sum(weight * energy_spectrum))


def integrate_band_rows(energy_matrix: np.ndarray, frequencies: np.ndarray, *,
                        spectrum_format: str = "canonical", f_start=None,
                        f_stop=None) -> np.ndarray:
    """
    `integrate_band` of every row of `energy_matrix` (n_rows, n_freqs) over one
    fixed band -- Overall Level, one row per tracking step. Zeros for an empty band.
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    energy_matrix = np.asarray(energy_matrix, dtype=np.float64)
    if len(frequencies) < 2 or energy_matrix.shape[1] == 0:
        return np.zeros(energy_matrix.shape[0], dtype=np.float64)
    weight = fixed_band_weights(frequencies, f_start=f_start, f_stop=f_stop)

    integrated = np.sum(energy_matrix * weight[np.newaxis, :], axis=1)
    if spectrum_format == "psd":
        integrated = integrated * (frequencies[1] - frequencies[0])
    return integrated


def integrate_moving_band(energy_spectrum: np.ndarray, frequencies: np.ndarray, *,
                           spectrum_format: str = "canonical", center_freq: np.ndarray,
                           band_width: np.ndarray, min_band_hz: float,
                           nyquist_hz: float, df: float) -> np.ndarray:
    """
    One band integral per row of `energy_spectrum` (n_rows, n_freqs), where the
    band's centre and requested width both vary by row -- order cut's
    order * rpm/60 growing with speed, one row per tracking trigger.
    """
    frequencies = np.asarray(frequencies, dtype=np.float64)
    energy_spectrum = np.asarray(energy_spectrum, dtype=np.float64)
    center_freq = np.asarray(center_freq, dtype=np.float64)
    band_width = np.asarray(band_width, dtype=np.float64)

    n_freqs = len(frequencies)

    f_start, f_stop = _moving_band_edges(center_freq, band_width, min_band_hz)

    bin_lo = frequencies - (df / 2.0)
    bin_hi = frequencies + (df / 2.0)

    first_bin = np.clip(np.searchsorted(bin_hi, f_start, side="right"), 0, n_freqs - 1)
    last_bin = np.clip(np.searchsorted(bin_lo, f_stop, side="left") - 1, -1, n_freqs - 1)

    widest_band = int(np.maximum(last_bin - first_bin + 1, 0).max())
    if widest_band == 0:
        integrated = np.zeros(center_freq.shape, dtype=np.float64)
    else:
        columns = first_bin[:, np.newaxis] + np.arange(widest_band)[np.newaxis, :]
        inside_band = columns <= last_bin[:, np.newaxis]
        columns = np.clip(columns, 0, n_freqs - 1)

        overlap = (np.minimum(f_stop[:, np.newaxis], bin_hi[columns])
                   - np.maximum(f_start[:, np.newaxis], bin_lo[columns]))
        weight = np.where(inside_band, np.clip(overlap / df, 0.0, 1.0), 0.0)

        band_energy = np.take_along_axis(energy_spectrum, columns, axis=1)
        integrated = np.sum(band_energy * weight, axis=1)

    if spectrum_format == "psd":
        integrated = integrated * df

    return np.where(_measurable(center_freq, nyquist_hz, df), integrated, np.nan)


def _moving_band_edges(center_freq, band_width, min_band_hz):
    """An order band's [f_start, f_stop]: the requested width, at least the main lobe."""
    half = np.maximum(band_width, min_band_hz) / 2.0
    return np.maximum(0.0, center_freq - half), center_freq + half


def _measurable(center_freq, nyquist_hz, df):
    """Where a moving band has a value: centre at or above df and at or below Nyquist."""
    return (center_freq <= nyquist_hz) & (center_freq >= df)


def integrate_band_rows_outside_moving_bands(
        energy_matrix: np.ndarray, frequencies: np.ndarray, *, f_start: float, f_stop: float,
        center_freqs: np.ndarray, band_widths: np.ndarray, min_band_hz: float,
        nyquist_hz: float, df: float) -> np.ndarray:
    """
    Per row of canonical `energy_matrix` (n_rows, n_freqs): the energy of the
    fixed band [f_start, f_stop] outside the union of several moving bands --
    Residual (ADR §1.141). `center_freqs` and `band_widths` are (n_bands,
    n_rows); each band is the one `integrate_moving_band` integrates, and one
    that would be NaN there masks nothing. The union counts shared energy once,
    so the result never exceeds `integrate_band_rows` over the same band.
    """
    energy_matrix = np.asarray(energy_matrix, dtype=np.float64)
    center_freqs = np.atleast_2d(np.asarray(center_freqs, dtype=np.float64))
    band_widths = np.atleast_2d(np.asarray(band_widths, dtype=np.float64))
    if center_freqs.shape[0] == 0:
        return integrate_band_rows(energy_matrix, frequencies, f_start=f_start, f_stop=f_stop)
    weight = fixed_band_weights(frequencies, f_start=f_start, f_stop=f_stop)
    bin_lo = frequencies - (df / 2.0)
    bin_hi = frequencies + (df / 2.0)

    lo, hi = _moving_band_edges(center_freqs, band_widths, min_band_hz)
    lo = np.maximum(lo, f_start)
    hi = np.minimum(hi, f_stop)
    keep = _measurable(center_freqs, nyquist_hz, df) & (hi > lo)
    hi = np.where(keep, hi, lo)      # an empty interval covers nothing

    order = np.argsort(lo, axis=0)
    lo = np.take_along_axis(lo, order, axis=0)
    hi = np.take_along_axis(hi, order, axis=0)

    def _coverage(a, b):
        overlap = np.minimum(b[:, None], bin_hi) - np.maximum(a[:, None], bin_lo)
        return np.clip(overlap / df, 0.0, 1.0)

    # Sweep the bands sorted by start, merging overlaps; a merged interval is
    # added once it is closed, so the covered fractions never double up.
    covered = np.zeros_like(energy_matrix)
    cur_lo, cur_hi = lo[0], hi[0]
    for start, stop in zip(lo[1:], hi[1:]):
        closed = start > cur_hi
        covered += _coverage(cur_lo, np.where(closed, cur_hi, cur_lo))
        cur_lo = np.where(closed, start, cur_lo)
        cur_hi = np.where(closed, stop, np.maximum(cur_hi, stop))
    covered += _coverage(cur_lo, cur_hi)

    outside = np.clip(weight[np.newaxis, :] - covered, 0.0, None)
    return np.sum(energy_matrix * outside, axis=1)
