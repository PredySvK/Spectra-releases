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

from core.block_kinds import KIND_ORDER_RESIDUAL, KINDS, PARAM_ORDER, STEP_READ
from core.curve_recipe import resolve_curve_recipe
from core.project_model import SourceEntry
from view_models.plot import Trace, build_compute_spec
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
# carries its block, so it is excluded too and rpm stays
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
    parameter_sig = None if _is_imported(block) else trace_parameter_signature(result_kind, trace.compute_spec)

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
                         curve_recipe=resolve_curve_recipe(block))


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
    # The recipe a live curve's spec is built with, applied to the stored block
    # (#665 C19): the reader hands over the block, not a spec of its own.
    block = curve.get("block")
    compute_spec = build_compute_spec(block) if block is not None else curve.get("compute_spec")
    return TraceIdentity(channel_identity=split_channel_base_and_direction(curve.get("channel_name", "")),
                         order=_order_from(compute_spec), source=source, result_kind=result_kind,
                         parameter_signature=None if _is_imported(block)
                         else trace_parameter_signature(result_kind, compute_spec),
                         compute_spec=compute_spec,
                         channel_index=_channel_index_from(curve.get("channel_index")),
                         curve_recipe=resolve_curve_recipe(block))


def resolve_stored_curves_already_held(
    curves: Sequence[Mapping[str, Any]], traces: Sequence[Trace],
    sources_by_path: Dict[str, SourceEntry], sources_by_id: Mapping[str, SourceEntry],
) -> Tuple[List[Tuple[Trace, Mapping[str, Any]]], List[Mapping[str, Any]]]:
    """
    Splits `curves`, read off one result set, by whether the graph holding
    `traces` already shows them: returns ((held trace, the stored curve it is the
    same curve as) pairs, the curves still to be drawn).

    Only a trace no result set claims yet -- a live compute, a dropped
    channel, a base curve off a measurement -- can be the same curve, and
    each answers for one stored curve at most (#116).
    """
    unclaimed = [
        (trace, identity_for_trace(trace, sources_by_path))
        for trace in traces if not trace.result_set_id
    ]
    held: List[Tuple[Trace, Mapping[str, Any]]] = []
    to_draw: List[Mapping[str, Any]] = []
    for curve in curves:
        stored = identity_for_stored_curve(curve, sources_by_id.get(curve.get("source_id", "")))
        match = next((i for i, (_, identity) in enumerate(unclaimed)
                      if identities_match(identity, stored)), None)
        if match is None:
            to_draw.append(curve)
        else:
            held.append((unclaimed.pop(match)[0], curve))
    return held, to_draw


def resolve_set_curve_same_as(
    live: Trace, traces: Sequence[Trace], sources_by_path: Dict[str, SourceEntry],
) -> Optional[Trace]:
    """
    The curve among `traces` that only a result set holds and that is the same
    curve as `live`, a curve just computed live -- the reverse of
    `resolve_stored_curves_already_held`, for a live curve landing after the set
    it belongs to. None when no such curve is held (#923).
    """
    set_curves = [trace for trace in traces if trace.is_set_only and trace is not live]
    if not set_curves:
        return None
    wanted = identity_for_trace(live, sources_by_path)
    return next((trace for trace in set_curves
                 if identities_match(identity_for_trace(trace, sources_by_path), wanted)), None)


def _is_imported(block: Any) -> bool:
    """Whether `block`, a result block, is an Imported result: computed by
    another tool, so it has no curve recipe and belongs to no Parameter Set
    (#813)."""
    provenance = getattr(block, "provenance", None)
    return provenance is not None and provenance.step == STEP_READ


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

    An empty compute_spec (a curve computed before the curve recipe) still
    gets the signature of its kind alone, so it keeps a Parameter Set until it
    is computed again; only a curve with no spec at all has none.
    """
    if not result_kind or compute_spec is None:
        return None
    params = {key: value for key, value in compute_spec.items() if key != PARAM_ORDER}
    return parameter_signature(result_kind, params)
