"""
The preconditions a tracked run has to meet before any trigger is placed.

Raising, not transforming: `dc_offset.py` is the module that changes a signal.
"""

import numpy as np


def require_alignable(vib_data: np.ndarray, fft_size: int) -> None:
    """
    Guard the precondition a tracked run has to meet before any trigger is placed:
    the record must be at least one block long to keep the recipes' coverage
    correction bounded (a trigger always sits inside the record, so a block is
    covered at least halfway and the gain never exceeds sqrt(2)).
    compute_averaged_spectrum enforces the same fft_size rule on its own.

    That vibration and tacho share one sample grid is checked where the tacho
    enters, before the TrackingPlan is built (result_blocks.resolve_and_convert_tacho):
    the recipes only ever see the plan, never the tacho.
    """
    if len(vib_data) < fft_size:
        raise ValueError(
            f"Input signal length ({len(vib_data)}) is shorter than FFT size ({fft_size})."
        )
