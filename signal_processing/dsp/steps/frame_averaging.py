# =====================================================================
# FILE: signal_processing/dsp/steps/frame_averaging.py
# =====================================================================
"""
Step: combine a stream of Unscaled power batches (frame_fft) into one
spectrum -- linear, peak hold, or exponential.

Consumes batches one at a time so the running result is the only thing ever
held in memory; a spectrum never needs every frame's power at once
(ADR §1.58 point 13). `skip_invalid_frames` sits in front of it and drops the
frames an invalid (NaN) sample fell in, so one bad sample costs those frames,
not the whole spectrum (#673).
"""

from dataclasses import dataclass
from typing import Iterator

import numpy as np

from core.dsp_configs import VALID_AVERAGING_TYPES, normalize_dsp_choice


@dataclass
class FrameCount:
    """How many frames `skip_invalid_frames` saw and how many of them it dropped."""
    frames: int = 0
    skipped: int = 0


def skip_invalid_frames(power_batches: Iterator[np.ndarray], count: FrameCount) -> Iterator[np.ndarray]:
    """
    `power_batches` without the frames holding a non-finite value, tallied in
    `count`. Raises once the stream ends if every frame was dropped: an average
    of nothing must not reach the user as a spectrum.
    """
    for batch in power_batches:
        valid = np.all(np.isfinite(batch), axis=1)
        n_valid = int(np.count_nonzero(valid))
        count.frames += len(batch)
        count.skipped += len(batch) - n_valid
        if n_valid == len(batch):
            yield batch
        elif n_valid:
            yield batch[valid]
    if count.frames and count.skipped == count.frames:
        raise ValueError(
            f"Every one of the {count.frames} frames holds an invalid (NaN) sample; "
            "there is nothing left to average."
        )


def average_batches(power_batches: Iterator[np.ndarray], averaging_type: str,
                     exponential_alpha: float = 0.1) -> np.ndarray:
    """The averaged Unscaled power spectrum, combined according to `averaging_type`."""
    averaging_type = normalize_dsp_choice(averaging_type, VALID_AVERAGING_TYPES, "averaging_type")
    if averaging_type == "peak_hold":
        return _peak_hold(power_batches)
    if averaging_type == "exponential":
        return _exponential(power_batches, exponential_alpha)
    return _linear(power_batches)


def _linear(power_batches: Iterator[np.ndarray]) -> np.ndarray:
    total = None
    n_frames = 0
    for batch in power_batches:
        n_frames += len(batch)
        batch_sum = np.sum(batch, axis=0)
        total = batch_sum if total is None else total + batch_sum
    if total is None:
        raise ValueError("No frames to average.")
    return total / n_frames


def _peak_hold(power_batches: Iterator[np.ndarray]) -> np.ndarray:
    result = None
    for batch in power_batches:
        batch_max = np.max(batch, axis=0)
        result = batch_max if result is None else np.maximum(result, batch_max)
    if result is None:
        raise ValueError("No frames to average.")
    return result


def _exponential(power_batches: Iterator[np.ndarray], exponential_alpha: float) -> np.ndarray:
    # A recurrence over individual frames, in frame order, regardless of how
    # they were grouped into batches -- exactly the loop this replaced, just
    # fed from a batch iterator instead of a fully-materialised array, so the
    # result stays bit-identical.
    alpha = max(0.0, min(1.0, float(exponential_alpha)))
    result = None
    for batch in power_batches:
        for frame_power in batch:
            result = frame_power if result is None else (1.0 - alpha) * result + alpha * frame_power
    if result is None:
        raise ValueError("No frames to average.")
    return result
