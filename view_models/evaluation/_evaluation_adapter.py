# =====================================================================
# FILE: view_models/evaluation/_evaluation_adapter.py
# =====================================================================
"""
Turns already-selected traces into the (block, identity) pairs
signal_processing.evaluation.runner.evaluate runs over -- the dock-free half
of the dock adapter ADR §1.64 point 3 asks for (issue #184). Takes
`traces`/`sources_by_path`/`result_set_labels`/`schema` a caller already has,
never a `dock` or `app_context` -- so Evaluation curve collection works from
any batch of traces, not only a focused dock (#148 Testing Decisions, Miesto
3b). `gui.workspace.evaluation_adapter.curves_for_evaluation` reads a dock to
build those arguments and calls straight through.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

from core.block_kinds import KIND_ORDER_CUT, KIND_ORDER_RESIDUAL, KIND_OVERALL_LEVEL, PARAM_F_START, PARAM_F_STOP, PARAM_ORDER
from core.data_block import NVHDataBlock
from core.evaluation import CurveBand, CurveIdentity, CurveOrder, CurveResidual, OrderOrBand
from core.filter_card_config import (
    COLUMN_CHANNEL, COLUMN_DIRECTION, COLUMN_FILE_NAME, COLUMN_PARAMETER_SET, COLUMN_RESULT_SET,
)
from view_models.curve_metadata import build_curve_metadata
from view_models.plot import Trace


def synthetic_trace_for_block(block: NVHDataBlock) -> Trace:
    """
    A minimal Trace wrapping a dock's own single content block, for a dock
    that holds its content as one block rather than a curve list (ADR §1.64
    point 3) -- today the spectrogram dock (issue #141). Goes through the same
    `identity_for_trace` machinery a curve-holding dock's real Traces do,
    rather than a second, cruder identity path for this one kind of dock.

    No Parameter Set: `compute_spec` stays None, so `identity_for_trace`
    leaves `parameter_signature` unset -- a spectrogram dock shows exactly one
    spectrogram, so there is never a second
    curve to group it with.

    The block's channel index rides along with its file path, as a curve's
    meta_ref carries it, so a file with two channels of one identity resolves
    to this block's own channel, not the first (#426, #692).
    """
    empty = np.zeros(0)
    meta_ref: Dict[str, Any] = {}
    if block.source.file_path:
        meta_ref["file_path"] = block.source.file_path
    if block.source.channel_index >= 0:
        meta_ref["channel_index"] = block.source.channel_index
    return Trace(
        x=empty, y=empty, y_raw=empty,
        channel_type=block.channel_type,
        unit=block.value_unit,
        label=block.name,
        file_name=block.source.file_name,
        channel_name=block.source.channel_name,
        meta_ref=meta_ref or None,
        block=block,
    )


def curve_identities_for_traces(
    traces: List[Trace],
    sources_by_path: Dict[str, Any],
    result_set_labels: Dict[str, str],
    schema: Dict[str, Any],
) -> List[Tuple[NVHDataBlock, CurveIdentity]]:
    """The dock-free core of the Evaluation card's path from traces to
    Evaluation input. Returns every trace that carries a block, paired with
    the CurveIdentity `runner.evaluate` groups curves by -- which of them the
    chosen Evaluation actually accepts is decided there, so a caller with no
    supported curves still gets back an empty list rather than an error here.

    Knows nothing about a dock or an `AppContext`: `sources_by_path`,
    `result_set_labels`, and `schema` are plain lookups the caller already
    has (from a `ProjectSession`, a batch run, or built by hand in a test).
    """
    traces = [trace for trace in traces if trace.block is not None]
    if not traces:
        return []

    records = build_curve_metadata(traces, sources_by_path, result_set_labels, schema or {})

    curves = []
    for trace, record in zip(traces, records):
        curve_identity = CurveIdentity(
            channel=record.get(COLUMN_CHANNEL, ""),
            direction=record.get(COLUMN_DIRECTION, ""),
            measurement=record.get(COLUMN_FILE_NAME, ""),
            source=record[COLUMN_RESULT_SET],
            parameter_set=record.get(COLUMN_PARAMETER_SET, ""),
            order_or_band=_order_or_band(trace.block),
            curve_metadata=record,
        )
        curves.append((trace.block, curve_identity))
    return curves


def _order_or_band(block: NVHDataBlock) -> OrderOrBand:
    if block.kind == KIND_ORDER_CUT:
        order = block.provenance.params.get(PARAM_ORDER)
        return CurveOrder(float(order)) if order is not None else None
    if block.kind == KIND_OVERALL_LEVEL:
        f_start = block.provenance.params.get(PARAM_F_START)
        f_stop = block.provenance.params.get(PARAM_F_STOP)
        if f_start is None:
            return None
        return CurveBand(float(f_start), float(f_stop) if f_stop is not None else None)
    if block.kind == KIND_ORDER_RESIDUAL:
        # Its band is always the Overall Level default, so the
        # name alone tells it apart, as in the plot legend.
        return CurveResidual()
    return None
