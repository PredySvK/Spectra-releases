# =====================================================================
# FILE: signal_processing/evaluation/_edge.py
# =====================================================================
"""
The edge flag on a Single value (ADR §1.64 point 7), one rule for Max and
Top-N maxima: a sample is on the edge when it is the first or last *finite*
sample of its curve. An order cut above Nyquist (or below resolution) has a
NaN tail, so its valid range ends before the array does -- a maximum on the
last valid sample is just as cut off by the range as one on the last index.
"""

import numpy as np


def resolve_edge(values: np.ndarray, index: int) -> bool:
    finite_indices = np.flatnonzero(np.isfinite(np.asarray(values, dtype=float)))
    if finite_indices.size == 0:
        return False
    return index == int(finite_indices[0]) or index == int(finite_indices[-1])
