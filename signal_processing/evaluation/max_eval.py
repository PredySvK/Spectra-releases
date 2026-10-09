# =====================================================================
# FILE: signal_processing/evaluation/max_eval.py
# =====================================================================
"""
Max (ADR §1.64 point 6, CONTEXT.md Max): the highest valid value of a curve
and where it sits. Not Top-N maxima with N = 1 -- it has no parameters and
always returns exactly one Single value, empty rather than absent when every
sample is NaN (a curve entirely below resolution or above Nyquist).
"""

import numpy as np

from core.data_block import NVHDataBlock
from core.evaluation import CurveIdentity, SingleValue
from signal_processing.evaluation._edge import resolve_edge


def extract_max(block: NVHDataBlock, identity: CurveIdentity) -> SingleValue:
    """Extraction on one curve (ADR §1.64 point 2) -- separate from
    aggregation across curves, which lives in runner.evaluate."""
    values = np.asarray(block.values, dtype=float)
    finite = np.isfinite(values)
    if not finite.any():
        return SingleValue(identity=identity, block=block, sample_index=None)

    masked = np.where(finite, values, -np.inf)
    index = int(np.argmax(masked))
    return SingleValue(identity=identity, block=block, sample_index=index,
                       is_edge=resolve_edge(values, index))
