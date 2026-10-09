# =====================================================================
# FILE: signal_processing/dsp/steps/frame_fft.py
# =====================================================================
"""
Step: Frames to Unscaled power (CONTEXT.md), one fixed-size batch at a time.

Batch size is a constant inside this step, not a recipe argument -- ADR §1.58
point 13 measured batches of 256 frames as both the fastest and the lowest
peak-memory option on a 75 s and a 600 s record (probe_spectrum_batch.py,
2026-09-11): fft-ing every frame in one call is somewhat faster than the
frame-by-frame Python loop it replaced, but holds every frame's power in
memory at once (1.4 GB on the 600 s record); batches of 256 give almost the
same speed at a 24 MB peak because a batch fits the CPU cache.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterator

import numpy as np
import scipy.fft

from core.scaling_table import compute_canonical_power

_BATCH_SIZE = 256
# ponytail: fixed cap, measured knee on a 24-core PC; tune if a target box differs.
FFT_WORKERS = min(8, os.cpu_count() or 1)


def unscaled_power_batches(frames: Iterator[np.ndarray]) -> Iterator[np.ndarray]:
    """
    Unscaled power (|rfft(frame)|^2) of `frames`, an iterable of equal-length
    windowed Frames, yielded as 2D batches shaped (batch_size, n_freqs) --
    the last batch may be shorter. frame_averaging consumes this stream
    without ever needing every frame's power at once.
    """
    batch = []
    for frame in frames:
        batch.append(frame)
        if len(batch) == _BATCH_SIZE:
            yield _power_of(batch)
            batch = []
    if batch:
        yield _power_of(batch)


def _power_of(frames_batch) -> np.ndarray:
    """
    The FFT runs in float32 on scipy.fft: on a 256 x 16k batch 8.5 ms against
    numpy's 21.5 ms in float64 (numpy's own float32 FFT is no faster). It costs
    float32 noise, ~1e-7 of the strongest bin (#501). The power comes back in
    float64, so averaging and scaling downstream keep their precision.
    """
    fft_vals = scipy.fft.rfft(np.asarray(frames_batch, dtype=np.float32), axis=1)
    return np.square(np.abs(fft_vals), dtype=np.float64)


def canonical_power_matrix(cut_rows: Callable[[int, int], np.ndarray], coverage_gain: np.ndarray,
                           n_freqs: int, fft_size: int, sum_w2: float) -> np.ndarray:
    """
    Every frame's canonical bin energy (P_canon) as one (n_frames, n_freqs)
    matrix -- a spectrogram row per frame -- where `cut_rows(lo, hi)` and
    `coverage_gain` come from frame_cutting.cut_trigger_blocks.

    Each batch's Unscaled power gets its rows' coverage gain and the canonical
    scaling while it is still in the CPU cache, instead of two more passes over
    the whole matrix afterwards (#503: 229 MB each on the real 75 s run-up).
    Same element-wise operations in the same order as those passes,
    so the result is bit-identical to them.

    The same batches of _BATCH_SIZE as unscaled_power_batches, but run on a
    thread pool: numpy's FFT and the windowing release the GIL, so batches
    proceed truly in parallel, and each fills its own rows of the matrix.
    Measured on the real 75 s run-up (3490 triggers, FFT 16k): 0.45 s -> 0.15 s
    per channel at 8 threads; beyond 8 it is memory-bound and stops improving.
    Same batch boundaries, so the result is bit-identical to a serial fill.
    """
    n_frames = len(coverage_gain)
    matrix = np.empty((n_frames, n_freqs), dtype=np.float64)

    def fill(lo: int) -> None:
        hi = min(lo + _BATCH_SIZE, n_frames)
        power = _power_of(cut_rows(lo, hi))
        power *= coverage_gain[lo:hi, np.newaxis]
        matrix[lo:hi] = compute_canonical_power(power, fft_size=fft_size, sum_w2=sum_w2)

    with ThreadPoolExecutor(max_workers=FFT_WORKERS) as pool:
        # list() re-raises the first worker exception here instead of dropping it.
        list(pool.map(fill, range(0, n_frames, _BATCH_SIZE)))
    return matrix
