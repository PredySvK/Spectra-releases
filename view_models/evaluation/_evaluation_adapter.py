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

from core.block_kinds import KIND_ORDER_CUT, KIND_OVERALL_LEVEL, PARAM_F_START, PARAM_F_STOP, PARAM_ORDER
from core.data_block import NVHDataBlock
from core.evaluation import CurveIdentity
from core.filter_card_config import (
    COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_CHANNEL_TYPE,
    COLUMN_DATA_POOL_LABEL, COLUMN_DIRECTION, COLUMN_FILE_NAME,
    COLUMN_ORDER, COLUMN_PARAMETER_SET, COLUMN_RESULT_SET,
)
from view_models.plot import Trace
from view_models.trace_filter import identity_for_trace
from io_modules.metadata_schema import parse_value
from selection.parameter_sets import parameter_set_for_signature, parameter_sets_from_traces
from selection.source_facets import resolve_source_channel


def synthetic_trace_for_block(block: NVHDataBlock) -> Trace:
    """
    A minimal Trace wrapping a dock's own single content block, for a dock
    that holds its content as one block rather than a curve list (ADR §1.64
    point 3) -- today the spectrogram dock (issue #141). Goes through the same
    `identity_for_trace` machinery a curve-holding dock's real Traces do,
    rather than a second, cruder identity path for this one kind of dock.

    No Parameter Set: `compute_spec` stays None, so `identity_for_trace`
    leaves `parameter_signature` unset -- a spectrogram dock shows exactly one
    spectrogram (ADR §1.64 "Vedome nedorobené"), so there is never a second
    curve to group it with.
    """
    empty = np.zeros(0)
    return Trace(
        x=empty, y=empty, y_raw=empty,
        channel_type=block.channel_type,
        unit=block.value_unit,
        label=block.name,
        file_name=block.source.file_name,
        channel_name=block.source.channel_name,
        meta_ref={"file_path": block.source.file_path} if block.source.file_path else None,
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

    identities = [identity_for_trace(trace, sources_by_path, result_set_labels) for trace in traces]
    parameter_sets = parameter_sets_from_traces(identities)

    curves = []
    for trace, identity in zip(traces, identities):
        parameter_set = parameter_set_for_signature(identity.parameter_signature, tuple(parameter_sets))

        # Build metadata dictionary covering Identity, Calculated, and Schema fields
        meta_dict: Dict[str, Any] = {}

        # 1. Identity built-ins
        meta_dict[COLUMN_CHANNEL] = identity.channel_identity[0] or trace.channel_name
        if identity.direction:
            meta_dict[COLUMN_DIRECTION] = identity.direction
        if identity.channel_type:
            meta_dict[COLUMN_CHANNEL_TYPE] = identity.channel_type
        if identity.file_name or trace.file_name:
            meta_dict[COLUMN_FILE_NAME] = identity.file_name or trace.file_name
        if identity.data_pool_label:
            meta_dict[COLUMN_DATA_POOL_LABEL] = identity.data_pool_label
        meta_dict[COLUMN_RESULT_SET] = identity.result_set_label or "Live"

        # 2. Calculated built-ins
        if identity.result_kind:
            meta_dict[COLUMN_ANALYSIS_TYPE] = identity.result_kind
        if identity.order is not None:
            meta_dict[COLUMN_ORDER] = identity.order
        if parameter_set is not None and parameter_set.label:
            meta_dict[COLUMN_PARAMETER_SET] = parameter_set.label

        # 3. Source typed metadata
        source = identity.source
        if source is not None:
            if getattr(source, "parsed_metadata", None):
                for k, v in source.parsed_metadata.items():
                    # A channel-layer field's parsed_metadata value is the
                    # file's first channel (channel_summary_value) -- never
                    # this curve's; it comes from the curve's own channel below.
                    if (schema or {}).get(k, {}).get("layer") == "channel":
                        continue
                    if v is not None and v != "":
                        meta_dict[k] = v

            if getattr(source, "channels", None):
                ch_meta = resolve_source_channel(source, identity.channel_identity,
                                                 getattr(identity, "channel_index", None))
                if ch_meta:
                    for k, v in ch_meta.items():
                        if k in schema and v is not None and v != "":
                            cfg = schema[k]
                            kind = cfg.get("kind", "str")
                            parsed = parse_value(v, kind, date_format=cfg.get("date_format"))
                            if parsed is not None:
                                meta_dict[k] = parsed

            if getattr(source, "excel_metadata", None):
                for k, v in source.excel_metadata.items():
                    if k in schema and k not in meta_dict and v is not None and v != "":
                        cfg = schema[k]
                        kind = cfg.get("kind", "str")
                        parsed = parse_value(v, kind, date_format=cfg.get("date_format"))
                        if parsed is not None:
                            meta_dict[k] = parsed

            if getattr(source, "file_metadata", None):
                for k, v in source.file_metadata.items():
                    if k in schema and k not in meta_dict and v is not None and v != "":
                        cfg = schema[k]
                        kind = cfg.get("kind", "str")
                        parsed = parse_value(v, kind, date_format=cfg.get("date_format"))
                        if parsed is not None:
                            meta_dict[k] = parsed

        # 4. Trace meta_ref and block metadata fallback
        if trace.meta_ref:
            for k, v in trace.meta_ref.items():
                if k not in meta_dict and v is not None and v != "":
                    cfg = schema.get(k, {}) if schema else {}
                    kind = cfg.get("kind", "str")
                    parsed = parse_value(v, kind, date_format=cfg.get("date_format"))
                    if parsed is not None:
                        meta_dict[k] = parsed

        if trace.block and hasattr(trace.block, "metadata") and trace.block.metadata:
            for k, v in trace.block.metadata.items():
                if k not in meta_dict and v is not None and v != "":
                    cfg = schema.get(k, {}) if schema else {}
                    kind = cfg.get("kind", "str")
                    parsed = parse_value(v, kind, date_format=cfg.get("date_format"))
                    if parsed is not None:
                        meta_dict[k] = parsed

        curve_identity = CurveIdentity(
            channel=identity.channel_identity[0] or trace.channel_name,
            direction=identity.direction or "",
            measurement=identity.file_name or trace.file_name,
            source=identity.result_set_label or "Live",
            parameter_set=parameter_set.label if parameter_set is not None else "",
            order_or_band=_order_or_band(trace.block),
            metadata=meta_dict,
        )
        curves.append((trace.block, curve_identity))
    return curves


def _order_or_band(block: NVHDataBlock) -> str:
    if block.kind == KIND_ORDER_CUT:
        order = block.provenance.params.get(PARAM_ORDER)
        return f"Order {order:g}" if order is not None else ""
    if block.kind == KIND_OVERALL_LEVEL:
        f_start = block.provenance.params.get(PARAM_F_START)
        f_stop = block.provenance.params.get(PARAM_F_STOP)
        if f_start is None:
            return ""
        stop_text = f"{f_stop:g} Hz" if f_stop is not None else "Full Bandwidth"
        return f"{f_start:g}-{stop_text}"
    return ""
