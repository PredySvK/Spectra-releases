"""Convert editor column checkmarks to and from a Measurement selection rule."""
from dataclasses import dataclass, replace
from typing import Dict, Iterable, Iterator, Mapping, Optional, Set, Tuple

from core.filter_card_config import (
    COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_ORDER, COLUMN_PARAMETER_SET, COLUMN_RESULT_SET,
)
from core.frozen import freeze_str_map
from core.measurement_selection import MODE_QUERY, MeasurementSelection
from core.project_model import FilterSelection
from selection.source_facets import EMPTY_FACET_VALUE, POOL_IDENTITY_COLUMNS
from selection.trace_filter import ResolvedFacets

# Result columns say nothing about which measurement a channel came from, so
# the Selection editor neither draws nor offers them (ADR §1.131).
SELECTION_EXCLUDED_COLUMNS = frozenset({
    COLUMN_RESULT_SET, COLUMN_ORDER, COLUMN_ANALYSIS_TYPE, COLUMN_PARAMETER_SET,
})


@dataclass(frozen=True, eq=False)
class CheckedColumnValues(Mapping[str, Tuple[str, ...]]):
    """Editor checkmarks with the original rule retained for an unchanged Edit.

    A saved restriction may equal today's entire offer. Checkmarks alone cannot
    distinguish it from an unrestricted column; the original rule preserves that
    distinction when an editor opens and saves without changing the picks.
    """
    checked: Mapping[str, Tuple[str, ...]]
    original_column_values: Mapping[str, Tuple[str, ...]]

    def __post_init__(self):
        object.__setattr__(self, "checked", freeze_str_map(self.checked))
        object.__setattr__(self, "original_column_values", freeze_str_map(self.original_column_values))

    def __getitem__(self, key: str) -> Tuple[str, ...]:
        return self.checked[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.checked)

    def __len__(self) -> int:
        return len(self.checked)


def build_column_values(checked: Mapping[str, Iterable[str]],
                        offered: Mapping[str, Iterable[str]], *,
                        original_column_values: Optional[Mapping[str, Iterable[str]]] = None
                        ) -> Dict[str, Tuple[str, ...]]:
    """Store only restricted columns, including deliberately empty columns.

    New fully checked columns remain open to new pool values. An unchanged Edit
    retains the original restriction even when it equals today's entire offer.
    An editor passing updated plain checkmarks supplies original_column_values;
    the mapping returned by resolve_checked_column_values already carries it.
    """
    result = {}
    if original_column_values is None:
        original_column_values = (
            checked.original_column_values if isinstance(checked, CheckedColumnValues) else {}
        )
    for key in sorted(offered.keys() | checked.keys()):
        values = set(checked.get(key, ()))
        original = tuple(original_column_values.get(key, ()))
        if key in original_column_values and values == set(original):
            result[key] = original
        elif key not in offered or values != set(offered[key]):
            result[key] = tuple(sorted(values))
    return result


def resolve_checked_column_values(column_values: Mapping[str, Iterable[str]],
                                  offered: Mapping[str, Iterable[str]]) -> CheckedColumnValues:
    """Restore restricted columns; check every offered value in open columns."""
    original = freeze_str_map(column_values)
    checked = {
        key: tuple(sorted(set(original[key] if key in original else offered[key])))
        for key in sorted(offered.keys() | original.keys())
    }
    return CheckedColumnValues(checked, original)


def resolve_selection_facets(facets: ResolvedFacets) -> ResolvedFacets:
    """Narrow a Global card's facets to what a Measurement selection constrains.

    Channel is offered by base name, as the rule stores it; Direction is its
    own column (ADR §1.131). Result columns and ranges are dropped, and no
    value is greyed: the editor masks no graph.
    """
    bases = sorted({base for base, _direction in facets.channel})
    return replace(
        facets, channel=[(base, None) for base in bases], orders=[], result_kinds=[],
        parameter_sets=[], parameter_set_has_empty=False, ranges={},
        identity={key: values for key, values in facets.identity.items()
                  if key in POOL_IDENTITY_COLUMNS},
        identities=None,
    )


def _with_empty(values: Iterable[str], key: str, checks: FilterSelection) -> Set[str]:
    return set(values) | ({EMPTY_FACET_VALUE} if key in checks.checked_empty_buckets else set())


def build_selection_from_checks(name: str, checks: FilterSelection,
                                facets: ResolvedFacets) -> MeasurementSelection:
    """The query selection the editor's checkmarks describe.

    `facets` is resolve_selection_facets' output the editor drew. A fully
    checked column is left open; an "(Empty)" row is a value like any other.
    """
    offered: Dict[str, Iterable[str]] = {**facets.metadata, **facets.identity}
    checked: Dict[str, Set[str]] = {
        key: _with_empty(checks.checked_metadata_values.get(key, ()), key, checks)
        for key in facets.metadata
    }
    checked.update({
        key: _with_empty(checks.checked_identity_values.get(key, ()), key, checks)
        for key in facets.identity
    })
    if facets.channel:
        offered[COLUMN_CHANNEL] = [base for base, _direction in facets.channel]
        checked[COLUMN_CHANNEL] = {base for base, _direction in checks.checked_channel_identities}
    return MeasurementSelection(
        name=name, mode=MODE_QUERY, column_values=build_column_values(checked, offered))


def build_checks_from_selection(selection: MeasurementSelection,
                                facets: ResolvedFacets) -> FilterSelection:
    """The editor checkmarks a stored rule describes -- the inverse of
    build_selection_from_checks.

    An open column is fully checked; a restricted one keeps its stored values.
    `facets` is resolve_selection_facets' output the editor draws.
    """
    offered: Dict[str, Iterable[str]] = {**facets.metadata, **facets.identity}
    if facets.channel:
        offered[COLUMN_CHANNEL] = [base for base, _direction in facets.channel]
    checked = resolve_checked_column_values(selection.column_values, offered)
    empty = {key for key in (*facets.metadata, *facets.identity)
             if EMPTY_FACET_VALUE in checked.get(key, ())}

    def values(keys) -> Dict[str, Set[str]]:
        return {key: set(checked.get(key, ())) - {EMPTY_FACET_VALUE} for key in keys}

    return FilterSelection(
        checked_metadata_values=values(facets.metadata),
        checked_identity_values=values(facets.identity),
        checked_channel_identities={(base, None) for base in checked.get(COLUMN_CHANNEL, ())},
        checked_empty_buckets=empty,
    )
