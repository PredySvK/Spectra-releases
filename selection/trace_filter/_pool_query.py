"""
The Filter panel's selection read as a Column rule -- what
selection.source_facets.visible_pool_channels is asked to narrow by.

The pool and the dock mask read the same FilterSelection and OfferedFacets but
answer different questions: the mask hides what the card offered and
the user unchecked, the pool keeps a positive list. So the pool may only be told
about a column that is a *real narrowing* -- a column with every offered value
checked, or with nothing checked, says nothing. Without that a Local card,
offering only what its dock draws and checking all of it by default, would hide
every pool measurement and channel the dock does not happen to hold.

Pure (no Qt), so the rule is testable without a FilterPanel.
"""

from __future__ import annotations

from typing import AbstractSet, Dict, List, Mapping

from core.project_model import FilterSelection
from selection.source_facets import ColumnRule, channel_identity_sort_key

from ._trace_filter import EMPTY_FACET_VALUE, OfferedFacets


def resolve_pool_query(selection: FilterSelection, offering: OfferedFacets) -> ColumnRule:
    """
    The Column rule for one card's `selection` against what it currently
    offers. Every field leaves out what imposes no constraint, so an untouched
    card gives an open rule. A checked "(Empty)" bucket travels as
    EMPTY_FACET_VALUE in `column_values`.

    Discrete metadata, Identity columns and Channel are reported only as a real
    narrowing (§1.96, §1.107); a moved range only while its widget is on the
    card (§1.29, §1.32).
    """
    offered_channels = set(offering.channel_identities)
    checked_channels = set(selection.checked_channel_identities) & offered_channels
    narrows_channels = bool(checked_channels) and checked_channels != offered_channels
    return ColumnRule(
        column_values={
            **_narrowing(offering.metadata_values, selection.checked_metadata_values,
                         selection, offering),
            **_narrowing(offering.identity_values, selection.checked_identity_values,
                         selection, offering),
        },
        ranges={key: bounds for key, bounds in selection.checked_ranges.items()
                if bounds and key in offering.range_fields},
        channel_identities=(sorted(checked_channels, key=channel_identity_sort_key)
                            if narrows_channels else None),
    )


def _narrowing(offered_by_key: Mapping[str, AbstractSet[str]],
               checked_by_key: Mapping[str, AbstractSet[str]],
               selection: FilterSelection, offering: OfferedFacets) -> Dict[str, List[str]]:
    """The "is this a real narrowing" rule for a metadata or Identity column:
    every offered value (and "(Empty)", when offered) checked, or nothing
    checked, leaves the column out."""
    selected = {}
    for key, offered in offered_by_key.items():
        values = set(checked_by_key.get(key, set())) & set(offered)
        offers_empty = key in offering.empty_buckets
        keeps_empty = offers_empty and key in selection.checked_empty_buckets
        if not values and not keeps_empty:
            continue
        if values != set(offered) or keeps_empty != offers_empty:
            selected[key] = sorted(values) + ([EMPTY_FACET_VALUE] if keeps_empty else [])
    return selected
