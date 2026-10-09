# =====================================================================
# FILE: selection/trace_filter/_panel_facets.py
# =====================================================================
"""
One resolver, one flat result: what the Filter panel should draw for the
active profile (ARCHITECTURE_DECISIONS §1.38, §1.48, ticket #168).

Resolves workspace state (pool sources, open dock identities, focused dock identities,
card, schema) to a flat ResolvedFacets, and resolves that against the active
FilterSelection into a single PanelRender.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from core.filter_card_config import (
    COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_ORDER, COLUMN_PARAMETER_SET,
    FilterCardConfig,
)
from core.models import ChannelIdentity
from core.project_model import FilterSelection
from selection.parameter_sets import Signature
from selection.source_facets import (
    build_channel_facet, build_identity_facets_from_sources, build_metadata_facets,
    build_range_facets,
)
from ._filter_card import (
    card_identity_facet_keys, card_metadata_keys, card_offers_channel,
)
from ._trace_filter import (
    OfferedFacets, TraceIdentity, facet_value_availability, facets_from_traces,
    global_calculated_facets, identity_facets_from_traces, offering_from_facets,
    resolve_default_checks, selection_from_defaulted, traces_without_parameter_set,
)

@dataclass(frozen=True)
class ResolvedFacets:
    """
    Everything `FilterPanel.populate_facets` needs, flat and named -- no
    positional 11-tuple, no scope branch left for the caller to get wrong.

    `parameter_sets` stays its own field rather than an entry in a generic
    `{column_key: values}` dict: it carries its own "(Empty)" bucket flag
    (`parameter_set_has_empty`) and the panel renders it with per-row
    tooltips, so it is not just a list of checks (§1.56).
    """
    metadata: Dict[str, List[str]]
    channel: List[Any]
    orders: List[float]
    result_kinds: List[str]
    parameter_sets: List[Any]
    ranges: Dict[str, Tuple[Any, Any]]
    identity: Dict[str, List[str]]
    schema: Dict[str, dict]
    card: Optional[FilterCardConfig]
    # Whether an open trace has a parameter signature that resolves to none of
    # `parameter_sets` (ADR §1.56): the Parameter Set family's "(Empty)" bucket
    # flag. The object list cannot carry the sentinel row in band the way
    # `orders` / `result_kinds` can, so it rides here.
    parameter_set_has_empty: bool = False
    # The drawn traces this card gates, for the "grey out a dead checkbox"
    # computation (facet_value_availability, #117): the focused dock's own for
    # Local, every open dock's for Global. A Global card offers more than these
    # carry (whole Data Pool, Result Pool); facet_value_availability never
    # greys a value no identity carries. None only for a hand-built
    # ResolvedFacets (tests) -- no greying then.
    identities: Optional[List[TraceIdentity]] = None

    def _available_columns(self) -> Dict[str, bool]:
        """
        The card's column keys that have at least one value to offer this round.

        One test for every facet family (ADR §1.56): the card carries the key
        and the facet has >= 1 value. The old per-family thresholds (Parameter
        Set at 2, Order at 1) are gone. `card is None` (tests only) -> {}.
        """
        if self.card is None:
            return {}
        # Facets sourced from the traces / pool computation rather than from the
        # identity / metadata / ranges dicts.
        trace_sourced = {
            COLUMN_PARAMETER_SET: self.parameter_sets,
            COLUMN_ANALYSIS_TYPE: self.result_kinds,
            COLUMN_CHANNEL: self.channel,
            COLUMN_ORDER: self.orders,
        }
        available: Dict[str, bool] = {}
        for column in self.card.ordered_columns:
            key = column.key
            if key in trace_sourced:
                has_values = bool(trace_sourced[key])
            elif key in self.identity:
                has_values = bool(self.identity[key])
            elif key in self.metadata:
                has_values = bool(self.metadata[key])
            elif key in self.ranges:
                has_values = bool(self.ranges[key])
            else:
                has_values = False
            if has_values:
                available[key] = True
        return available

    def ordered_columns(self) -> List[str]:
        """
        Which facets to draw and in what order: the card's own columns, in card
        order, filtered to the ones with at least one value this round (ADR
        §1.56). No fixed tail -- the card is the only column source. `card=None`
        (tests only) -> [].

        `populate_facets` takes a `ResolvedFacets` and calls this directly.
        """
        if self.card is None:
            return []
        available = self._available_columns()
        return [column.key for column in self.card.ordered_columns
                if column.key in available]


def resolve_panel_facets(scope: str, card: FilterCardConfig, schema: Dict[str, dict],
                         *, project, pool_sources,
                         focused_identities: List[TraceIdentity],
                         open_dock_identities: List[TraceIdentity]) -> ResolvedFacets:
    """
    The single path from workspace state to a `ResolvedFacets` (§1.38). One
    `if scope`, branch inside -- the caller does not know Local and Global are
    two code paths.

    - `scope`: "global" reads the whole Data Pool for the measurement facets
      and unions the open docks with the Result Pool for the Calculated ones
      (§1.36); anything else is treated as Local and reads only
      `focused_identities`.
    - `card`: already resolved by the caller (a Local card needs the focused
      dock's block kinds, which need the session -- that stays in
      `gui/handlers` glue, §1.38 "Zamietnuté: FilterPanel volá resolver sám").
      Its metadata / Identity columns narrow the offering the same way in
      both branches.
    - `project`, `pool_sources`, `open_dock_identities`: the Global inputs.
      `project` is not in §1.38's field sketch but the Global helpers
      (`global_calculated_facets`, `build_identity_facets_from_sources`)
      genuinely need `result_sets`.
    - `focused_identities` / `open_dock_identities` are each dock's traces
      resolved to `TraceIdentity` once by the caller via `identity_for_trace`
      (with the project's result-set labels, ticket #166) -- this module
      reads only the identity, never the Trace itself.
    """
    allowed_keys = card_metadata_keys(card)
    identity_keys = card_identity_facet_keys(card)

    if scope == "global":
        metadata = build_metadata_facets(pool_sources, schema, allowed_keys)
        ranges = build_range_facets(pool_sources, schema, allowed_keys)
        orders, result_kinds, parameter_sets = global_calculated_facets(
            project, open_dock_identities
        )
        channel: List[Any] = []
        if card_offers_channel(card):
            channel = build_channel_facet(pool_sources)
        identity = build_identity_facets_from_sources(
            pool_sources, project.result_sets, identity_keys
        )
        parameter_set_has_empty = traces_without_parameter_set(
            open_dock_identities, parameter_sets
        )
        identities = open_dock_identities
    else:
        metadata, channel, orders, result_kinds, parameter_sets, ranges = facets_from_traces(
            focused_identities, schema, allowed_keys
        )
        identity = identity_facets_from_traces(focused_identities, identity_keys)
        parameter_set_has_empty = traces_without_parameter_set(
            focused_identities, parameter_sets
        )
        identities = focused_identities

    return ResolvedFacets(
        metadata=metadata, channel=channel, orders=orders, result_kinds=result_kinds,
        parameter_sets=parameter_sets, ranges=ranges, identity=identity,
        schema=schema, card=card, parameter_set_has_empty=parameter_set_has_empty,
        identities=identities,
    )


@dataclass(frozen=True)
class PanelRender:
    """
    Everything `FilterPanel.populate_facets` needs to draw one round, decided --
    the widget computes nothing from it (ADR §1.48). `facets` is carried through
    for the per-box widget builders; `ordered_columns` is already filtered to the
    facets that have something to offer this round (the presence test lives once,
    in `ResolvedFacets.ordered_columns`, not also in `_facet_builders`).

    The five `checked_*` fields are the plain mutable sets/dicts
    `resolve_default_checks` returns: the panel lands them on its live
    `FilterSelection` and its checkbox handlers `.add`/`.discard` them in place
    afterwards. `range_bounds` is
    field key -> the (lo, hi) the range widget should show. `offering` is the
    `OfferedFacets` for this round; `record_offering` is False on a replay
    (`_replay_last_populate` re-renders the last real facets against a newly
    active selection -- recording them would tell the next real populate this
    dock's own values are brand new). `nothing_to_filter` drives the empty-state
    status label.
    """
    facets: ResolvedFacets
    ordered_columns: List[str]
    checked_channel_identities: Set[ChannelIdentity]
    checked_orders: Set[float]
    checked_result_kinds: Set[str]
    checked_parameter_set_signatures: Set[Signature]
    checked_identity_values: Dict[str, Set[str]]
    checked_metadata_values: Dict[str, Set[str]]
    checked_empty_buckets: Set[str]
    range_bounds: Dict[str, Tuple[Any, Any]]
    offering: OfferedFacets
    record_offering: bool
    nothing_to_filter: bool
    # Column key -> its dead values this round (facet_value_availability) --
    # empty when `facets.identities` is None. Purely advisory: the panel greys a control's text with it, the
    # checked state above is unaffected.
    dead_values: Dict[str, Set[Any]]


def resolve_panel_render(facets: ResolvedFacets, selection: FilterSelection,
                         previously_offered: Optional[OfferedFacets], already_seen: bool,
                         is_replay: bool) -> PanelRender:
    """
    One full round of the Filter panel's own decisions (ADR §1.48), pure: the
    §1.29 default-check heuristic (was `populate_plan.plan_populate`, §1.42) plus
    the ordered list of boxes to draw.

    `previously_offered` is what the panel recorded for this (profile, dock) the
    last time it populated it for real, or None; `already_seen` is whether it has
    populated this combo at all. A replay (`is_replay`) of a combo already seen
    for real must not re-tick a box the user just unchecked, so defaulting is off
    unless this is the combo's first sight.
    """
    offering = offering_from_facets(facets)

    allow_default = not is_replay or not already_seen
    defaulted = resolve_default_checks(
        offering, previously_offered, selection, allow_default=allow_default,
    )

    range_bounds = {
        key: selection.checked_ranges.get(key, span)
        for key, span in (facets.ranges or {}).items()
    }

    ordered_columns = facets.ordered_columns()
    nothing_to_filter = not ordered_columns

    dead_values: Dict[str, Set[Any]] = {}
    if facets.identities is not None:
        checked_selection = selection_from_defaulted(defaulted, selection.checked_ranges)
        dead_values = facet_value_availability(facets.identities, checked_selection, facets.schema, offering)

    return PanelRender(
        facets=facets,
        ordered_columns=ordered_columns,
        checked_channel_identities=defaulted.checked_channel_identities,
        checked_orders=defaulted.checked_orders,
        checked_result_kinds=defaulted.checked_result_kinds,
        checked_parameter_set_signatures=defaulted.checked_parameter_set_signatures,
        checked_identity_values=defaulted.checked_identity_values,
        checked_metadata_values=defaulted.checked_metadata_values,
        checked_empty_buckets=defaulted.checked_empty_buckets,
        range_bounds=range_bounds,
        offering=offering,
        record_offering=not is_replay,
        nothing_to_filter=nothing_to_filter,
        dead_values=dead_values,
    )
