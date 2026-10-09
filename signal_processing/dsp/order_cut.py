# =====================================================================
# FILE: signal_processing/dsp/order_cut.py
# =====================================================================
"""
Recipe: tracked order cuts (ADR §1.58, §1.60), built from the steps in
signal_processing/dsp/steps/:

    cut_trigger_blocks    -> Windowed analysis blocks, one per tracking trigger
    canonical_power_matrix -> Blocks to Unscaled power to canonical bin energy
                              (P_canon) in squared units, batch by batch, as a 2D matrix
    integrate_moving_band -> Order * rpm/60 moving band per trigger, with
                             measure_main_lobe_width_bins widening
    sqrt                  -> Linear RMS amplitude per order (ADR §1.60)

Returns (rpm_axis, {order: ndarray}) where each array holds native Linear RMS
amplitudes with NaNs where the order fell below the FFT resolution df or above
the Nyquist frequency. `compute_tracked_order_cuts_with_overall_level` also
returns the Overall Level of one fixed band and its Residual -- the part outside
every order's band -- from the same P_canon (ADR §1.141).

`order_cut_from_spectrogram` (ADR §1.64 point 8) is the same tail --
`_order_cut_amplitude_from_canonical` -- reused directly on an already-computed
rpm-tracked spectrogram's own canonical matrix instead of a fresh cut from raw
samples: a spectrogram and an order cut with the same FFT, window, step and
order width already agree on p_canon by construction (ADR §1.58 point 6), so
this needs no raw measurement to read.
"""

from typing import Dict, List, Optional, Tuple

import numpy as np

from core.benchmark import benchmark_step
from core.dsp_configs import VALID_AMPLITUDE_MODES, normalize_dsp_choice
from signal_processing.dsp.windows import generate_window
from signal_processing.dsp.tracking import TrackingPlan
from signal_processing.dsp.preconditions import require_alignable
from signal_processing.dsp.steps.frame_cutting import cut_trigger_blocks
from signal_processing.dsp.steps.frame_fft import canonical_power_matrix
from signal_processing.dsp.steps.band_integration import (
    integrate_band_rows,
    integrate_band_rows_outside_moving_bands,
    integrate_moving_band,
    measure_main_lobe_width_bins,
)


def _order_cut_amplitude_from_canonical(
        p_canon_matrix: np.ndarray, frequencies: np.ndarray, rpm_axis: np.ndarray,
        order: float, order_width: float, min_band_hz: float, nyquist_hz: float, df: float,
) -> np.ndarray:
    """One order's Linear RMS amplitude per row of an already-built canonical
    energy matrix -- the shared tail of `compute_tracked_order_cuts` and
    `order_cut_from_spectrogram`, so the two cannot drift apart on the moving
    band or the sqrt (ADR §1.60)."""
    center_freq = (order * rpm_axis) / 60.0
    band_width = order_width * (rpm_axis / 60.0)
    power_integral = integrate_moving_band(
        p_canon_matrix, frequencies,
        spectrum_format="canonical",
        center_freq=center_freq,
        band_width=band_width,
        min_band_hz=min_band_hz,
        nyquist_hz=nyquist_hz,
        df=df,
    )
    return np.sqrt(np.maximum(0.0, power_integral))


def order_cut_from_spectrogram(
        p_canon_matrix: np.ndarray, frequencies: np.ndarray, rpm_axis: np.ndarray,
        orders_to_extract: List[float], order_width: float,
        fft_size: int, window_type: str,
) -> Dict[float, np.ndarray]:
    """
    Order cut(s) sliced directly out of an existing rpm-tracked spectrogram's
    own canonical energy matrix, rather than a fresh cut from raw samples (ADR
    §1.64 point 8). Used by the Typed orders Evaluation (#141) and, on a
    refined order, by Dominant orders (#142).

    `p_canon_matrix` is (n_rpm_steps, n_freqs) -- one row per spectrogram
    column, the transpose of `NVHDataBlock.spectrogram`'s own (frequency, z)
    storage order. `fft_size` and `window_type` must be the ones the
    spectrogram was actually computed with (its own `SpectralProcessing`) --
    that is what makes the result agree with `compute_tracked_order_cuts` over
    the same file at float precision, not by coincidence.
    """
    win, _acf, _ecf_linear, _enbw = generate_window(window_type, fft_size)
    df = float(frequencies[1] - frequencies[0])
    nyquist_hz = float(frequencies[-1])
    min_band_hz = measure_main_lobe_width_bins(win) * df

    return {
        float(o): _order_cut_amplitude_from_canonical(
            p_canon_matrix, frequencies, rpm_axis, o, order_width, min_band_hz, nyquist_hz, df,
        )
        for o in orders_to_extract
    }


def compute_tracked_order_cuts(
        vib_data: np.ndarray, fs: float, orders_to_extract: List[float],
        order_width: float, fft_size: int, window_type: str,
        amplitude_mode: str = "rms", plan: TrackingPlan = None,
) -> Tuple[np.ndarray, Dict[float, np.ndarray]]:
    """Rpm axis (from `plan`) and one Linear RMS amplitude array per requested order (ADR §1.60)."""
    rpm_axis, order_cuts, _, _ = _tracked_order_cuts(
        vib_data, fs, orders_to_extract, order_width, fft_size, window_type,
        amplitude_mode, plan, overall_band=None,
    )
    return rpm_axis, order_cuts


def compute_tracked_order_cuts_with_overall_level(
        vib_data: np.ndarray, fs: float, orders_to_extract: List[float],
        order_width: float, fft_size: int, window_type: str, *,
        f_start: float, f_stop: float, plan: TrackingPlan = None,
) -> Tuple[np.ndarray, Dict[float, np.ndarray], np.ndarray, np.ndarray]:
    """
    `compute_tracked_order_cuts` plus the Overall Level of [f_start, f_stop]
    and its Residual per step, integrated from the same p_canon (ADR §1.141
    point 1). The level is the band sum `levels.compute_tracked_overall_level`
    makes, so a point is the standalone Overall Level of that step; the
    Residual leaves out every bin share inside at least one order's band
    (point 2), so explained² + Residual² = Overall Level².
    """
    return _tracked_order_cuts(
        vib_data, fs, orders_to_extract, order_width, fft_size, window_type,
        "rms", plan, overall_band=(f_start, f_stop),
    )


def _tracked_order_cuts(
        vib_data: np.ndarray, fs: float, orders_to_extract: List[float],
        order_width: float, fft_size: int, window_type: str,
        amplitude_mode: str, plan: TrackingPlan,
        overall_band: Optional[Tuple[float, float]],
) -> Tuple[np.ndarray, Dict[float, np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
    if plan is None:
        raise ValueError("A TrackingPlan is required.")

    if amplitude_mode != "rms":
        normalize_dsp_choice(amplitude_mode, VALID_AMPLITUDE_MODES, "amplitude_mode")

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
        raise ValueError("No tracking triggers generated for Order Extraction.")

    t_idx = plan.trigger_indices
    rpm_axis = plan.axis_values

    win, acf, ecf_linear, _ = generate_window(window_type, fft_size)
    sum_w2 = np.sum(win ** 2)

    with benchmark_step("cut_window_fft"):
        cut_rows, coverage_gain = cut_trigger_blocks(vib_data, t_idx, win)
        frequencies = np.fft.rfftfreq(fft_size, 1.0 / fs)
        p_canon_matrix = canonical_power_matrix(cut_rows, coverage_gain, len(frequencies),
                                                fft_size=fft_size, sum_w2=sum_w2)

    df = fs / fft_size
    nyquist_hz = fs / 2.0
    with benchmark_step("coverage_main_lobe_nan_check"):
        min_band_hz = measure_main_lobe_width_bins(win) * df

    # Order cuts integrate moving band directly from canonical energy (Parseval)
    # sqrt(integral) yields native Linear RMS
    with benchmark_step("band_integration"):
        order_cuts = {
            float(o): _order_cut_amplitude_from_canonical(
                p_canon_matrix, frequencies, rpm_axis, o, order_width, min_band_hz, nyquist_hz, df,
            )
            for o in orders_to_extract
        }

    # Every requested order came back entirely NaN: each one sits below the FFT
    # bin width for the whole RPM span, or above Nyquist, so there is nothing to
    # plot (ADR §1.23). An error here lets the caller surface a clear reason.
    with benchmark_step("coverage_main_lobe_nan_check"):
        nothing_measurable = orders_to_extract and not any(
            np.any(np.isfinite(vals)) for vals in order_cuts.values())
    if nothing_measurable:
        raise ValueError(
            f"None of the requested orders {orders_to_extract} are measurable for this "
            f"RPM range ({rpm_axis.min():.0f}-{rpm_axis.max():.0f} rpm): every order cut "
            f"falls below the {df:.2f} Hz FFT resolution (FFT size {fft_size}) or above "
            f"the {nyquist_hz:.0f} Hz Nyquist limit. Use a smaller FFT size, lower orders, "
            "or check the tacho RPM range."
        )

    if overall_band is None:
        return rpm_axis, order_cuts, None, None
    with benchmark_step("band_integration"):
        band_energy = integrate_band_rows(
            p_canon_matrix, frequencies, spectrum_format="canonical",
            f_start=overall_band[0], f_stop=overall_band[1],
        )
        orders = np.asarray(orders_to_extract, dtype=np.float64)[:, np.newaxis]
        residual_energy = integrate_band_rows_outside_moving_bands(
            p_canon_matrix, frequencies, f_start=overall_band[0], f_stop=overall_band[1],
            center_freqs=orders * rpm_axis / 60.0,
            band_widths=np.broadcast_to(order_width * rpm_axis / 60.0, (len(orders), len(rpm_axis))),
            min_band_hz=min_band_hz, nyquist_hz=nyquist_hz, df=df,
        )
    return (rpm_axis, order_cuts, np.sqrt(np.maximum(0.0, band_energy)),
            np.sqrt(np.maximum(0.0, residual_energy)))
