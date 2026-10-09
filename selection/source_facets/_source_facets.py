# =====================================================================
# FILE: selection/source_facets/_source_facets.py
# =====================================================================
"""
Builds the Filter tab's faceted filter choices from a set of project sources.

Pure data logic, no Qt -- scoped to whichever h5 result sets the Compare tab
has selected (a filter facet only shows values that could actually narrow
down something in the current comparison), reading from SourceEntry rather
than the measurement files themselves so this works without any data root
being mounted (see core.project_model.SourceEntry.excel_metadata /
file_metadata / channels).
"""
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from core.filter_card_config import IDENTITY_BUILTIN_ORDER, COLUMN_RESULT_SET
from core.block_kinds import KIND_ORDER_CUT
from core.models import ChannelIdentity
from core.project_model import NVHProject, ResultSetRef, SourceEntry
from selection.channel_identity import split_channel_base_and_direction
from selection.parameter_sets import orders_equal

# The "(Empty)" bucket row (ADR §1.56): a gating facet offers this value when at
# least one trace / source carries no value for it, and a value-less trace is
# gated through it like any other value. Defined here rather than in
# gui/filter_panel/trace_filter.py because the value builders that append it
# span both layers (build_metadata_facets / build_identity_facets_from_sources
# here, facets_from_traces there); trace_filter re-exports it so panel code and
# tests still import it from one place.
EMPTY_FACET_VALUE = "(Empty)"
POOL_IDENTITY_COLUMNS = frozenset(IDENTITY_BUILTIN_ORDER) - {COLUMN_RESULT_SET}


def with_empty_row(sorted_values: List[Any], has_missing: bool) -> List[Any]:
    """
    `sorted_values` (a facet's real values, already ordered) plus one
    EMPTY_FACET_VALUE row at the end when `has_missing` -- some trace / source
    carries no value for the facet (ADR §1.56). The row is left off when the
    facet has no real values at all: an "(Empty)"-only facet is not a facet.
    """
    values = list(sorted_values)
    if values and has_missing:
        values.append(EMPTY_FACET_VALUE)
    return values


def filterable_schema_fields(schema: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Opted-in fields from the metadata schema (Metadata Editor's "Use as Filter").

    Independent of "Active Status" (BUGS.md M1) -- the two checkboxes are
    unrelated properties in the dialog (visibility vs. filterability) and
    coupling them meant "Use as Filter" silently did nothing unless the field
    was also marked active.
    """
    return {
        key: config for key, config in schema.items()
        if config.get("usable_as_filter", False)
    }


# Kinds filtered by a low..high bound; every other kind is picked from a list.
RANGED_FIELD_KINDS = ("int", "float", "date")


def field_kind(config: Dict[str, Any]) -> str:
    return config.get("kind", "str")


@dataclass(frozen=True)
class FieldCardinality:
    """
    How many distinct values a column carries across the current pool, and
    why that makes it unusable as a facet right now, or None when it is fine
    (ARCHITECTURE_DECISIONS §1.32 "Merané 2026-09-06", ticket #42). Configure
    Filters shows `distinct_count` next to every column's label ("Setup (1)"),
    not only the greyed ones -- "how many metadata values are in the pool" is
    useful information on a column the user is about to check, too.
    """
    distinct_count: int
    reason: Optional[str]


def field_cardinality(values: Iterable[Any], *, per_measurement: bool = True,
                      pool_label: str = "the pool") -> FieldCardinality:
    """
    `values` collapsed to a `FieldCardinality`. A column is dead weight in
    exactly two shapes: one value pool-wide (`Date`, `Max speed`), or -- when
    `per_measurement` (`values` is genuinely one entry per measurement, e.g. a
    schema field or File name) -- a value unique to every single entry
    (`Test no.`, `File Name`); either way, checking it can never hide one
    measurement without hiding all or none of the rest.

    `per_measurement=False` is for a facet with no 1:1 correspondence to a
    measurement (Channel, Result set, Order, ...): a channel that happens to
    be unique across the pool is not "unique per measurement" in the sense
    that matters here, so only the pool-wide-single-value rule applies.

    `pool_label` names the value universe in the "cannot narrow" reason -- "the
    pool" for a Global card, "this graph" for a Local one, whose count is read
    off the focused dock's own traces instead (ARCHITECTURE_DECISIONS §1.33).

    Cardinality, not the column's name, is the only signal: `Comment 1` looks
    like the same kind of column as `Test no.` but has 6 values on 36 rows and
    is a good facet (blank entries are dropped before counting, not treated
    as a value of their own, or every row missing it would look unique). This
    is why the app never *hides* a low-cardinality column (Configure Filters
    greys it out with the reason instead, still checkable) and never bakes
    the verdict into a default set -- it is a live read of the current pool,
    so a column flips back the moment a measurement with a different value
    joins.
    """
    cleaned = [value for value in values if value not in (None, "")]
    distinct = set(cleaned)
    count = len(distinct)
    if count <= 1:
        return FieldCardinality(count, f"{count} value{'' if count == 1 else 's'} in {pool_label}")
    if per_measurement and len(cleaned) == count:
        return FieldCardinality(count, "unique per measurement")
    return FieldCardinality(count, None)


def schema_field_cardinality(sources: Iterable[SourceEntry], key: str,
                             config: Dict[str, Any]) -> FieldCardinality:
    """`field_cardinality` for a metadata schema field -- one value per source."""
    values = (_field_value(source, key, config.get("layer", "excel")) for source in sources)
    return field_cardinality((str(value) if value is not None else value for value in values))


def filter_field_unusable_reason(sources: Iterable[SourceEntry], key: str,
                                 config: Dict[str, Any]) -> Optional[str]:
    """Why `key` cannot narrow anything down across `sources` right now, or None when it can."""
    return schema_field_cardinality(sources, key, config).reason


def filter_field_cardinalities(sources: Iterable[SourceEntry],
                               schema: Dict[str, Dict[str, Any]]) -> Dict[str, FieldCardinality]:
    """`schema_field_cardinality` for every `usable_as_filter` schema field, keyed by field."""
    sources = list(sources)
    return {
        key: schema_field_cardinality(sources, key, config)
        for key, config in filterable_schema_fields(schema).items()
    }


def filter_field_unusable_reasons(sources: Iterable[SourceEntry],
                                  schema: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """`filter_field_unusable_reason` for every `usable_as_filter` schema field, keyed by field."""
    return {
        key: cardinality.reason
        for key, cardinality in filter_field_cardinalities(sources, schema).items()
        if cardinality.reason is not None
    }


def _narrowed_to(fields: Dict[str, Dict[str, Any]],
                 allowed_keys: Optional[Iterable[str]]) -> Dict[str, Dict[str, Any]]:
    """`fields` restricted to `allowed_keys`, or unchanged when it is None --
    the Filter card's column list narrowing the offering on top of the
    usable_as_filter gate (ARCHITECTURE_DECISIONS §1.32)."""
    if allowed_keys is None:
        return fields
    allowed = set(allowed_keys)
    return {key: config for key, config in fields.items() if key in allowed}


def categorical_schema_fields(schema: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Opted-in fields whose values are picked from a list (str / enum kinds)."""
    return {
        key: config for key, config in filterable_schema_fields(schema).items()
        if field_kind(config) not in RANGED_FIELD_KINDS
    }


def ranged_schema_fields(schema: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Opted-in fields filtered by a low..high bound (int / float / date kinds)."""
    return {
        key: config for key, config in filterable_schema_fields(schema).items()
        if field_kind(config) in RANGED_FIELD_KINDS
    }


def _as_number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value if isinstance(value, (int, float)) else str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return None if number != number else number  # NaN is no value to compare


def channel_summary_value(source: SourceEntry, key: str) -> Optional[Any]:
    """
    One representative value for a channel-level field (BUGS.md N1/N2) across
    a source's channels -- the first channel that actually carries it.

    A real acquisition normally shares one sampling_rate/func_type across every
    channel, so picking one keeps the existing one-value-per-source facet model
    intact rather than fanning a single field out into per-channel facets. This
    does mean a source whose channels genuinely disagree (mixed sample rates in
    one file) is represented by whichever channel happens to be first -- an
    accepted simplification, not a claim that the field cannot vary.
    """
    for channel_meta in source.channels.values():
        value = channel_meta.get(key)
        if value not in (None, ""):
            return value
    return None


def _raw_field_value(source: SourceEntry, key: str, layer: str) -> Optional[Any]:
    if layer == "channel":
        return channel_summary_value(source, key)
    if layer == "excel":
        return source.excel_metadata.get(key)
    return source.file_metadata.get(key)


def _text_or_none(value: Any) -> Optional[str]:
    """`value` as the string a facet lists it under, or None when it is blank."""
    return str(value) if value not in (None, "") else None


def _field_value(source: SourceEntry, key: str, layer: str) -> Optional[Any]:
    """
    The field's typed value (parsed once at ingest, ADR §1.1) when metadata has
    been parsed for it, otherwise the raw cell -- so a project written before
    parsed_metadata existed still filters, just on strings.
    """
    parsed = getattr(source, "parsed_metadata", None) or {}
    if key in parsed:
        return parsed[key]
    return _raw_field_value(source, key, layer)


def sources_for_result_sets(project: NVHProject, result_set_ids: Iterable[str]) -> List[SourceEntry]:
    """
    The distinct SourceEntry objects behind a set of selected result sets, in
    `source_ids` order (result sets walked in project order, first occurrence
    wins). The order is deterministic on purpose: it becomes the curve order
    and colour assignment of Load Result Sets (#352).
    """
    wanted_ids = set(result_set_ids)
    source_ids: Dict[str, None] = {}
    for result_set in project.result_sets:
        if result_set.id in wanted_ids:
            source_ids.update(dict.fromkeys(result_set.source_ids))

    sources = []
    for source_id in source_ids:
        entry = project.source_by_id(source_id)
        if entry is not None:
            sources.append(entry)
    return sources


def all_pool_sources(project: NVHProject) -> List[SourceEntry]:
    """
    Every source registered anywhere in the project's Data Pool (with active pool
    membership, entry.in_pool=True), independent of whether its data root is
    currently reachable/scanned this session.

    Unlike pool_source_entries(runs, entries_by_path), which only returns a
    source when its file is in the live, currently-scanned `runs` list (i.e.
    DataPool.loaded_runs), this is what an Input Data (MODE_QUERY) selection
    has to be built and re-resolved against: "the whole Data Pool" is a
    project-level concept (NVHProject.sources / data_roots), not a function of
    what happens to be mounted and scanned in this particular session.
    """
    return [entry for entry in project.sources if entry.in_pool]


def build_metadata_facets(sources: Iterable[SourceEntry],
                          schema: Dict[str, Dict[str, Any]],
                          allowed_keys: Optional[Iterable[str]] = None) -> Dict[str, List[str]]:
    """
    One entry per opted-in categorical (str/enum) schema field -> sorted
    distinct values found across `sources`. A source missing the field
    contributes nothing for it, and a field with no values found across any
    source is left out entirely -- an empty facet is not a choice worth
    offering. Numeric and date fields are filtered by range instead; see
    build_range_facets.

    `allowed_keys`, when given, narrows the offering to those keys on top of
    the `usable_as_filter` gate -- the Filter card's own column list
    (ARCHITECTURE_DECISIONS §1.32): `usable_as_filter` decides what *may*
    appear, the card decides what is *on it*. None keeps the pre-§1.32
    behaviour (every opted-in field), which the batch resolver still relies on.
    """
    fields = _narrowed_to(categorical_schema_fields(schema), allowed_keys)
    facets: Dict[str, set] = {key: set() for key in fields}
    missing: Dict[str, bool] = {key: False for key in fields}

    for source in sources:
        for key, config in fields.items():
            if config.get("layer") == "channel":
                # Every channel's own value is on offer: a curve is judged by
                # its channel (curve_field_value), not the file's first one.
                values = {_text_or_none(facts.get(key)) for facts in source.channels.values()}
                values.discard(None)
            else:
                value = _text_or_none(_field_value(source, key, config.get("layer", "excel")))
                values = {value} if value is not None else set()
            if values:
                facets[key] |= values
            else:
                missing[key] = True

    return {
        key: with_empty_row(sorted(values), missing[key])
        for key, values in facets.items() if values
    }


def source_field_value(source: SourceEntry, schema: Dict[str, Dict[str, Any]],
                       key: str) -> Optional[str]:
    """
    `source`'s string value for one categorical filter field, or None when the
    field is not a categorical filter field or the source has no value for it --
    what selection.trace_filter's metadata gating family reads per trace
    (ADR §1.56), the counterpart of TraceIdentity's pre-resolved Identity values.
    """
    config = categorical_schema_fields(schema).get(key)
    if config is None:
        return None
    return _text_or_none(_field_value(source, key, config.get("layer", "excel")))


def curve_field_value(source: SourceEntry, schema: Dict[str, Dict[str, Any]], key: str,
                      identity: ChannelIdentity, channel_index: Optional[int] = None) -> Optional[str]:
    """
    `source_field_value` for one curve: a channel-layer field (unit, hardware
    label...) is read off the curve's own source channel, so a file holding an
    accelerometer and a microphone judges each curve by its own value. A channel
    the source does not list (or one without the field) falls back to the
    source-level value; every other field is source-level anyway.
    """
    config = categorical_schema_fields(schema).get(key)
    if config is not None and config.get("layer") == "channel":
        facts = resolve_source_channel(source, identity, channel_index)
        if facts is not None and _text_or_none(facts.get(key)) is not None:
            return _text_or_none(facts.get(key))
    return source_field_value(source, schema, key)


def channel_identity_sort_key(identity: ChannelIdentity) -> Tuple[str, bool, str]:
    """
    Orders channel identities without comparing a direction against None.

    Plain tuple ordering works right up until two identities share a base name
    and only one carries a direction ("Acc" beside "Acc_X"), where it reaches
    None < "X" and raises TypeError instead of sorting. Every place that sorts
    identities has to use this -- the facet, the panel's selection, and the
    snapshot that goes into the project.
    """
    return (identity[0], identity[1] is None, identity[1] or "")


def build_identity_facets_from_sources(sources: Iterable[SourceEntry],
                                      result_sets: Iterable[ResultSetRef],
                                      keys: Iterable[str]) -> Dict[str, List[str]]:
    """
    The built-in Identity facets (Direction, Channel type, File name, Data Pool
    label, Result set) a Global Filter card offers -- every distinct value each
    carries across the whole Data Pool, sorted, empty facets left out (same
    rule as build_metadata_facets). `keys` is the card's own Identity column
    list (core.filter_card_config COLUMN_*); a key not in it is not built.

    The Local counterpart reads the same values off a dock's own traces
    instead -- selection.trace_filter.identity_facets_from_traces
    (ARCHITECTURE_DECISIONS §1.33).
    """
    from core.filter_card_config import (
        COLUMN_CHANNEL_TYPE, COLUMN_DATA_POOL_LABEL, COLUMN_DIRECTION,
        COLUMN_FILE_NAME, COLUMN_RESULT_SET,
    )
    wanted = set(keys)
    sources = list(sources)
    buckets: Dict[str, set] = {}

    if COLUMN_DIRECTION in wanted:
        buckets[COLUMN_DIRECTION] = {
            split_channel_base_and_direction(label)[1]
            for source in sources for label in source.channels
        }
    if COLUMN_CHANNEL_TYPE in wanted:
        buckets[COLUMN_CHANNEL_TYPE] = {
            facts.get("type")
            for source in sources for facts in source.channels.values()
        }
    if COLUMN_FILE_NAME in wanted:
        buckets[COLUMN_FILE_NAME] = {source.relpath for source in sources}
    if COLUMN_DATA_POOL_LABEL in wanted:
        buckets[COLUMN_DATA_POOL_LABEL] = {source.setup_label for source in sources}
    if COLUMN_RESULT_SET in wanted:
        buckets[COLUMN_RESULT_SET] = {ref.label for ref in result_sets}

    result: Dict[str, List[str]] = {}
    for key, values in buckets.items():
        real = sorted(str(v) for v in values if v not in (None, ""))
        if real:
            result[key] = with_empty_row(real, any(v in (None, "") for v in values))
    return result


def build_channel_facet(sources: Iterable[SourceEntry]) -> List[ChannelIdentity]:
    """
    Every distinct (base_name, direction) channel identity found across
    `sources`, sorted for stable display. Not a schema field -- the channel
    filter always exists and is not something the user can hide.
    """
    identities = set()
    for source in sources:
        for label in source.channels:
            identities.add(split_channel_base_and_direction(label))
    return sorted(identities, key=channel_identity_sort_key)


def apply_metadata_facets(sources: Iterable[SourceEntry], schema: Dict[str, Dict[str, Any]],
                          selected_values: Dict[str, List[str]], *,
                          fields: Optional[Iterable[str]] = None) -> List[SourceEntry]:
    """
    Sources whose fields match every active facet selection: AND across
    fields, OR within one field's selected values. A field absent from
    `selected_values`, or present with no values selected, imposes no
    constraint -- it is simply not being filtered on yet.

    `fields` names the schema fields to evaluate in place of the Filter panel's
    offer (categorical_schema_fields): a saved query names its own fields and has
    already checked their kind, so usable_as_filter is not asked (ADR §1.116).
    """
    fields = (categorical_schema_fields(schema) if fields is None
              else {key: schema[key] for key in fields if key in schema})
    kept = []
    for source in sources:
        matches = True
        for key, wanted in selected_values.items():
            if not wanted or key not in fields:
                continue
            value = _field_value(source, key, fields[key].get("layer", "excel"))
            if (EMPTY_FACET_VALUE if value in (None, "") else str(value)) not in wanted:
                matches = False
                break
        if matches:
            kept.append(source)
    return kept


def build_range_facets(sources: Iterable[SourceEntry],
                       schema: Dict[str, Dict[str, Any]],
                       allowed_keys: Optional[Iterable[str]] = None) -> Dict[str, Tuple[Any, Any]]:
    """
    One entry per opted-in numeric/date field -> the (min, max) span its values
    cover across `sources` -- the bounds a range slider or date picker snaps to.

    Numeric fields yield floats; a date field yields ISO "YYYY-MM-DD" strings,
    which order chronologically as text. A field with no usable value across any
    source is left out, same as an empty categorical facet.

    `allowed_keys` narrows the offering to the Filter card's own columns, same
    as build_metadata_facets (ARCHITECTURE_DECISIONS §1.32).
    """
    fields = _narrowed_to(ranged_schema_fields(schema), allowed_keys)
    spans: Dict[str, Tuple[Any, Any]] = {}
    for key, config in fields.items():
        values = [value for source in sources for value in _range_values(source, key, config)]
        if values:
            spans[key] = (min(values), max(values))
    return spans


def _range_value(raw: Any, config: Dict[str, Any]) -> Optional[Any]:
    """`raw` as the comparable value of a ranged field (float, or ISO date text), None when unusable."""
    if raw in (None, ""):
        return None
    value = str(raw) if field_kind(config) == "date" else _as_number(raw)
    return None if value in (None, "") else value


def _is_channel_layer(config: Dict[str, Any]) -> bool:
    return config.get("layer") == "channel"


def _range_values(source: SourceEntry, key: str, config: Dict[str, Any]) -> List[Any]:
    """Every usable value `source` holds for one ranged field -- one per channel
    for a channel-layer field, else the single file-level value."""
    if _is_channel_layer(config):
        raws = [facts.get(key) for facts in source.channels.values()]
    else:
        raws = [_field_value(source, key, config.get("layer", "excel"))]
    values = (_range_value(raw, config) for raw in raws)
    return [value for value in values if value is not None]


def value_in_range(source: SourceEntry, key: str, config: Dict[str, Any],
                   bounds: Tuple[Any, Any], identity: Optional[ChannelIdentity] = None,
                   channel_index: Optional[int] = None) -> Optional[bool]:
    """
    Whether `source`'s value for one ranged field falls in `bounds` (inclusive).

    A channel-layer field is judged by the curve's own channel when `identity`
    is given (like curve_field_value, but with no fallback to another channel's
    value). Without `identity` -- the batch resolver judging a whole file -- the
    file passes when any of its channels is in range.

    Returns None -- rather than False -- when there is no usable value to
    judge, so a caller can decide what "nothing to judge" means: the
    batch resolver's apply_range_facets below drops it (a range is a positive
    assertion), while the mask path's trace_filter.trace_matches lets it pass
    (ARCHITECTURE_DECISIONS §1.29/§1.32 -- "nemám čo posúdiť" never means
    "skry").
    """
    lo, hi = bounds
    if identity is not None and _is_channel_layer(config):
        facts = resolve_source_channel(source, identity, channel_index) or {}
        values = [v for v in [_range_value(facts.get(key), config)] if v is not None]
    else:
        values = _range_values(source, key, config)
    if not values:
        return None
    return any(lo <= value <= hi for value in values)


def curve_range_value(source: SourceEntry, schema: Dict[str, Dict[str, Any]], key: str,
                      identity: ChannelIdentity, channel_index: Optional[int] = None) -> Optional[Any]:
    """
    The value `value_in_range` judges one curve by for a ranged field (float, or
    ISO date text), None when the field is not ranged or the curve has none: a
    channel-layer field is read off the curve's own channel (no fallback to
    another channel), a file-level field off the source.
    """
    config = ranged_schema_fields(schema).get(key)
    if config is None:
        return None
    if _is_channel_layer(config):
        facts = resolve_source_channel(source, identity, channel_index) or {}
        return _range_value(facts.get(key), config)
    values = _range_values(source, key, config)
    return values[0] if values else None


def apply_range_facets(sources: Iterable[SourceEntry], schema: Dict[str, Dict[str, Any]],
                       selected_ranges: Dict[str, Tuple[Any, Any]], *,
                       fields: Optional[Iterable[str]] = None) -> List[SourceEntry]:
    """
    Sources whose value for every constrained field falls in [lo, hi]: AND
    across fields. `selected_ranges` maps a field to (lo, hi) in the field's own
    type -- floats for numeric fields, ISO date strings for date fields. A field
    absent from the map imposes no constraint; a source missing a constrained
    field is dropped, since a range is a positive assertion (unlike an untouched
    categorical facet).

    `fields` names the schema fields to evaluate in place of the Filter panel's
    offer (ranged_schema_fields), for a saved query (ADR §1.116).
    """
    fields = (ranged_schema_fields(schema) if fields is None
              else {key: schema[key] for key in fields if key in schema})
    kept = []
    for source in sources:
        matches = True
        for key, bounds in selected_ranges.items():
            if key not in fields or not bounds:
                continue
            if value_in_range(source, key, fields[key], bounds) is not True:
                matches = False
                break
        if matches:
            kept.append(source)
    return kept


def build_order_facet(refs: Iterable[ResultSetRef]) -> List[float]:
    """
    Every distinct order value configured for the checked order-cut result
    sets, sorted -- read from ResultSetRef.params rather than the h5 files
    themselves, since orders_to_extract is already right there and a channel
    always stores exactly the orders its result set was computed with.
    """
    orders = set()
    for ref in refs:
        if ref.kind != KIND_ORDER_CUT:
            continue
        for order in ref.params.get("orders_to_extract") or []:
            orders.add(float(order))
    return sorted(orders)


def order_matches(order: float, selected_orders: Iterable[float]) -> bool:
    """
    Whether `order` passes the Order facet.

    BUGS.md K1 (fixed 2026-09-01): an empty selection used to mean "no
    constraint" and matched every order, so unchecking every box in the Order
    group -- with a channel still checked -- kept drawing every order anyway,
    same class of bug as the old Channel-facet one (F1). Order now matches
    Channel's rule instead: nothing selected means nothing matches. The only
    caller that ever passes an empty list already only does so when the Order
    group has values on offer (compare_curve_reader gates on
    `kind == KIND_ORDER_CUT`, which is exactly when build_order_facet
    populates something) -- and FilterPanel.populate_facets defaults a fresh
    Order selection to everything on offer the same way it does Channel, so
    "empty" here only ever means the user explicitly cleared it.

    `order` comes off the result cache's float32 order axis while the facet
    values come from ResultSetRef.params as the exact floats the user typed,
    so the two never compare equal for an order float32 cannot hold. The old
    1e-9 window meant a result set computed for order 2.3 matched nothing at
    all and Apply silently produced no curves; orders_equal is the same tolerance
    cache lookup itself matches orders by.
    """
    selected = list(selected_orders)
    if not selected:
        return False
    return any(orders_equal(order, wanted) for wanted in selected)


def pool_source_entries(runs, entries_by_path) -> List[SourceEntry]:
    """
    The project entries behind the measurements currently in the Data Pool.

    Takes the map from ProjectSession.sources_by_path() rather than a session,
    so this module stays free of everything above it. A run with no entry is
    left out: it has no stored metadata, so there is nothing here to filter it
    by.
    """
    entries = {}
    for run in runs:
        entry = entries_by_path.get(os.path.normcase(os.path.abspath(getattr(run, "file_path", ""))))
        if entry is not None:
            entries[entry.id] = entry
    return list(entries.values())


def resolve_source_channel(source: Optional[SourceEntry],
                           identity: ChannelIdentity,
                           channel_index: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The stored facts of the source channel a trace's identity resolves to
    -- matched on the (base, direction) identity the facet is built from, not
    the raw label (which may still carry a reader prefix, e.g. UNV
    "Time for Acc1:+X"). None when the source is unknown or lists no such
    channel.

    Two stored channels can share one identity (duplicate channel names, #320).
    When `channel_index` (the channel's index in its file) is given, the one
    stored with that index wins; without it, or when none matches, the first
    channel of that identity is returned (#426)."""
    if source is None:
        return None
    matches = [facts for label, facts in source.channels.items()
               if split_channel_base_and_direction(label) == identity]
    if channel_index is not None:
        for facts in matches:
            if facts.get("index") == channel_index:
                return facts
    return matches[0] if matches else None


def resolve_channel_type(source: Optional[SourceEntry], identity: ChannelIdentity,
                         fallback_type: Optional[str],
                         channel_index: Optional[int] = None) -> Optional[str]:
    """
    The Channel type a channel is judged by, in the pool and on a graph
    alike: the type the project stores for the source channel of that identity
    -- the value the Global card's facet was built from, so a channel stored
    with none is "(Empty)" (None here) whatever the reader says (ADR §1.97).
    `fallback_type` only stands in where the project has nothing to say: no
    source entry, or one that lists no such channel.
    """
    facts = resolve_source_channel(source, identity, channel_index)
    return _text_or_none(fallback_type if facts is None else facts.get("type"))


def _passes(value: Optional[str], wanted: Optional[set]) -> bool:
    """Whether one Identity value survives its column; a missing one is "(Empty)"."""
    if wanted is None:
        return True
    return (EMPTY_FACET_VALUE if value in (None, "") else str(value)) in wanted


def _matching_channel_labels(source, schema, column_values, channels):
    """Judge stored or reader channels by the same Filter column values."""
    from core.filter_card_config import (
        COLUMN_CHANNEL, COLUMN_CHANNEL_TYPE, COLUMN_DATA_POOL_LABEL,
        COLUMN_DIRECTION, COLUMN_FILE_NAME,
    )
    wanted = {key: set(values) for key, values in column_values.items()}
    source_values = {
        COLUMN_FILE_NAME: getattr(source, "relpath", None),
        COLUMN_DATA_POOL_LABEL: getattr(source, "setup_label", None),
    }
    channel_columns = {}
    for key, values in wanted.items():
        if key in source_values:
            value = source_values[key]
        elif key in schema and schema[key].get("layer") != "channel":
            value = (_field_value(source, key, schema[key].get("layer", "excel"))
                     if source is not None else None)
        else:
            channel_columns[key] = values
            continue
        if not _passes(value, values):
            return None
    labels = set()
    for label, identity, fallback_type, index in channels:
        identity_values = {
            COLUMN_CHANNEL: identity[0], COLUMN_DIRECTION: identity[1],
        }
        if COLUMN_CHANNEL_TYPE in wanted:
            identity_values[COLUMN_CHANNEL_TYPE] = resolve_channel_type(
                source, identity, fallback_type, index)
        matches = True
        for key, values in channel_columns.items():
            if key in identity_values:
                value = identity_values[key]
            elif key in schema:
                config = schema[key]
                facts = (resolve_source_channel(source, identity, index)
                         if config.get("layer") == "channel" else None)
                if facts is not None:
                    value = facts.get(key)
                elif source is not None:
                    value = _field_value(source, key, config.get("layer", "excel"))
                else:
                    value = None
            else:
                continue
            if not _passes(value, values):
                matches = False
                break
        if matches:
            labels.add(label)
    return labels


def apply_column_facets(sources: Iterable[SourceEntry], schema: Mapping[str, Any],
                        column_values: Mapping[str, Iterable[str]]) -> Dict[str, set]:
    """Measurement × channel pairs satisfying a column rule (ADR §1.131).

    OR within each column, AND across columns. Missing keys impose nothing;
    empty value sets reject every pair. Schema validity is the caller's concern.
    This is also the predicate used by visible_pool_channels. A matching
    measurement with no matching channel retains its key with an empty set.
    """
    result = {}
    columns = {key: set(values) for key, values in column_values.items()}
    for source in sources:
        channels = (
            (label, split_channel_base_and_direction(facts.get("name") or label),
             facts.get("type"), facts.get("index"))
            for label, facts in source.channels.items()
        )
        labels = _matching_channel_labels(source, schema, columns, channels)
        if labels is not None:
            result[source.id] = labels
    return result


def visible_pool_channels(runs, entries_by_path, schema: Dict[str, Dict[str, Any]],
                          selected_values: Dict[str, List[str]],
                          selected_identities: Iterable[ChannelIdentity],
                          selected_ranges: Optional[Dict[str, Tuple[Any, Any]]] = None,
                          selected_identity_values: Optional[Dict[str, List[str]]] = None, *,
                          column_values: Optional[Mapping[str, Iterable[str]]] = None
                          ) -> Optional[Dict[str, set]]:
    """
    What survives the filter panel's selection in the Data Pool: a map from
    each visible measurement's path to the labels of its visible channels.

    Returns None when nothing is being filtered on, which the caller reads as
    "show everything" -- worth distinguishing from an empty map, which means
    the filter is on and matched nothing.

    An empty channel selection imposes no constraint here. That is the
    opposite of what it means in the comparison, where nothing checked means
    nothing worth plotting; in the pool the same rule would empty the tree the
    moment the filter was switched on, which reads as the pool having lost the
    data rather than as a filter waiting to be told what to look for.

    Channel identities are taken from each channel's own name rather than the
    label it is filed under, because the two differ -- the label carries the
    reader's set/column prefix ("Set #3: Acc_X") while the project stores the
    stripped name the facets were built from.

    `selected_ranges` maps a numeric/date field to its (lo, hi) and narrows by
    apply_range_facets, so a measurement with no value for the field is hidden
    like one no metadata filter can judge. `selected_identity_values` maps a
    built-in Identity column (core.filter_card_config COLUMN_*) to the values
    it lets through, EMPTY_FACET_VALUE standing for "has none" (ADR §1.56):
    File name and Data Pool label hide whole measurements, Direction and
    Channel type hide channels. Result set is ignored -- the pool holds
    measurements, and none of them has a result set to be judged by.

    `column_values` supplies an already normalized column rule (ADR §1.131),
    preserving empty constraints. Legacy panel picks keep their existing
    "empty means no pool narrowing" policy; the shared predicate is identical.
    """
    from core.filter_card_config import (
        COLUMN_CHANNEL_TYPE, COLUMN_DATA_POOL_LABEL, COLUMN_DIRECTION, COLUMN_FILE_NAME,
    )
    active_values = {key: values for key, values in (selected_values or {}).items() if values}
    wanted_identities = set(selected_identities or [])
    ranged_fields = ranged_schema_fields(schema)
    active_ranges = {key: bounds for key, bounds in (selected_ranges or {}).items()
                     if bounds and key in ranged_fields}
    wanted_by_column = {
        key: set(values) for key, values in (selected_identity_values or {}).items()
        if values and key in (COLUMN_DIRECTION, COLUMN_CHANNEL_TYPE,
                              COLUMN_FILE_NAME, COLUMN_DATA_POOL_LABEL)
    }
    if not (active_values or wanted_identities or active_ranges or wanted_by_column or column_values):
        return None

    kept_ids = None
    if active_ranges:
        kept = apply_range_facets(pool_source_entries(runs, entries_by_path), schema, active_ranges)
        kept_ids = {source.id for source in kept}
    # The panel decides which fields are active. The column predicate itself
    # also serves saved rules, whose fields need not be offered by the panel.
    active_values = {key: values for key, values in active_values.items()
                     if key in categorical_schema_fields(schema)}
    columns = {**active_values, **wanted_by_column}
    if column_values is not None:
        columns.update({key: set(values) for key, values in column_values.items()})

    visible: Dict[str, set] = {}
    for run in runs:
        entry = entries_by_path.get(os.path.normcase(os.path.abspath(run.file_path)))
        if kept_ids is not None and (entry is None or entry.id not in kept_ids):
            continue
        channels = (
            (label, split_channel_base_and_direction(meta.name or ""), meta.type, meta.index)
            for label, meta in run.available_channels.items()
        )
        labels = _matching_channel_labels(entry, schema, columns, channels)
        if labels is not None and wanted_identities:
            labels &= {label for label, meta in run.available_channels.items()
                       if split_channel_base_and_direction(meta.name or "") in wanted_identities}

        if labels:
            visible[run.file_path] = labels

    return visible


def apply_channel_facet(sources: Iterable[SourceEntry],
                        selected_identities: Iterable[ChannelIdentity]) -> Dict[str, List[str]]:
    """
    For each source, the channel labels whose (base_name, direction) identity
    was selected. A source contributing no matching channel is left out of
    the result entirely.
    """
    wanted = set(selected_identities)
    matches: Dict[str, List[str]] = {}
    for source in sources:
        labels = [
            label for label in source.channels
            if split_channel_base_and_direction(label) in wanted
        ]
        if labels:
            matches[source.id] = labels
    return matches
