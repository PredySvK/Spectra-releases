"""
selection.trace_filter -- TraceIdentity, gating rules, filter card resolution,
and panel facets for the selection floor.

Architecture:
- Selection floor: which subset of curves or measurements is relevant?
- TraceIdentity is a drawn Trace's identity resolved once up front.
- OfferedFacets & trace_matches implement the §1.29 gating rules.
- Filter card configuration, defaults, and cardinalities (_filter_card.py).
- Panel facets resolution (ResolvedFacets) and render plan (PanelRender).
- The selection read as a Data Pool query (PoolQuery, _pool_query.py).

Does NOT import Qt, gui, orchestration, view_models, session, or io_modules.
"""

from ._trace_filter import (
    EMPTY_FACET_VALUE,
    GATING_FACETS,
    IDENTITY_FACET_ATTR,
    DefaultedChecks,
    Facet,
    OfferedFacets,
    Signature,
    TraceIdentity,
    facet_value_availability,
    facets_from_traces,
    format_result_kind,
    global_calculated_facets,
    global_parameter_sets,
    identities_match,
    identity_facets_from_traces,
    missing_range_value_fields,
    offering_from_facets,
    resolve_default_checks,
    selection_from_defaulted,
    trace_matches,
    traces_without_parameter_set,
)
from ._filter_card import (
    build_column_for_key,
    builtin_column_cardinalities,
    builtin_column_cardinalities_for_global,
    builtin_column_cardinalities_from_traces,
    card_identity_facet_keys,
    card_metadata_keys,
    card_offers_channel,
    default_card_for_schema,
    local_card_cardinalities,
    resolve_card,
    schema_field_group,
    user_default_column_keys,
)
from ._panel_facets import (
    PanelRender,
    ResolvedFacets,
    resolve_panel_facets,
    resolve_panel_render,
)
from ._pool_query import (
    PoolQuery,
    resolve_pool_query,
)

__all__ = [
    # TraceIdentity & gating
    "EMPTY_FACET_VALUE",
    "GATING_FACETS",
    "IDENTITY_FACET_ATTR",
    "DefaultedChecks",
    "Facet",
    "OfferedFacets",
    "Signature",
    "TraceIdentity",
    "facet_value_availability",
    "facets_from_traces",
    "format_result_kind",
    "global_calculated_facets",
    "global_parameter_sets",
    "identities_match",
    "identity_facets_from_traces",
    "missing_range_value_fields",
    "offering_from_facets",
    "resolve_default_checks",
    "selection_from_defaulted",
    "trace_matches",
    "traces_without_parameter_set",
    # Filter card
    "build_column_for_key",
    "builtin_column_cardinalities",
    "builtin_column_cardinalities_for_global",
    "builtin_column_cardinalities_from_traces",
    "card_identity_facet_keys",
    "card_metadata_keys",
    "card_offers_channel",
    "default_card_for_schema",
    "local_card_cardinalities",
    "resolve_card",
    "schema_field_group",
    "user_default_column_keys",
    # Panel facets & render
    "PanelRender",
    "ResolvedFacets",
    "resolve_panel_facets",
    "resolve_panel_render",
    # Data Pool query
    "PoolQuery",
    "resolve_pool_query",
]
