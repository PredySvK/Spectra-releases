"""
Source facets for the selection floor.

Selection floor: which subset of curves or measurements is relevant?
Source facets builds and applies faceted filter choices (categorical and
ranged metadata, channel identities, order cuts) from project sources and
measurements for the Filter panel and batch workflows.
It also resolves the stored source channel behind a channel identity and the
Channel type that channel is judged by.

What does not belong here: how a curve is drawn or Qt widgets (gui/),
file format parsing or disk reading (io_modules/), or workspace plot
models (view_models/).
"""

from ._source_facets import (
    EMPTY_FACET_VALUE,
    POOL_IDENTITY_COLUMNS,
    apply_column_facets,
    FieldCardinality,
    RANGED_FIELD_KINDS,
    all_pool_sources,
    apply_channel_facet,
    apply_metadata_facets,
    apply_range_facets,
    build_channel_facet,
    build_identity_facets_from_sources,
    build_metadata_facets,
    build_order_facet,
    build_range_facets,
    categorical_schema_fields,
    channel_identity_sort_key,
    channel_summary_value,
    field_cardinality,
    field_kind,
    filter_field_cardinalities,
    filter_field_unusable_reason,
    filter_field_unusable_reasons,
    filterable_schema_fields,
    order_matches,
    pool_source_entries,
    ranged_schema_fields,
    resolve_channel_type,
    resolve_source_channel,
    curve_field_value,
    curve_range_value,
    source_field_value,
    sources_for_result_sets,
    value_in_range,
    visible_pool_channels,
    with_empty_row,
)

__all__ = [
    "EMPTY_FACET_VALUE",
    "POOL_IDENTITY_COLUMNS",
    "apply_column_facets",
    "FieldCardinality",
    "RANGED_FIELD_KINDS",
    "all_pool_sources",
    "apply_channel_facet",
    "apply_metadata_facets",
    "apply_range_facets",
    "build_channel_facet",
    "build_identity_facets_from_sources",
    "build_metadata_facets",
    "build_order_facet",
    "build_range_facets",
    "categorical_schema_fields",
    "channel_identity_sort_key",
    "channel_summary_value",
    "field_cardinality",
    "field_kind",
    "filter_field_cardinalities",
    "filter_field_unusable_reason",
    "filter_field_unusable_reasons",
    "filterable_schema_fields",
    "order_matches",
    "pool_source_entries",
    "ranged_schema_fields",
    "resolve_channel_type",
    "resolve_source_channel",
    "curve_field_value",
    "curve_range_value",
    "source_field_value",
    "sources_for_result_sets",
    "value_in_range",
    "visible_pool_channels",
    "with_empty_row",
]
