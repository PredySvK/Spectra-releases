# =====================================================================
# FILE: session/measurement_selection.py
# =====================================================================
"""
The Selection draft (#906): what the user has set in the Selection editor and
not yet confirmed -- the name and the checked values -- without Qt.

Opening a draft resolves the offer (the Selection editor's facets over the
whole Data Pool) and lays the checkmarks on it in one step: everything checked
for a new Selection, the stored rule's checkmarks for an Edit. The editor then
draws once. An Edit also widens the editor's column card by every column the
rule restricts, so no part of the rule is invisible, and keeps the rule it
opened, so a column whose checkmarks are left unchanged keeps its saved
restriction (#700). Nothing in the project changes here: storing the card and
the accepted Selection is the caller's business.
"""
from typing import Iterable, Mapping, Optional

from core.filter_card_config import BUILTIN_COLUMN_KEYS, FilterCardConfig, add_column
from core.measurement_selection import MeasurementSelection
from core.project_model import FilterSelection
from selection.measurement_selection import (
    SELECTION_EXCLUDED_COLUMNS, WHOLE_POOL_SELECTION_NAME, SelectionResolution,
    build_checks_from_selection, build_selection_from_checks, resolve_selection_cardinalities,
    resolve_selection_facets,
)
from selection.source_facets import all_pool_sources
from selection.trace_filter import (
    CardCardinalities, ResolvedFacets, build_column_for_key, resolve_card_cardinalities,
    resolve_panel_facets, write_checks,
)
from session.trace_filter import FilterSelectionStore

# The project's Filter card id the editor's column configuration lives under.
SELECTION_CARD_ID = "measurement_selection_editor"


def _with_rule_columns(card: FilterCardConfig, column_values: Mapping[str, Iterable[str]],
                       schema: dict) -> FilterCardConfig:
    """`card` plus every column the rule restricts that it does not list."""
    for key in column_values:
        if (key not in SELECTION_EXCLUDED_COLUMNS and not card.has_column(key)
                and (key in schema or key in BUILTIN_COLUMN_KEYS)):
            card = add_column(card, build_column_for_key(key, schema))
    return card


class MeasurementSelectionDraft:
    """One Create or Edit in the Selection editor, from opening to OK."""

    def __init__(self, project, schema: dict, card: FilterCardConfig, *,
                 selection: Optional[MeasurementSelection] = None,
                 taken_names: Iterable[str] = ()):
        self._project = project
        self._schema = schema
        self.pool_sources = all_pool_sources(project)
        self.is_edit = selection is not None
        self.name = selection.name if selection else ""
        self._taken_names = set(taken_names) | {WHOLE_POOL_SELECTION_NAME}
        self._original_column_values = selection.column_values if selection else {}
        self.store = FilterSelectionStore()
        self.store.set_scope(SELECTION_CARD_ID, "global")
        self.card: FilterCardConfig = card
        self.facets: Optional[ResolvedFacets] = None
        self.set_card(_with_rule_columns(card, self._original_column_values, schema)
                      if selection else card)
        if selection is not None:
            write_checks(self.checks, build_checks_from_selection(selection, self.facets))

    @property
    def selection_key(self):
        """The (card, dock) key the editor's checks live under in `store`."""
        return SELECTION_CARD_ID, None

    @property
    def checks(self) -> FilterSelection:
        """The checked values; the editor's clicks edit them in place."""
        return self.store.active_selection(*self.selection_key)

    def set_card(self, card: FilterCardConfig) -> None:
        """Offer `card`'s columns: the facets are resolved again and the checks
        go through one render round, so a newly shown column starts checked and
        the checks already made stay."""
        self.card = card
        facets = resolve_panel_facets(
            "global", card, self._schema, project=self._project,
            pool_sources=self.pool_sources, focused_identities=[], open_dock_identities=[])
        self.facets = resolve_selection_facets(facets)
        self.store.resolve_render(*self.selection_key, self.facets)

    def resolve_cardinalities(self) -> CardCardinalities:
        """The "(N)" counts Configure shows, in the editor's shape (Channel by base name)."""
        counts = resolve_card_cardinalities(
            "global", self._schema, project=self._project, pool_sources=self.pool_sources,
            focused_identities=[], open_dock_identities=[])
        return resolve_selection_cardinalities(counts, self.pool_sources)

    def resolve_selection(self) -> MeasurementSelection:
        """The rule the current checkmarks describe, under the draft's name."""
        return build_selection_from_checks(
            self.name.strip(), self.checks, self.facets,
            original_column_values=self._original_column_values)

    def problem(self, resolution: Optional[SelectionResolution]) -> str:
        """Why OK is refused, or "" -- `resolution` is the last count, None while counting."""
        name = self.name.strip()
        if not name:
            return "Type a name."
        if name in self._taken_names:
            return f"'{name}' is already taken."
        if resolution is not None and resolution.measurement_count == 0:
            return "Nothing matches -- check at least one value in every column."
        return ""
