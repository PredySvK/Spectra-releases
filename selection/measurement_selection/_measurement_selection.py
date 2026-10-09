# =====================================================================
# FILE: selection/measurement_selection/_measurement_selection.py
# =====================================================================
"""
Internal implementation of measurement selection, channel selection for runs,
and save-spec filtering (ARCHITECTURE_DECISIONS §1.6, §1.12).
"""
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from core.measurement_selection import (
    MODE_EXPLICIT,
    MODE_QUERY,
    MeasurementSelection,
)
from core.models import (
    FUNC_TYPE_TIME_RESPONSE, ChannelIdentity, ChannelMetadata, MeasurementRunIndex,
    is_time_response, resolve_channel_block_kind,
)
from core.project_model import SourceEntry
from core.workflow_graph import SaveSpec
from selection.channel_identity import split_channel_base_and_direction
from selection.source_facets import (
    RANGED_FIELD_KINDS,
    apply_column_facets,
    apply_channel_facet,
    POOL_IDENTITY_COLUMNS,
    apply_metadata_facets,
    apply_range_facets,
    field_kind,
    resolve_channel_type,
)

WHOLE_POOL_SELECTION_NAME = "Whole Data Pool"

def _constraint_note(key: str, reason: str) -> str:
    return f"saved constraint on {key!r} was not applied: {reason}"


def _bounds_are_text(bounds: Tuple[Any, Any]) -> bool:
    return all(isinstance(bound, str) for bound in bounds)


def _saved_facet_plan(metadata_values: Mapping[str, Any],
                      ranges: Mapping[str, Tuple[Any, Any]],
                      schema: Mapping[str, Any], *, column_rule: bool = False
                      ) -> Tuple[Dict[str, List[str]], Dict[str, Tuple[Any, Any]], Tuple[str, ...]]:
    """
    Split a saved query into constraints that can still be evaluated and ones
    that cannot (ADR §1.116).

    `usable_as_filter` is not consulted: it decides what the Filter panel offers,
    not whether a query written earlier still names a real column. A missing
    field, or one whose kind no longer matches the constraint, is named instead
    of being skipped in silence.
    """
    categorical: Dict[str, List[str]] = {}
    ranged: Dict[str, Tuple[Any, Any]] = {}
    notes: List[str] = []

    for key, values in (metadata_values or {}).items():
        if column_rule and key in POOL_IDENTITY_COLUMNS:
            categorical[key] = list(values)
            continue
        if not values and not column_rule:
            continue
        config = schema.get(key)
        if not isinstance(config, dict):
            notes.append(_constraint_note(key, "the field is not in the metadata schema"))
            continue
        kind = field_kind(config)
        if kind in RANGED_FIELD_KINDS:
            notes.append(_constraint_note(
                key, f"the field kind is {kind!r}, not categorical"))
            continue
        categorical[key] = list(values)

    for key, bounds in (ranges or {}).items():
        if not bounds:
            continue
        config = schema.get(key)
        if not isinstance(config, dict):
            notes.append(_constraint_note(key, "the field is not in the metadata schema"))
            continue
        kind = field_kind(config)
        if kind not in RANGED_FIELD_KINDS:
            notes.append(_constraint_note(key, f"the field kind is {kind!r}, not a range"))
            continue
        if kind == "date" and not _bounds_are_text(bounds):
            notes.append(_constraint_note(
                key, f"the field kind is {kind!r}, not a numeric range"))
            continue
        if kind in ("int", "float") and _bounds_are_text(bounds):
            notes.append(_constraint_note(
                key, f"the field kind is {kind!r}, not a date range"))
            continue
        ranged[key] = bounds

    return categorical, ranged, tuple(notes)


def _apply_saved_facets(sources: Iterable[SourceEntry],
                        schema: Optional[Mapping[str, Any]],
                        metadata_values: Mapping[str, Any],
                        ranges: Mapping[str, Tuple[Any, Any]]
                        ) -> Tuple[List[SourceEntry], Tuple[str, ...]]:
    schema = schema or {}
    categorical, ranged, notes = _saved_facet_plan(metadata_values, ranges, schema)
    kept = list(sources)
    if categorical:
        kept = apply_metadata_facets(kept, schema, categorical, fields=categorical)
    if ranged:
        kept = apply_range_facets(kept, schema, ranged, fields=ranged)
    return kept, notes


def whole_pool_selection() -> MeasurementSelection:
    """
    The synthetic selection an input node with `whole_pool=True` runs over: a
    query with no column constraints, which `resolve`
    evaluates to every measurement currently in the pool, every channel. Built
    fresh each run (never saved) so it always reflects the pool as it is now --
    that is what "grows with the pool" means.
    """
    return MeasurementSelection(
        name=WHOLE_POOL_SELECTION_NAME, mode=MODE_QUERY,
    )


@dataclass(frozen=True)
class SelectionResolution:
    """
    What a selection means right now.

    `channels_by_source` is what a runner fans out over: one chain run per
    (source, channel) pair. `dropped_without_channels` counts measurements that
    matched the query but contribute no selected channel -- worth showing in the
    \"Run on selection\" dialog, because \"40 measurements, 0 runs\" otherwise looks
    like a bug rather than like a channel filter that matches nothing.
    `unevaluable_constraints` names saved metadata or range constraints the
    schema can no longer judge (ADR §1.116); the runner logs each as a WARNING.
    """
    sources: List[SourceEntry]
    channels_by_source: Dict[str, List[str]]
    channel_identities: List[ChannelIdentity]
    dropped_without_channels: int = 0
    unevaluable_constraints: Tuple[str, ...] = ()
    skipped_non_time_sources: Tuple[str, ...] = ()

    @property
    def measurement_count(self) -> int:
        return len(self.sources)

    @property
    def channel_count(self) -> int:
        return len(self.channel_identities)

    @property
    def leaf_count(self) -> int:
        """Chain runs this selection produces -- the denominator of \"12/408\"."""
        return sum(len(labels) for labels in self.channels_by_source.values())

    def describe(self) -> str:
        """One line for a confirmation dialog or the log."""
        return (
            f"{self.measurement_count} measurement(s), "
            f"{self.channel_count} channel(s), {self.leaf_count} run(s)"
        )


def resolve(selection: MeasurementSelection,
            sources: Iterable[SourceEntry],
            schema: Optional[Dict[str, Dict[str, Any]]] = None,
            channel_types: Optional[Iterable[str]] = None, *,
            time_responses_only: bool = False) -> SelectionResolution:
    """
    Evaluate `selection` against `sources` (the project entries the caller
    considers candidates -- typically the Data Pool via
    selection.source_facets.pool_source_entries).

    A source id in an explicit selection that no longer exists is silently
    skipped rather than raising: a measurement can be deleted or moved between
    saving a selection and running it, and losing the whole batch over one
    missing file is worse than running it over the rest. The count difference is
    visible in the resolution.

    `channel_types` additionally narrows the column rule by the save nodes'
    type scope. None means every readable channel, including Imported results.
    Computation callers set `time_responses_only` to exclude non-waveforms.
    """
    schema = schema or {}
    candidates = list(sources)
    unevaluable: Tuple[str, ...] = ()

    if selection.mode == MODE_EXPLICIT:
        wanted_ids = set(selection.source_ids)
        matched = [source for source in candidates if source.id in wanted_ids]
    else:
        matched = candidates
        if selection.setup_labels:
            allowed = set(selection.setup_labels)
            matched = [source for source in matched if source.setup_label in allowed]
    if selection.mode == MODE_EXPLICIT:
        columns = {key: values for key, values in selection.column_values.items()
                   if key in POOL_IDENTITY_COLUMNS}
        ranges = {}
    else:
        columns, ranges, unevaluable = _saved_facet_plan(
            selection.column_values, selection.ranges, schema, column_rule=True)
    if ranges:
        matched = apply_range_facets(matched, schema, ranges, fields=ranges)
    picked = apply_column_facets(matched, schema, columns)
    matched = [source for source in matched if source.id in picked]
    if selection.mode == MODE_EXPLICIT and selection.channel_identities is not None:
        exact = apply_channel_facet(matched, selection.channel_identities)
        picked = {source_id: labels & set(exact.get(source_id, ()))
                  for source_id, labels in picked.items()}
    channels_by_source = _channels_for(matched, picked, channel_types,
                                      time_responses_only=time_responses_only)
    skipped = tuple(
        source.relpath for source in matched
        if time_responses_only and any(
            source.channels[label].get("block_kind")
            and not is_time_response(source.channels[label].get("func_type", FUNC_TYPE_TIME_RESPONSE))
            for label in picked.get(source.id, ())
        )
    )

    kept = [source for source in matched if channels_by_source.get(source.id)]
    identities = sorted({
        split_channel_base_and_direction(source.channels[label].get("name") or label)
        for source in kept for label in channels_by_source[source.id]
    }, key=lambda identity: (identity[0], identity[1] is None, identity[1] or ""))

    return SelectionResolution(
        sources=kept,
        channels_by_source={source.id: channels_by_source[source.id] for source in kept},
        channel_identities=identities,
        dropped_without_channels=len(matched) - len(kept),
        unevaluable_constraints=unevaluable,
        skipped_non_time_sources=skipped,
    )


@dataclass(frozen=True)
class SaveSourceResolution:
    """
    Which measurements a `SaveSpec` keeps, and which of its saved constraints
    the schema can no longer evaluate (ADR §1.116).
    """
    sources: List[SourceEntry]
    unevaluable_constraints: Tuple[str, ...] = ()


def resolve_save_sources(save: SaveSpec, sources: Iterable[SourceEntry],
                         schema: Optional[Dict[str, Dict[str, Any]]] = None) -> SaveSourceResolution:
    """
    The measurements a `SaveSpec` keeps: `sources` narrowed by its metadata and
    range facets (ADR §1.6 phase 7B, ADR §1.116).

    Same functions as `resolve()`'s query branch and the same reason -- the batch
    and the Compare tab must agree on what \"these measurements\" means. An empty
    or absent facet imposes no constraint; a range facet naming a field a source
    lacks drops that source, because a range is a positive assertion. A constraint
    whose field is gone or has changed kind is not applied and is named on the
    result, the same rule `resolve` uses.
    """
    kept, notes = _apply_saved_facets(
        sources, schema, save.metadata_values, save.ranges)
    return SaveSourceResolution(sources=kept, unevaluable_constraints=notes)


def save_spec_allows_channel(save: SaveSpec, channel_name: str, channel_type: str) -> bool:
    """
    Whether one channel's results are written at a node carrying this `SaveSpec`.

    `channel_types` is an AND constraint (drop anything not of a listed type).
    On top of that: `all_channels` keeps every remaining channel; otherwise only
    the listed `channel_identities` pass, and an empty list means *no* channels
    (the same distinction the field's own comment draws).
    """
    if save.channel_types and channel_type not in save.channel_types:
        return False
    if save.all_channels:
        return True
    if not save.channel_identities:
        return False
    identity = split_channel_base_and_direction(channel_name)
    return identity in set(save.channel_identities)


def _channels_for(sources: List[SourceEntry], picked: Mapping[str, Iterable[str]],
                  channel_types: Optional[Iterable[str]] = None, *,
                  time_responses_only: bool = False) -> Dict[str, List[str]]:
    """Keep the rule's readable channels within the save nodes' type scope."""
    # The stored channel snapshot is ChannelMetadata.to_dict(), so the type sits
    # under \"type\" (compare gui/handlers/filter_routing.py, which reads it the
    # same way). With a type constraint, a channel with no stored type is dropped: a type
    # constraint is a positive assertion, the same rule resolve_save_sources
    # applies to range facets.
    wanted = set(channel_types) if channel_types is not None else None
    by_id = {source.id: source for source in sources}
    narrowed = {}
    for source_id, labels in picked.items():
        stored = by_id[source_id].channels
        kept = []
        for label in sorted(labels):
            facts = stored.get(label) or {}
            readable = (is_time_response(facts.get("func_type", FUNC_TYPE_TIME_RESPONSE))
                        if time_responses_only else
                        resolve_channel_block_kind(ChannelMetadata.from_dict(facts)) is not None)
            if (readable
                    and (wanted is None or facts.get("type") in wanted)):
                kept.append(label)
        if kept:
            narrowed[source_id] = kept
    return narrowed


def resolve_run_channel_type(source: Optional[SourceEntry],
                             channel_meta: ChannelMetadata) -> Optional[str]:
    """
    The type a batch judges one of a run's channels by -- offering it, planning
    it and deciding whether a SaveSpec keeps it all ask this, so the three can
    no longer disagree. It is the Filter panel's rule (ADR §1.97): the type the
    project stores for that channel, the reader's only where the project is
    silent. None is a channel stored with no type, which no type constraint keeps.
    """
    identity = split_channel_base_and_direction(channel_meta.name)
    return resolve_channel_type(source, identity, channel_meta.type, channel_meta.index)


def channel_identities_by_type(runs: Iterable[MeasurementRunIndex],
                               channel_types: Optional[Set[str]],
                               entries_by_path: Optional[Mapping[str, SourceEntry]] = None,
                               ) -> Dict[str, List[Optional[str]]]:
    """
    Every distinct (base_name, direction) found across `runs`, restricted to
    the given channel types (None: any type a channel has at all), grouped as
    base_name -> sorted directions.

    `entries_by_path` is ProjectSession.sources_by_path(): a channel is judged
    by `resolve_run_channel_type`, so what is offered here is what the plan's
    typed SaveSpec goes on to keep.
    """
    entries_by_path = entries_by_path or {}
    grouped: Dict[str, Set[Optional[str]]] = {}
    for run in runs:
        source = entries_by_path.get(os.path.normcase(os.path.abspath(run.file_path)))
        for channel_meta in run.readable_channels():
            channel_type = resolve_run_channel_type(source, channel_meta)
            if channel_type is None or (channel_types is not None
                                        and channel_type not in channel_types):
                continue
            base, direction = split_channel_base_and_direction(channel_meta.name)
            grouped.setdefault(base, set()).add(direction)

    return {
        base: sorted(directions, key=lambda d: (d is None, d))
        for base, directions in grouped.items()
    }


def select_channels_for_run(run: MeasurementRunIndex,
                            wanted: Set[ChannelIdentity],
                            channel_types: Set[str]) -> List[ChannelMetadata]:
    """The channels in one run whose identity was picked and whose type matches."""
    matches = []
    for channel_meta in run.readable_channels():
        if channel_meta.type not in channel_types:
            continue
        identity = split_channel_base_and_direction(channel_meta.name)
        if identity in wanted:
            matches.append(channel_meta)
    return matches


def build_channel_drop_descriptors(resolution: SelectionResolution,
                                   files_by_source: Mapping[str, Tuple[str, str]]) -> List[dict]:
    """
    The channels of `resolution` as the drop descriptors a Data Pool drag
    carries (file_path, file_name, channel_index, channel_name, channel_type,
    unit), so a Selection takes the same route into a graph as dragged rows.

    `files_by_source` maps a source id to the `(file_path, file_name)` of its
    loaded run; a measurement that is not loaded has nothing to draw and is
    skipped, like a source id that no longer exists in `resolve()`.
    """
    descriptors = []
    for source in resolution.sources:
        if source.id not in files_by_source:
            continue
        file_path, file_name = files_by_source[source.id]
        for label in resolution.channels_by_source[source.id]:
            facts = source.channels[label]
            descriptors.append({
                "file_path": str(file_path),
                "file_name": str(file_name),
                "channel_index": int(facts.get("index", 0)),
                "channel_name": str(facts.get("name") or label),
                "channel_type": str(facts.get("type", "")),
                "unit": str(facts.get("unit", "")),
                "block_kind": resolve_channel_block_kind(ChannelMetadata.from_dict(facts)),
                "func_type": facts.get("func_type", FUNC_TYPE_TIME_RESPONSE),
            })
    return descriptors
