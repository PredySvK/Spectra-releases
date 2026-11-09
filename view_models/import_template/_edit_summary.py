"""
What confirming an edit of a project's Import template copy does to the
project: which metadata fields disappear or are renamed, and which Filter cards
and evaluations use them (CONTEXT.md "Import template").

A field is renamed when the same piece of the same source text gives a field of
another name after the edit; otherwise a field the edit no longer gives
disappears. The summary only reads what it is given -- confirming it is the
caller's business, so a Cancel changes nothing.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from core.evaluation import EvaluationConfig
from core.filter_card_config import FilterCardConfig
from core.import_template import ImportTemplate
from io_modules.import_template import resolve_template_field_key


@dataclass(frozen=True)
class FieldConsequence:
    """A field the edit takes away (`renamed_to` blank) or renames, and who uses it."""

    field: str
    renamed_to: str = ""
    filter_cards: Tuple[str, ...] = ()
    evaluations: Tuple[str, ...] = ()

    @property
    def text(self) -> str:
        change = f"is renamed to '{self.renamed_to}'" if self.renamed_to else "disappears"
        users = []
        if self.filter_cards:
            cards = "Filter card" if len(self.filter_cards) == 1 else "Filter cards"
            users.append(f"{len(self.filter_cards)} {cards} ({', '.join(self.filter_cards)})")
        if self.evaluations:
            graphs = "graph" if len(self.evaluations) == 1 else "graphs"
            users.append(f"the evaluation table of {len(self.evaluations)} {graphs} "
                         f"({', '.join(self.evaluations)})")
        used = f"; used by {' and '.join(users)}" if users else "; nothing uses it"
        return f"Field '{self.field}' {change}{used}."


@dataclass(frozen=True)
class TemplateEditSummary:
    """The consequences of replacing the project's copy of `template` by the edited one."""

    template: str
    consequences: Tuple[FieldConsequence, ...] = ()
    added_fields: Tuple[str, ...] = ()

    @property
    def has_losses(self) -> bool:
        """Whether a field the project knows disappears or is renamed."""
        return bool(self.consequences)

    def lines(self) -> Tuple[str, ...]:
        """The summary as sentences for the user, the losses first."""
        lines = tuple(item.text for item in self.consequences)
        lines += tuple(f"Field '{field}' is new." for field in self.added_fields)
        return lines or ("No metadata field disappears or is renamed.",)


def _fields_by_chip(template: ImportTemplate) -> Dict[Tuple[str, int, int, int], str]:
    """(source, header row, chip, piece) -> the field that chip becomes, for every metadata field."""
    return {(field.chip.source, field.chip.row_above, field.chip.chip, field.chip.piece): field.field.strip()
            for field in template.metadata_fields}


def _tab_label(number: int, tab: Mapping[str, Any]) -> str:
    return str(tab.get("custom_label") or f"graph {number} ({tab.get('analysis_kind') or 'graph'})")


def build_template_edit_summary(before: ImportTemplate, after: ImportTemplate, *,
                                filter_cards: Iterable[FilterCardConfig] = (),
                                filter_profiles: Iterable[Mapping[str, Any]] = (),
                                open_tabs: Sequence[Mapping[str, Any]] = ()) -> TemplateEditSummary:
    """
    The consequences of editing the project's copy `before` into `after`.

    `filter_cards` and `filter_profiles` (identity dicts with `id` and `name`)
    are the project's Filter cards; `open_tabs` its open graphs as
    `TabSpec.to_dict()`, whose evaluation tables show metadata columns.
    """
    old, new = _fields_by_chip(before), _fields_by_chip(after)
    old_names, new_names = set(old.values()), set(new.values())
    names = {str(profile.get("id")): str(profile.get("name") or profile.get("id"))
             for profile in filter_profiles}
    cards = tuple(filter_cards)
    evaluations = [(_tab_label(number, tab), EvaluationConfig.from_dict(tab.get("evaluation_config") or {}))
                   for number, tab in enumerate(open_tabs, start=1)]
    consequences, renamed_targets = [], set()
    for field in dict.fromkeys(old.values()):
        if field in new_names:
            continue
        slots = [slot for slot, name in old.items() if name == field]
        renamed_to = next((new[slot] for slot in slots if new.get(slot) and new[slot] not in old_names), "")
        renamed_targets.add(renamed_to)
        key = resolve_template_field_key(field)
        consequences.append(FieldConsequence(
            field=field, renamed_to=renamed_to,
            filter_cards=tuple(names.get(card.id, card.id) for card in cards if card.has_column(key)),
            evaluations=tuple(label for label, config in evaluations if key in config.metadata_columns)))
    added = tuple(field for field in dict.fromkeys(new.values())
                  if field not in old_names and field not in renamed_targets)
    return TemplateEditSummary(before.name, tuple(consequences), added)
