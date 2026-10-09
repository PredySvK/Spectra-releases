"""
Trace filter mask application planning.

Pure functions (no Qt, no AppContext) deciding whether a dock's filter mask
needs rebuilding and, if it does, what the new one is.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from core.project_model import SourceEntry
from selection.trace_filter import (
    OfferedFacets, TraceIdentity, missing_range_value_fields, trace_matches,
)
from session.trace_filter import FilterSelectionStore
from view_models.plot import Mask, Trace
from view_models.trace_filter import identity_for_trace


@dataclass(frozen=True)
class MaskApplicationPlan:
    """
    A dock's new mask: `predicate` to draw through (None = "Show all", no
    mask), the staleness `key` it was built for, and the warnings to log once.
    """

    key: Tuple[Any, ...]
    predicate: Mask
    messages: Tuple[str, ...] = ()


def plan_mask_application(
    store: FilterSelectionStore,
    active_profile_id: str,
    dock_id: str,
    *,
    showing_all: bool,
    applied_filter_key: Optional[Tuple[Any, ...]],
    traces: Sequence[Trace],
    sources_by_path: Mapping[str, SourceEntry],
    result_set_labels: Mapping[str, str],
    schema: Dict[str, Dict[str, Any]],
    force: bool = False,
) -> Optional[MaskApplicationPlan]:
    """
    The dock's new mask, or None when `applied_filter_key` shows it already
    has this one (R6') and `force` was not asked for.

    The key is computed before the dock's traces are walked, so an unchanged
    dock -- every focus event -- bails out cheaply. The offering is in the
    key, not just in the predicate: repopulating the panel can change which
    values are gated at all (§1.29) while leaving the selection byte-for-byte
    identical.

    The predicate closes over the live `FilterSelection`, not a copy:
    `_draw_all()` calls it fresh every draw, so a later edit to that selection
    (a checkbox click, the §1.29 default-everything heuristic) is picked up
    on the next reapply with no rebuild. It resolves each trace's identity on
    every call rather than memoising it (#336). The missing-range warnings
    are computed here, once per rebuild, so `trace_matches` stays a pure
    hot-loop function (§1.32).
    """
    offered = store.offered_facets(active_profile_id, dock_id) or OfferedFacets()
    key = (showing_all, active_profile_id,
           store.snapshot_for(active_profile_id, dock_id), offered)

    if not force and applied_filter_key == key:
        return None

    if showing_all:
        return MaskApplicationPlan(key=key, predicate=None)

    selection = store.active_selection(active_profile_id, dock_id)

    def identity(trace: Trace) -> TraceIdentity:
        return identity_for_trace(trace, sources_by_path, result_set_labels)

    def predicate(trace: Trace) -> bool:
        return trace_matches(identity(trace), selection, schema, offered)

    missing = missing_range_value_fields(
        [identity(trace) for trace in traces], schema, selection.checked_ranges
    )
    messages = tuple(
        f"WARNING: Filter '{schema.get(field, {}).get('custom_label', field)}' -- some curves on this graph have no value for it and are shown anyway."
        for field in missing
    )
    return MaskApplicationPlan(key=key, predicate=predicate, messages=messages)
