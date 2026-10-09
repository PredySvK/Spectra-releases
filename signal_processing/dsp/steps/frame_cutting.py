# =====================================================================
# FILE: signal_processing/dsp/steps/frame_cutting.py
# =====================================================================
"""
Step: cut a time signal into Frames -- either at a uniform hop (spectrum) or
centred on external trigger indices (spectrogram, ADR §1.23) -- and window
them (CONTEXT.md).

Owns the one thing every averaged-spectrum or spectrogram result shares
before it becomes Unscaled power: where the frames start, and applying the
window to each of them. Nothing here knows about FFTs, batching or scaling
-- those are the next steps in the recipe.
"""

from typing import Callable, Iterator, Tuple

import numpy as np


def hop_size_for_overlap(fft_size: int, overlap_pct: float) -> int:
    """The hop (in samples) between consecutive frame starts for a given overlap."""
    overlap_fraction = max(0.0, min(99.0, float(overlap_pct))) / 100.0
    return max(1, int(round(fft_size * (1.0 - overlap_fraction))))


def frame_starts(n_samples: int, fft_size: int, hop_size: int) -> np.ndarray:
    """
    Start sample index of every frame at a uniform hop within a record.

    Raises rather than returning zero frames: a signal shorter than one block
    would otherwise silently need zero-padding, which is not what Testlab's
    classic block averaging does (see the docstring this replaced).
    """
    if n_samples < fft_size:
        raise ValueError(
            f"Input signal length ({n_samples}) is shorter than FFT size ({fft_size})."
        )
    # n_samples >= fft_size and hop_size >= 1 here, so the floor division is
    # never negative and n_frames is at least 1.
    n_frames = (n_samples - fft_size) // hop_size + 1
    return np.arange(n_frames, dtype=np.int64) * hop_size


def cut_frames(time_data: np.ndarray, fft_size: int, hop_size: int,
               window: np.ndarray) -> Iterator[np.ndarray]:
    """
    Yields one windowed Frame at a time, in order, without holding the whole
    set at once -- frame_fft consumes this lazily so a spectrum never
    materialises every frame's Unscaled power together (ADR §1.58 point 13).
    """
    starts = frame_starts(len(time_data), fft_size, hop_size)
    for start in starts:
        frame_samples = time_data[start:start + fft_size]
        yield frame_samples * window


def cut_trigger_blocks(time_data: np.ndarray, trigger_indices: np.ndarray,
                        window: np.ndarray) -> Tuple[Callable[[int, int], np.ndarray], np.ndarray]:
    """
    Cuts one fft_size block centred on every trigger and windows them.

    Returns (cut_rows, coverage_gain). `cut_rows(lo, hi)` cuts and windows the
    blocks of triggers lo..hi on demand, so frame_fft can work through a long
    run-up batch by batch on several threads without the whole windowed matrix
    ever existing at once (3490 triggers at FFT 16k were 457 MB of it).
    coverage_gain restores a block that ran off the end of the record to the
    level the same content would read further inside it.

    Shared by a tracked spectrogram, an order cut and Overall Level because they
    must cut blocks the *same* way: they are routinely run on one file with the
    same step, and an rpm row of the spectrogram is expected to agree with the
    order cut at that speed. Two copies of this loop drifted apart once
    already (the coverage correction below had to be written twice), and a
    difference here is invisible in the plot -- it shows up only as an
    amplitude mismatch the user cannot attribute to anything.

    idx is a fractional sample index (see generate_tracking_triggers' crossing
    interpolation). Rounding to the *nearest* sample removes the systematic
    up-to-one-dt late bias that np.where's "+1" rule used to skew every window
    by, without the cost of linearly resampling the window: linear interpolation
    between samples is a low-pass filter, so it would attenuate high orders'
    true amplitude rather than just re-centring the block in time.

    The gain is bounded: the caller guarantees the record is at least one block
    long and a trigger always sits inside it, so a block is covered at least
    halfway and the correction never exceeds sqrt(2) in amplitude.
    """
    fft_size = len(window)
    half_fft = fft_size // 2
    n_triggers = len(trigger_indices)
    n_samples = len(time_data)

    # How much of the window's energy each block's real samples actually sit on.
    # A trigger closer than fft_size/2 to either end of the record leaves part of
    # its block as zeros, but the window is still applied across the whole block
    # and every scaling branch downstream still divides by the whole window -- so
    # the first and last points used to read up to 29% low while looking like any
    # other measurement.
    covered_w2 = np.zeros(n_triggers, dtype=np.float64)
    sum_w2 = np.sum(window ** 2)

    starts = np.rint(np.asarray(trigger_indices, dtype=np.float64)).astype(np.int64) - half_fft
    # A block spans centre +/- fft_size//2, which is one sample short of
    # fft_size when fft_size is odd -- the trailing column then stays zero, and
    # the energy correction has to account for that rather than assume a block
    # fills the window.
    span = 2 * half_fft

    # Whole blocks are cut in one gather per batch rather than one Python
    # iteration each. sliding_window_view is a view, so this costs exactly one
    # copy of the blocks that are actually used -- no (n_triggers, fft_size)
    # index matrix. Every block of a run-up is whole except the one or two at
    # the very ends, and those keep the explicit path below: their covered_w2 is
    # a partial sum with no closed form, and a cumulative-sum shortcut would
    # round differently from the whole-block sum and make a whole block's gain
    # 1.0 only to within float noise instead of exactly.
    whole = (starts >= 0) & (starts + span <= n_samples)
    blocks = None
    if span and span <= n_samples and np.any(whole):
        blocks = np.lib.stride_tricks.sliding_window_view(time_data, span)
        covered_w2[whole] = np.sum(window[:span] ** 2)

    def partial_extent(start_idx: int) -> Tuple[int, int, int]:
        valid_start = max(0, start_idx)
        valid_end = min(n_samples, start_idx + span)
        return valid_start, max(0, -start_idx), valid_end - valid_start

    for i in np.flatnonzero(~whole):
        _, chunk_start, chunk_len = partial_extent(int(starts[i]))
        if chunk_len > 0:
            covered_w2[i] = np.sum(window[chunk_start:chunk_start + chunk_len] ** 2)

    def cut_rows(lo: int, hi: int) -> np.ndarray:
        # float32: frame_fft transforms in float32 anyway, and this halves the copy (#501).
        rows = np.zeros((hi - lo, fft_size), dtype=np.float32)
        row_whole = whole[lo:hi]
        if blocks is not None and np.any(row_whole):
            rows[np.flatnonzero(row_whole), :span] = blocks[starts[lo:hi][row_whole]]
        for j in np.flatnonzero(~row_whole):
            valid_start, chunk_start, chunk_len = partial_extent(int(starts[lo + j]))
            if chunk_len > 0:
                rows[j, chunk_start:chunk_start + chunk_len] =                     time_data[valid_start:valid_start + chunk_len]
        rows *= window
        return rows

    coverage_gain = np.where(covered_w2 > 0.0, sum_w2 / np.maximum(covered_w2, 1e-300), 1.0)
    return cut_rows, coverage_gain
