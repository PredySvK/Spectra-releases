# =====================================================================
# FILE: signal_processing/dsp/spectrum.py
# =====================================================================
"""
Recipe: an averaged single-sided spectrum, built from the steps in
signal_processing/dsp/steps/.

    frame_cutting    -> Frames, cut at a uniform hop and windowed
    frame_fft        -> Frames to Unscaled power, in fixed-size batches
    frame_averaging  -> the batches, less any frame an invalid (NaN) sample
                        fell in, to one averaged Unscaled power spectrum
    spectrum_scaling -> canonical bin energy (P_canon) in squared units

Short and batch-size-agnostic on purpose: this is a recipe, not a second
workflow engine -- it only calls the steps in order and
does not know frame_fft's batch size exists.
"""

from typing import Any, Dict, Optional, Tuple

import numpy as np

from core.benchmark import benchmark_step
from core.block_kinds import META_FRAMES, META_SKIPPED_FRAMES
from core.dsp_configs import VALID_AVERAGING_TYPES, normalize_dsp_choice
from signal_processing.dsp.windows import generate_window
from signal_processing.dsp.steps.frame_cutting import cut_frames, hop_size_for_overlap
from signal_processing.dsp.steps.frame_fft import unscaled_power_batches
from signal_processing.dsp.steps.frame_averaging import FrameCount, average_batches, skip_invalid_frames
from signal_processing.dsp.steps.spectrum_scaling import compute_canonical_power


def compute_averaged_spectrum(
    time_data: np.ndarray,
    fs: float,
    fft_size: int,
    overlap_pct: float = 50.0,
    window_type: str = "hanning",
    averaging_type: str = "linear",
    exponential_alpha: float = 0.1,
    **window_kwargs,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """
    Computes a single-sided averaged spectrum in canonical bin energy (P_canon)
    in squared units; Format x Amplitude is applied at display time.
    """
    averaging_type = normalize_dsp_choice(averaging_type, VALID_AVERAGING_TYPES, "averaging_type")

    time_data = np.asarray(time_data, dtype=np.float64)
    if time_data.ndim != 1:
        raise ValueError("Input time_data must be a 1D array.")

    hop_size = hop_size_for_overlap(fft_size, overlap_pct)
    win, acf, ecf_linear, enbw_factor = generate_window(window_type, fft_size, **window_kwargs)
    sum_w2 = np.sum(win ** 2)
    enbw_hz = enbw_factor * (fs / fft_size)

    # The frame pipeline is lazy: cutting, FFT and averaging all run inside this one call.
    frame_count = FrameCount()
    with benchmark_step("cut_window_fft"):
        frames = cut_frames(time_data, fft_size, hop_size, win)
        unscaled_batches = skip_invalid_frames(unscaled_power_batches(frames), frame_count)
        avg_power = average_batches(
            unscaled_batches,
            averaging_type=averaging_type,
            exponential_alpha=exponential_alpha,
        )

    frequencies = np.fft.rfftfreq(fft_size, 1.0 / fs)
    with benchmark_step("canonical_scaling"):
        p_canon = compute_canonical_power(avg_power, fft_size=fft_size, sum_w2=sum_w2)

    meta = {
        "acf": acf,
        "ecf_linear": ecf_linear,
        "enbw_hz": enbw_hz,
        "fft_size": fft_size,
        "window_type": window_type,
        "averaging_type": averaging_type,
        META_FRAMES: frame_count.frames,
        META_SKIPPED_FRAMES: frame_count.skipped,
    }
    return frequencies, p_canon, meta
