# =====================================================================
# FILE: signal_processing/evaluation/registry.py
# =====================================================================
"""
The register of Evaluations (ADR §1.64 point 3): which block kinds each one
accepts, so the GUI's evaluation picker and runner.evaluate both branch on
data instead of an `if/elif` on analysis kind -- the same shape as
core/block_kinds.py's register of block kinds.

Adding an Evaluation (Top-N maxima, Dominant orders, ...) is one entry in
EVALUATIONS plus one extraction function; nothing else in the codebase learns
its name. One literal dict rather than a `register()` call per entry: this
module lives in signal_processing/, where module-level mutable state that
gets written to after import is banned for determinism
(tests/test_architecture.py) -- a dict built once and only ever read is a
constant table, not state.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Tuple

from core.block_kinds import KIND_ORDER_CUT, KIND_OVERALL_LEVEL, KIND_SPECTROGRAM, KIND_SPECTRUM
from core.data_block import NVHDataBlock
from core.evaluation import CurveIdentity, SingleValue
from signal_processing.evaluation.dominant_orders_eval import extract_dominant_orders
from signal_processing.evaluation.max_eval import extract_max
from signal_processing.evaluation.topn_eval import extract_topn_maxima
from signal_processing.evaluation.typed_orders_eval import extract_typed_orders

# Curve-shaped kinds only -- a spectrogram is a map (ADR §1.64 "Vedome
# nedorobené": Dominant orders is the evaluation that reads one). Shared by
# every Evaluation below since a graph's own visible curves are never more
# than these three kinds.
_CURVE_BLOCK_KINDS = (KIND_SPECTRUM, KIND_ORDER_CUT, KIND_OVERALL_LEVEL)


@dataclass(frozen=True)
class EvaluationSpec:
    name: str
    label: str
    accepted_block_kinds: Tuple[str, ...]
    # Always a sequence -- Max wraps its single SingleValue in a 1-tuple so
    # runner.evaluate has one flattening rule for every Evaluation, present
    # and future (Top-N maxima returns 0..N).
    extract: Callable[..., Tuple[SingleValue, ...]]
    help_topic: str


def _max_rows(block: NVHDataBlock, identity: CurveIdentity, **_params) -> Tuple[SingleValue, ...]:
    return (extract_max(block, identity),)


EVALUATIONS: Dict[str, EvaluationSpec] = {
    "max": EvaluationSpec(
        name="max",
        label="Max",
        accepted_block_kinds=_CURVE_BLOCK_KINDS,
        extract=_max_rows,
        help_topic="evaluation_max",
    ),
    "topn_maxima": EvaluationSpec(
        name="topn_maxima",
        label="Top-N maxima",
        accepted_block_kinds=_CURVE_BLOCK_KINDS,
        extract=extract_topn_maxima,
        help_topic="evaluation_topn_maxima",
    ),
    "typed_orders": EvaluationSpec(
        name="typed_orders",
        label="Typed orders",
        # A spectrogram is a map, not a curve -- the one Evaluation below that
        # reads KIND_SPECTROGRAM instead of _CURVE_BLOCK_KINDS. runner.evaluate
        # filters every curve by accepted_block_kinds before extract ever runs,
        # so a dock showing spectra/order cuts/Overall Level offers this
        # Evaluation too (the combo box does not branch on dock type) but its
        # curves never reach extract_typed_orders at all -- the table just
        # comes back empty, the same "unsupported dock" message Max/Top-N
        # maxima give a spectrogram dock in the other direction. A time-tracked
        # spectrogram does reach extract_typed_orders (it is KIND_SPECTROGRAM)
        # but gives no rows there -- its z axis is not "rpm".
        accepted_block_kinds=(KIND_SPECTROGRAM,),
        extract=extract_typed_orders,
        help_topic="evaluation_typed_orders",
    ),
    "dominant_orders": EvaluationSpec(
        name="dominant_orders",
        label="Dominant orders",
        # Same map-not-curve filtering as Typed orders above, including the
        # time-tracked spectrogram that reaches extract but gives no rows.
        accepted_block_kinds=(KIND_SPECTROGRAM,),
        extract=extract_dominant_orders,
        help_topic="evaluation_dominant_orders",
    ),
}
