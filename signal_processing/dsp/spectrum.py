# =====================================================================
# FILE: signal_processing/dsp/spectrum.py
# =====================================================================
"""
Recipe: an averaged single-sided spectrum, built from the steps in
signal_processing/dsp/steps/ (ADR §1.58, §1.60).

    frame_cutting    -> Frames, cut at a uniform hop and windowed
    frame_fft        -> Frames to Unscaled power, in fixed-size batches
    frame_averaging  -> the batches to one averaged Unscaled power spectrum
    spectrum_scaling -> canonical bin energy (P_canon) in squared units

Short and batch-size-agnostic on purpose: this is a recipe, not a second
workflow engine (ADR §1.58 point 2) -- it only calls the steps in order and
does not know frame_fft's batch size exists.
"""

from typing import Any, Dict, Optional, Tuple

import numpy as np

from core.benchmark import benchmark_step
from core.dsp_configs import (
    VALID_AMPLITUDE_MODES,
    VALID_AVERAGING_TYPES,
    VALID_SPECTRUM_FORMATS,
    normalize_dsp_choice,
)
from signal_processing.dsp.windows import generate_window
from signal_processing.dsp.steps.frame_cutting import cut_frames, hop_size_for_overlap
from signal_processing.dsp.steps.frame_fft import unscaled_power_batches
from signal_processing.dsp.steps.frame_averaging import average_batches
from signal_processing.dsp.steps.spectrum_scaling import compute_canonical_power, scale_canonical_to_amplitude


def compute_averaged_spectrum(
    time_data: np.ndarray,
    fs: float,
    fft_size: int,
    overlap_pct: float = 50.0,
    window_type: str = "hanning",
    amplitude_mode: str = "rms",
    spectrum_format: str = "canonical",
    averaging_type: str = "linear",
    exponential_alpha: float = 0.1,
    **window_kwargs,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """
    Computes a single-sided averaged spectrum in canonical bin energy (P_canon)
    in squared units by default, or scaled to a legacy display format (ADR §1.60).
    """
    if amplitude_mode != "rms":
        normalize_dsp_choice(amplitude_mode, VALID_AMPLITUDE_MODES, "amplitude_mode")
    if spectrum_format != "canonical":
        normalize_dsp_choice(spectrum_format, VALID_SPECTRUM_FORMATS, "spectrum_format")
    averaging_type = normalize_dsp_choice(averaging_type, VALID_AVERAGING_TYPES, "averaging_type")

    time_data = np.asarray(time_data, dtype=np.float64)
    if time_data.ndim != 1:
        raise ValueError("Input time_data must be a 1D array.")

    hop_size = hop_size_for_overlap(fft_size, overlap_pct)
    win, acf, ecf_linear, enbw_factor = generate_window(window_type, fft_size, **window_kwargs)
    sum_w2 = np.sum(win ** 2)
    enbw_hz = enbw_factor * (fs / fft_size)

    # The frame pipeline is lazy: cutting, FFT and averaging all run inside this one call.
    with benchmark_step("cut_window_fft"):
        frames = cut_frames(time_data, fft_size, hop_size, win)
        unscaled_batches = unscaled_power_batches(frames)
        avg_power = average_batches(
            unscaled_batches,
            averaging_type=averaging_type,
            exponential_alpha=exponential_alpha,
        )

    frequencies = np.fft.rfftfreq(fft_size, 1.0 / fs)
    with benchmark_step("canonical_scaling"):
        p_canon = compute_canonical_power(avg_power, fft_size=fft_size, sum_w2=sum_w2)

    if spectrum_format == "canonical":
        amplitudes = p_canon
    else:
        df = frequencies[1] - frequencies[0]
        amplitudes = scale_canonical_to_amplitude(
            p_canon, spectrum_format=spectrum_format, amplitude_mode=amplitude_mode,
            acf=acf, ecf_linear=ecf_linear, df=df, fft_size=fft_size,
        )

    meta = {
        "acf": acf,
        "ecf_linear": ecf_linear,
        "enbw_hz": enbw_hz,
        "fft_size": fft_size,
        "window_type": window_type,
        "amplitude_mode": amplitude_mode,
        "spectrum_format": spectrum_format,
        "averaging_type": averaging_type,
    }
    return frequencies, amplitudes, meta
