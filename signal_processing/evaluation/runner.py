# =====================================================================
# FILE: signal_processing/evaluation/runner.py
# =====================================================================
"""
The one entry function from a dock's curves to an Evaluation table (ADR
§1.64 point 2): "Evaluation + krivky (blok + identita) -> Evaluation table".

Deliberately thin -- filter by accepted block kind, extract one Single value
per curve, pack the table; an Evaluation whose maxima depend on Amplitude
runs once per Amplitude. Extraction-on-a-curve (registry.py's `extract`)
is kept separate from this aggregation on purpose: the former is what a
future workflow runner would call once per measurement x channel, this
aggregation would not.
"""

from typing import Any, Dict, Optional, Sequence, Tuple

from core.data_block import NVHDataBlock
from core.evaluation import CurveIdentity, EvaluationTable, SingleValue
from signal_processing.evaluation.registry import EVALUATIONS


def evaluate(evaluation_name: str,
            curves: Sequence[Tuple[NVHDataBlock, CurveIdentity]],
            params: Optional[Dict[str, Any]] = None) -> EvaluationTable:
    spec = EVALUATIONS[evaluation_name]
    resolved_params = dict(params or {})
    accepted = [(block, identity) for block, identity in curves
                if block.kind in spec.accepted_block_kinds]

    def extract_all(**amplitude: str) -> Tuple[SingleValue, ...]:
        return tuple(
            single
            for block, identity in accepted
            for single in spec.extract(block, identity, **resolved_params, **amplitude)
        )

    if not spec.ranks_by_amplitude:
        return EvaluationTable(evaluation_name=evaluation_name, params=resolved_params,
                               rows=extract_all())
    return EvaluationTable(evaluation_name=evaluation_name, params=resolved_params,
                           rows=extract_all(amplitude_mode="rms"),
                           peak_rows=extract_all(amplitude_mode="peak"))
