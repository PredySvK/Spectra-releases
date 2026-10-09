# =====================================================================
# FILE: signal_processing/evaluation/topn_eval.py
# =====================================================================
"""
Top-N maxima (ADR §1.64 point 7, CONTEXT.md Local maximum / Top-N maxima): the
N highest Local maxima of a curve, ranked by height -- never "dominant
maxima" ranked by prominence, and never padded with empty rows when a curve
holds fewer humps than N.

A Local maximum is a point that stands clear of its neighbours by a minimum
distance along the X axis and a minimum prominence in dB; a point at either
end of the range counts and carries the edge flag on its SingleValue -- the
range being the curve's finite samples, shared with Max (_edge.py).
Distance and prominence are computed in amplitude dB (the square root of
canonical power for spectra, ADR §1.64 point 4) so a channel sensitivity
change or an RMS<->Peak toggle never changes which maxima are picked --
scaling every sample by the same factor shifts every dB value by the same
constant and leaves differences (and therefore prominence) untouched.

NaN samples and non-positive amplitude samples are both treated as -inf dB
(tests/test_evaluation.py pins this rule): they can never be picked as a
maximum, and they always act as a valley deep enough to satisfy any
prominence requirement on their side of a neighbouring peak.
"""

from typing import List, Optional, Tuple

import numpy as np

from core.data_block import NVHDataBlock
from core.evaluation import CurveIdentity, SingleValue
from signal_processing.evaluation._edge import resolve_edge

DEFAULT_N = 3
DEFAULT_MIN_PROMINENCE_DB = 3.0
DEFAULT_MIN_DISTANCE_FRACTION = 0.05  # of the curve's own X-axis range, used only when min_distance is not given


def _amplitude_db(block: NVHDataBlock) -> np.ndarray:
    """Amplitude in dB, fixed at Linear/RMS regardless of the table's current
    display switches (ADR §1.64 point 4) -- the position of a maximum must
    not move when the user flips RMS<->Peak or Linear<->Power<->PSD."""
    values, _unit = block.to_display_values("linear", "rms")
    amplitude = np.asarray(values, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 20.0 * np.log10(amplitude)
    return np.where(np.isfinite(db), db, -np.inf)


def _local_maxima_candidates(db: np.ndarray) -> List[int]:
    """Every point (or plateau, represented by its middle sample) that is not
    lower than its existing neighbours -- edges included, since they have
    only one neighbour to clear. -inf points (NaN or zero amplitude) never
    qualify, however flat the run around them."""
    n = len(db)
    candidates: List[int] = []
    j = 0
    while j < n:
        k = j
        while k + 1 < n and db[k + 1] == db[j]:
            k += 1
        if np.isfinite(db[j]):
            left_lower = (j == 0) or (db[j - 1] < db[j])
            right_lower = (k == n - 1) or (db[k + 1] < db[k])
            if left_lower and right_lower:
                candidates.append((j + k) // 2)
        j = k + 1
    return candidates


def _side_min(db: np.ndarray, idx: int, step: int) -> Optional[float]:
    """Scans away from idx in one direction until a higher sample or the
    array boundary; returns the lowest value crossed, or None if idx is
    already at that boundary. Topographic prominence definition
    (scipy.signal.peak_prominences), extended to treat a missing side at an
    edge as imposing no constraint rather than an infinite valley."""
    n = len(db)
    j = idx + step
    if j < 0 or j >= n:
        return None
    running_min = db[idx]
    while 0 <= j < n:
        if db[j] > db[idx]:
            break
        running_min = min(running_min, db[j])
        j += step
    return running_min


def _prominence_db(db: np.ndarray, idx: int) -> float:
    sides = [v for v in (_side_min(db, idx, -1), _side_min(db, idx, 1)) if v is not None]
    if not sides:
        return float("inf")
    return float(db[idx] - max(sides))


def local_maxima_by_height(
    db: np.ndarray,
    x: np.ndarray,
    min_distance: float,
    min_prominence_db: float,
    n: Optional[int] = None,
) -> List[int]:
    """The Local maximum rule itself, on any dB curve over any X axis: sample
    indices of every point clearing `min_prominence_db` and standing at least
    `min_distance` (in X units) from every taller pick, tallest first, at
    most `n` of them (all when None). Shared with Dominant orders (#142),
    which runs it on an order map instead of a curve -- one rule, not two."""
    candidates = _local_maxima_candidates(db)
    qualifying = [idx for idx in candidates if _prominence_db(db, idx) >= min_prominence_db]
    qualifying.sort(key=lambda idx: db[idx], reverse=True)

    selected: List[int] = []
    for idx in qualifying:
        if n is not None and len(selected) >= n:
            break
        if all(abs(x[idx] - x[picked]) >= min_distance for picked in selected):
            selected.append(idx)
    return selected


def extract_topn_maxima(
    block: NVHDataBlock,
    identity: CurveIdentity,
    n: int = DEFAULT_N,
    min_distance: Optional[float] = None,
    min_prominence_db: float = DEFAULT_MIN_PROMINENCE_DB,
) -> Tuple[SingleValue, ...]:
    """Extraction on one curve (ADR §1.64 point 2). Returns zero to n rows,
    ranked by height, never padded to n and never a dash row -- a curve with
    no qualifying hump simply contributes no rows to the table (unlike Max,
    which always returns exactly one)."""
    db = _amplitude_db(block)
    x = np.asarray(block.primary_axis.values, dtype=float)

    if min_distance is None:
        finite_x = x[np.isfinite(x)]
        axis_range = float(finite_x.max() - finite_x.min()) if finite_x.size else 0.0
        min_distance = axis_range * DEFAULT_MIN_DISTANCE_FRACTION

    selected = local_maxima_by_height(db, x, min_distance, min_prominence_db, n)

    return tuple(
        SingleValue(identity=identity, block=block, sample_index=idx,
                    is_edge=resolve_edge(block.values, idx))
        for idx in selected
    )
