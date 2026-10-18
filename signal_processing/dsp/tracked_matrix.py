# =====================================================================
# FILE: signal_processing/dsp/tracked_matrix.py
# =====================================================================
"""
The shared front half of every tracked analysis: spectrogram,
order cuts and Overall Level all start the same way and differ only in their tail.

    plan validation       -> the request fits the TrackingPlan
    generate_window       -> window plus its factors, generated once
    cut_trigger_blocks    -> Windowed analysis blocks, one per tracking trigger
    rfftfreq              -> the bin frequencies
    canonical_power_matrix -> P_canon, one row per trigger, one column per bin

The tails (waterfall scaling, moving-band integration, fixed-band integration)
stay in their own recipes. Analyses do not share the matrix with each other: each
call cuts and transforms its own, exactly as before this front half was shared.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from core.benchmark import benchmark_step
from signal_processing.dsp.preconditions import require_alignable
from signal_processing.dsp.steps.frame_cutting import cut_trigger_blocks
from signal_processing.dsp.steps.frame_fft import canonical_power_matrix
from signal_processing.dsp.tracking import TrackingPlan
from signal_processing.dsp.windows import generate_window


@dataclass(frozen=True)
class WindowDescription:
    """The window an analysis used and the factors derived from it."""
    samples: np.ndarray
    acf: float
    ecf_linear: float
    enbw_factor: float


@dataclass(frozen=True)
class TrackedPowerMatrix:
    """Canonical bin energy per trigger (row-major) with its bin frequencies and window."""
    p_canon: np.ndarray      # (n_triggers, n_frequencies)
    frequencies: np.ndarray  # (n_frequencies,)
    window: WindowDescription


def require_plan(plan: Optional[TrackingPlan]) -> TrackingPlan:
    """The plan a tracked analysis was asked to run on; a missing one is a caller error."""
    if plan is None:
        raise ValueError("A TrackingPlan is required.")
    return plan


def compute_tracked_power_matrix(
        vib_data: np.ndarray, fs: float, fft_size: int, window_type: str,
        plan: TrackingPlan, *, no_trigger_message: str,
) -> TrackedPowerMatrix:
    """
    Validate `vib_data` against `plan`, then cut, window and transform one block
    per trigger into canonical bin energy. `no_trigger_message` is the analysis's
    own wording for a plan that placed no triggers; a non-positive step is
    reported the same way for all of them.
    """
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
        raise ValueError(no_trigger_message)

    win, acf, ecf_linear, enbw_factor = generate_window(window_type, fft_size)
    sum_w2 = np.sum(win ** 2)

    with benchmark_step("cut_window_fft"):
        cut_rows, coverage_gain = cut_trigger_blocks(vib_data, plan.trigger_indices, win)
        frequencies = np.fft.rfftfreq(fft_size, 1.0 / fs)
        p_canon = canonical_power_matrix(cut_rows, coverage_gain, len(frequencies),
                                         fft_size=fft_size, sum_w2=sum_w2)

    return TrackedPowerMatrix(
        p_canon=p_canon, frequencies=frequencies,
        window=WindowDescription(win, acf, ecf_linear, enbw_factor),
    )
