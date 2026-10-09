# =====================================================================
# FILE: view_models/trace_filter/_trace_identity.py
# =====================================================================
"""
Turning one already-drawn Trace into the TraceIdentity a filter facet is
built from (`selection.trace_filter.TraceIdentity`), plus the parameter-set
signature reading straight off a Trace's own compute_spec.

Lives in ``view_models/trace_filter`` (Floor 3: presentation state, no Qt).
Qt-free, unit-testable without a QApplication.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.block_kinds import KIND_ORDER_RESIDUAL, KIND_OVERALL_LEVEL, KINDS, PARAM_COMPUTATION, PARAM_ORDER
from core.project_model import SourceEntry
from view_models.plot import Trace
from io_modules.measurement_files import canonical_path
from selection.channel_identity import split_channel_base_and_direction
from selection.parameter_sets import parameter_signature
from selection.source_facets import resolve_channel_type
from selection.trace_filter import Signature, TraceIdentity, identities_match

# x_quantity -> kind, for the one-axis (curve-shaped) kinds with an
# unambiguous (single) axis quantity -- a spectrogram's two axes never reach a
# Trace (ARCHITECTURE_DECISIONS §1.30, result_content._is_comparable_kind
# already excludes it upstream). Kinds with alternative quantities (e.g.
# overall_level's "rpm|time") cannot be uniquely reverse-mapped from
# x_quantity alone, so they are excluded here and resolve their kind from
# trace.block / data_block. A Residual shares rpm with order_cut and always
# carries its block (ADR §1.141), so it is excluded too and rpm stays
# order_cut. Built once at import time rather than listed by hand, so a new
# curve-shaped kind in core.block_kinds needs no second edit here.
KIND_BY_X_QUANTITY: Dict[str, str] = {
    quantity: kind
    for kind, spec in KINDS.items()
    if kind != KIND_ORDER_RESIDUAL
    and len(spec.axis_quantities) == 1 and "|" not in (quantity := spec.axis_quantities[0])
}


def identity_for_trace(trace: Trace, sources_by_path: Dict[str, SourceEntry],
                       result_set_labels: Optional[Dict[str, str]] = None) -> TraceIdentity:
    """
    Builds a TraceIdentity from one Trace.

    `source` is None both for a trace with no meta_ref (a manually dropped
    live channel never wrote one) and for one whose meta_ref names a file the
    project no longer knows -- trace_matches treats the two the same way.

    `result_set_labels` (id -> display label) resolves the Result set Identity
    facet's value; without it (or for a curve with no result-set origin) that
    value is None and the facet never gates the trace (§1.33).
    """
    channel_identity = split_channel_base_and_direction(trace.channel_name)

    order = _order_from(trace.compute_spec)

    source: Optional[SourceEntry] = None
    meta_ref = trace.meta_ref or {}
    # `source_path`: a result-set curve's measurement, which never says `file_path`.
    file_path = meta_ref.get("file_path") or meta_ref.get("source_path")
    if file_path:
        source = sources_by_path.get(canonical_path(file_path))

    block = trace.data_block if trace.data_block is not None else trace.block
    block_kind = getattr(block, "kind", None) if block is not None else None
    result_kind = block_kind if block_kind is not None else (
        KIND_BY_X_QUANTITY.get(trace.x_quantity) if trace.x_quantity else None
    )
    parameter_sig = trace_parameter_signature(result_kind, trace.compute_spec)

    direction = channel_identity[1] or None
    channel_index = _channel_index_from((trace.meta_ref or {}).get("channel_index"))
    channel_type = resolve_channel_type(source, channel_identity, trace.channel_type, channel_index)
    file_name = source.relpath if source is not None else None
    data_pool_label = (source.setup_label or None) if source is not None else None
    result_set_label = None
    if trace.result_set_id and result_set_labels:
        result_set_label = result_set_labels.get(trace.result_set_id)

    return TraceIdentity(channel_identity=channel_identity, order=order, source=source,
                         result_kind=result_kind, parameter_signature=parameter_sig,
                         direction=direction, channel_type=channel_type, file_name=file_name,
                         data_pool_label=data_pool_label, result_set_label=result_set_label,
                         compute_spec=trace.compute_spec,
                         channel_index=channel_index,
                         computation=_computation_of(block))


def identity_for_stored_curve(curve: Mapping[str, Any], source: Optional[SourceEntry]) -> TraceIdentity:
    """
    The TraceIdentity of a curve read off a result set (one dict of
    io_modules.result_cache's read_result_curves), before any Trace is built
    for it -- what lets it be compared (selection.trace_filter.identities_match)
    against the curves a graph already holds (#116).

    Only the fields that comparison reads are resolved; the Identity facet
    values stay None.
    """
    result_kind = curve.get("kind") or None
    compute_spec = curve.get("compute_spec")
    if result_kind == KIND_OVERALL_LEVEL and compute_spec is not None:
        # The Overall Level builders stamp this onto every Trace they build,
        # so a drawn curve's signature carries it and the stored one must too.
        compute_spec = {**compute_spec, "tracking_mode": curve.get("x_quantity", "")}
    return TraceIdentity(channel_identity=split_channel_base_and_direction(curve.get("channel_name", "")),
                         order=_order_from(compute_spec), source=source, result_kind=result_kind,
                         parameter_signature=trace_parameter_signature(result_kind, compute_spec),
                         compute_spec=compute_spec,
                         channel_index=_channel_index_from(curve.get("channel_index")),
                         computation=dict(curve.get("computation") or {}))


def resolve_stored_curves_already_held(
    curves: Sequence[Mapping[str, Any]], traces: Sequence[Trace],
    sources_by_path: Dict[str, SourceEntry], sources_by_id: Mapping[str, SourceEntry],
) -> Tuple[List[Trace], List[Mapping[str, Any]]]:
    """
    Splits `curves`, read off one result set, by whether the graph holding
    `traces` already shows them: returns (the held traces that are the same
    curve as one of `curves`, the curves still to be drawn).

    Only a trace no result set claims yet -- a live compute, a dropped
    channel, a base curve off a measurement -- can be the same curve, and
    each answers for one stored curve at most (#116).
    """
    unclaimed = [
        (trace, identity_for_trace(trace, sources_by_path))
        for trace in traces if not trace.result_set_id
    ]
    held: List[Trace] = []
    to_draw: List[Mapping[str, Any]] = []
    for curve in curves:
        stored = identity_for_stored_curve(curve, sources_by_id.get(curve.get("source_id", "")))
        match = next((i for i, (_, identity) in enumerate(unclaimed)
                      if identities_match(identity, stored)), None)
        if match is None:
            to_draw.append(curve)
        else:
            held.append(unclaimed.pop(match)[0])
    return held, to_draw


def _computation_of(block: Any) -> Dict[str, Any]:
    """The extra settings a block records in its provenance, empty for none."""
    provenance = getattr(block, "provenance", None)
    params = provenance.params if provenance else {}
    return dict(params.get(PARAM_COMPUTATION) or {})


def _channel_index_from(raw: Any) -> Optional[int]:
    """A channel index a curve states, or None for a missing or unset (negative) one."""
    return raw if isinstance(raw, int) and raw >= 0 else None


def _order_from(compute_spec: Optional[Dict[str, Any]]) -> Optional[float]:
    """The order a curve was cut at, or None for a curve that is not an order cut."""
    raw_order = (compute_spec or {}).get(PARAM_ORDER)
    return float(raw_order) if raw_order is not None else None


def trace_parameter_signature(result_kind: Optional[str], compute_spec: Optional[Dict[str, Any]]
                              ) -> Optional[Signature]:
    """
    What makes two traces' computations "the same settings" for the Parameter
    Set facet -- selection.parameter_sets.parameter_signature, read straight
    off a Trace's own compute_spec instead of a project-wide ResultSetRef (this
    dock may hold h5 curves that were never resolved back to one). PARAM_ORDER
    is stripped first: it is already its own facet (Order), and shape_signature
    only exempts "orders_to_extract" (the plural, project-side key), not the
    singular value a stored order-cut block actually carries.
    """
    if not result_kind or not compute_spec:
        return None
    params = {key: value for key, value in compute_spec.items() if key != PARAM_ORDER}
    return parameter_signature(result_kind, params)
