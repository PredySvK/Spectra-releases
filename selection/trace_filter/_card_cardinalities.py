# =====================================================================
# FILE: selection/trace_filter/_card_cardinalities.py
# =====================================================================
"""
One resolver for a card's "(N)" counts and "cannot narrow" verdicts.

Configure Filters shows a count next to every column, including columns the
card does not carry yet, so the counts cover all columns while the panel's
facets cover the card's own. Both read the same inputs `resolve_panel_facets`
reads -- the pool sources, the open docks and the focused dock -- and the one
`if scope` lives here, so a count cannot drift from the facet it describes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from selection.source_facets import FieldCardinality, filter_field_cardinalities
from ._filter_card import builtin_column_cardinalities_for_global, local_card_cardinalities
from ._trace_filter import TraceIdentity


@dataclass(frozen=True)
class CardCardinalities:
    """Counts for every schema field (`schema_fields`) and every built-in
    Identity / Calculated column (`builtins`), keyed by column key."""
    schema_fields: Dict[str, FieldCardinality]
    builtins: Dict[str, FieldCardinality]


def resolve_card_cardinalities(scope: str, schema: Dict[str, Dict[str, Any]], *, project,
                               pool_sources: Iterable,
                               focused_identities: List[TraceIdentity],
                               open_dock_identities: List[TraceIdentity]) -> CardCardinalities:
    """
    `scope` and inputs exactly as `resolve_panel_facets` takes them: "global"
    counts the pool sources, plus the open docks unioned with the Result Pool
    for the Calculated columns; anything else is Local and counts
    only `focused_identities`.
    """
    if scope == "global":
        sources = list(pool_sources)
        return CardCardinalities(
            schema_fields=filter_field_cardinalities(sources, schema),
            builtins=builtin_column_cardinalities_for_global(
                project, open_dock_identities, sources=sources),
        )
    schema_fields, builtins = local_card_cardinalities(focused_identities, schema)
    return CardCardinalities(schema_fields=schema_fields, builtins=builtins)
