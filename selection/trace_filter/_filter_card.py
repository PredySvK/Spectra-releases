# =====================================================================
# FILE: selection/trace_filter/_filter_card.py
# =====================================================================
"""
Turning a Filter card's stored column list into a live facet offering, and a
Configure Filters dialog result back into a card (ARCHITECTURE_DECISIONS
§1.32, ticket #41, #168).

`core/filter_card_config.py` owns the shape (frozen data, JSON round-trip).
This owns the half that has to read the metadata schema: what a default card
looks like for a given schema, which metadata keys a stored card lets through,
and how the flat Configure Filters checkbox result rebuilds a card.
"""
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from core.filter_card_config import (
    BUILTIN_COLUMN_GROUPS, BUILTIN_COLUMN_KEYS, COLUMN_ANALYSIS_TYPE,
    COLUMN_CHANNEL, COLUMN_CHANNEL_TYPE, COLUMN_DATA_POOL_LABEL, COLUMN_DIRECTION,
    COLUMN_FILE_NAME, COLUMN_ORDER, COLUMN_PARAMETER_SET, COLUMN_RESULT_SET,
    FilterCardConfig, FilterColumnConfig, GROUP_EXCEL, GROUP_RAW,
    LIVE_IDENTITY_FACET_COLUMNS, default_widget_for_kind, renumbered,
)
from core.project_model import NVHProject
from selection.source_facets import (
    FieldCardinality, all_pool_sources, build_channel_facet,
    build_order_facet, field_cardinality, filter_field_cardinalities,
)
from selection.parameter_sets import build_parameter_sets, parameter_sets_from_traces
from ._trace_filter import TraceIdentity, global_calculated_facets

_CHANNEL_LAYER = "channel"


def schema_field_group(config: Dict[str, Any]) -> str:
    """
    Public (ticket #42): FilterFieldSelectionDialog sections its Raw metadata
    / Excel metadata columns off the same rule this module already used
    internally to pick a schema field's group.
    """
    return GROUP_RAW if config.get("layer") == _CHANNEL_LAYER else GROUP_EXCEL


def default_card_for_schema(card_id: str, schema: Dict[str, Dict[str, Any]],
                            project: Optional[NVHProject] = None) -> FilterCardConfig:
    """
    The card an unedited profile resolves to -- Local and Global alike, no
    longer derived from any dock's block kinds (ADR §1.56): just `Channel`,
    plus every column the user pinned with the "Default" checkbox on any stored
    card, in pin order.

    Nothing else pours in: a facet reaches an unedited card solely through the
    Configure Filters checkbox or the Default pin. Channel is always present --
    "predefined card = only Channel" is unusable if even that is opt-in.
    """
    columns = _with_user_default_pins(_columns_for_keys([COLUMN_CHANNEL], schema), schema, project)
    return FilterCardConfig(id=card_id, columns=renumbered(columns))


def _with_user_default_pins(columns: Iterable[FilterColumnConfig],
                            schema: Dict[str, Dict[str, Any]],
                            project: Optional[NVHProject]) -> List[FilterColumnConfig]:
    """
    `columns` followed by a `default=True` column for every key the user pinned
    with the Default checkbox that is not already present (§1.37 -- the one way
    a Raw/Excel field or a built-in reaches an unedited card, ticket #92 / ADR
    §1.56).

    `key not in present` is the whole dedup: Channel already leads the card, so
    pinning it as a Default never doubles the column.
    """
    columns = list(columns)
    if project is None:
        return columns
    present = {column.key for column in columns}
    return columns + [
        replace(build_column_for_key(key, schema), default=True)
        for key in user_default_column_keys(project)
        if key not in present and (key in schema or key in BUILTIN_COLUMN_KEYS)
    ]


def user_default_column_keys(project: NVHProject) -> Tuple[str, ...]:
    """
    Every column key the user has pinned with the "Default" checkbox on any
    stored Filter card -- the one list, shared across kinds, that every fresh
    graph's card also picks up (§1.32 / ticket #44, ADR §1.56).

    Built-in Identity/Calculated keys count too (ticket #92): pinning Order or
    Direction has to reach every graph the same way a schema field does, so
    "predefined card = only Channel" (ADR §1.56) stays usable.
    """
    keys: List[str] = []
    for card in project.filter_cards:
        for column in card.columns:
            if column.default and column.key not in keys:
                keys.append(column.key)
    return tuple(keys)


def resolve_card(session, profile_id: str, schema: Dict[str, Dict[str, Any]]) -> FilterCardConfig:
    """
    The active card for `profile_id` -- the one stored on the project, or a
    fresh default. A default is not persisted here: it costs nothing to
    recompute and an untouched project stays clean until the user actually
    edits a card through Configure Filters.

    One path for Local and Global (ADR §1.56): a never-configured profile of
    either scope resolves to `default_card_for_schema` -- `Channel` plus the
    user's Default pins. Local is no longer derived from the focused dock's
    block kinds.
    """
    stored = session.project.filter_card_by_id(profile_id)
    if stored is not None:
        return stored
    return default_card_for_schema(profile_id, schema, session.project)


def card_metadata_keys(card: FilterCardConfig) -> Set[str]:
    """
    The schema-field column keys on `card` -- what `build_metadata_facets` /
    `build_range_facets` narrow their offering to. The Identity / Calculated
    built-ins are not schema fields, so they are left out.
    """
    return {column.key for column in card.columns if column.key not in BUILTIN_COLUMN_KEYS}


def card_offers_channel(card: FilterCardConfig) -> bool:
    return card.has_column(COLUMN_CHANNEL)


def card_identity_facet_keys(card: FilterCardConfig) -> Set[str]:
    """
    The card's built-in Identity columns that render as their own panel facet
    (Direction, Channel type, File name, Data Pool label, Result set -- ADR
    §1.33). Channel is not one of them: it has its own dedicated path.
    """
    return {column.key for column in card.columns if column.key in LIVE_IDENTITY_FACET_COLUMNS}


def _columns_for_keys(keys, schema: Dict[str, Dict[str, Any]]):
    return tuple(
        replace(build_column_for_key(key, schema), order=position)
        for position, key in enumerate(keys, start=1)
    )


def build_column_for_key(key: str, schema: Dict[str, Dict[str, Any]]) -> FilterColumnConfig:
    """
    A fresh `FilterColumnConfig` for `key`: its group fixed by the key (a
    built-in) or the schema field's layer, its widget derived from the schema
    field's `kind` (ticket #49 -- a numeric/date field opens as a range).
    Public so Configure Filters can build the column for a newly checked row
    without re-deriving the group/widget rule.
    """
    group = BUILTIN_COLUMN_GROUPS.get(key) or schema_field_group(schema.get(key, {}))
    kind = None if key in BUILTIN_COLUMN_KEYS else schema.get(key, {}).get("kind")
    return FilterColumnConfig(key=key, group=group, widget=default_widget_for_kind(kind))


def builtin_column_cardinalities(project: NVHProject) -> Dict[str, FieldCardinality]:
    """
    `field_cardinality` for every Identity / Calculated built-in, over the
    whole project (ticket #42) -- Configure Filters shows the same "(N)"
    count next to these as it does next to a schema field, so the built-ins
    that have no schema row need the same read.

    None of these have a 1:1 correspondence to a measurement the way a schema
    field does (a channel is not a source, a result set is not a source), so
    every one of them skips the "unique per measurement" rule
    (`per_measurement=False`) -- only "one value pool-wide" applies.
    """
    sources = all_pool_sources(project)
    result_sets = project.result_sets
    identities = build_channel_facet(sources)
    return {
        COLUMN_CHANNEL: field_cardinality(identities, per_measurement=False),
        COLUMN_DIRECTION: field_cardinality(
            (direction for _, direction in identities), per_measurement=False),
        COLUMN_CHANNEL_TYPE: field_cardinality(
            (meta.get("type") for source in sources for meta in source.channels.values()),
            per_measurement=False,
        ),
        COLUMN_FILE_NAME: field_cardinality((source.relpath for source in sources)),
        COLUMN_DATA_POOL_LABEL: field_cardinality((source.setup_label for source in sources)),
        COLUMN_RESULT_SET: field_cardinality(
            (result_set.id for result_set in result_sets), per_measurement=False),
        COLUMN_ANALYSIS_TYPE: field_cardinality(
            (result_set.kind for result_set in result_sets), per_measurement=False),
        COLUMN_ORDER: field_cardinality(build_order_facet(result_sets), per_measurement=False),
        COLUMN_PARAMETER_SET: field_cardinality(
            [parameter_set.label for parameter_set in
             build_parameter_sets(project, (result_set.id for result_set in result_sets))],
            per_measurement=False,
        ),
    }


def builtin_column_cardinalities_for_global(project: NVHProject,
                                            open_dock_identities: List[TraceIdentity]
                                            ) -> Dict[str, FieldCardinality]:
    """
    `builtin_column_cardinalities` for a Global card (ADR §1.36). Identity
    columns stay pool-wide; the three Calculated columns are counted straight
    off `global_calculated_facets`' output, the single path that decides that
    universe, so the "(N)" cannot drift from the facet it gates.

    `open_dock_identities` is every open dock's own `TraceIdentity`, resolved
    once by the caller via `identity_for_trace` (ticket #166).
    """
    cardinalities = builtin_column_cardinalities(project)
    orders, kinds, parameter_sets = global_calculated_facets(project, open_dock_identities)

    def calculated(values) -> FieldCardinality:
        return field_cardinality(values, per_measurement=False)

    cardinalities[COLUMN_ANALYSIS_TYPE] = calculated(kinds)
    cardinalities[COLUMN_ORDER] = calculated(orders)
    cardinalities[COLUMN_PARAMETER_SET] = calculated(ps.label for ps in parameter_sets)
    return cardinalities


def builtin_column_cardinalities_from_traces(identities: List[TraceIdentity],
                                             *, pool_label: str = "this graph"
                                             ) -> Dict[str, FieldCardinality]:
    """
    `builtin_column_cardinalities`' Local-card counterpart (ADR §1.33): the same
    "(N)" counts and "cannot narrow" verdicts, but read off the focused dock's
    own traces instead of the whole Data Pool -- a Local card offers only what
    is on that graph, so counting the pool overstated every column.

    `identities` is the focused dock's own `TraceIdentity` list, resolved once
    by the caller via `identity_for_trace` with the project's result-set labels
    (ticket #166) -- Analysis type / Order read straight off it
    (`result_kind` / `order`), the same source `facets_from_traces` builds the
    actual checkboxes from -- not `trace.result_set_id`, which only a curve
    loaded back out of a saved Result Set carries. A live-computed curve (an
    order-tracking or Compare overlay never saved as a Result Set) has no
    `result_set_id`, so counting through it used to show "(0)" here while the
    real facet still offered every value.
    """
    parameter_sets = parameter_sets_from_traces(identities)

    def card(values, per_measurement: bool = False) -> FieldCardinality:
        return field_cardinality(values, per_measurement=per_measurement, pool_label=pool_label)

    return {
        COLUMN_CHANNEL: card(i.channel_identity for i in identities),
        COLUMN_DIRECTION: card(i.direction for i in identities),
        COLUMN_CHANNEL_TYPE: card(i.channel_type for i in identities),
        COLUMN_FILE_NAME: card(i.file_name for i in identities),
        COLUMN_DATA_POOL_LABEL: card(i.data_pool_label for i in identities),
        COLUMN_RESULT_SET: card(i.result_set_label for i in identities),
        COLUMN_ANALYSIS_TYPE: card(i.result_kind for i in identities),
        COLUMN_ORDER: card(i.order for i in identities),
        COLUMN_PARAMETER_SET: card(ps.label for ps in parameter_sets),
    }



def local_card_cardinalities(identities: Iterable[TraceIdentity],
                             schema: Dict[str, Dict[str, Any]],
                             *, pool_label: str = "this graph"
                             ) -> Tuple[Dict[str, FieldCardinality], Dict[str, FieldCardinality]]:
    """
    The schema-field and built-in column cardinalities Configure Filters shows
    for a Local card -- read off the focused dock's own traces and their
    resolved sources, not the pool (ADR §1.33). Returns (schema_cardinalities,
    builtin_cardinalities), both keyed the same way the pool-wide versions are.
    """
    identities_list = list(identities)
    dock_sources = []
    seen = set()
    for identity in identities_list:
        source = identity.source
        if source is not None and source.id not in seen:
            seen.add(source.id)
            dock_sources.append(source)

    schema_cardinalities = filter_field_cardinalities(dock_sources, schema)
    builtin_cardinalities = builtin_column_cardinalities_from_traces(identities_list, pool_label=pool_label)
    return schema_cardinalities, builtin_cardinalities
