# =====================================================================
# FILE: selection/field_offer/_field_offer.py
# =====================================================================
"""
The Field offer: which metadata schema fields a user may pick from, what each
one is called and which section it sits in.

Every place that offers fields (Configure Filters, Cursor Settings, the
Evaluation column selection) or names one (the Filters panel facets, the
Cursor Box, the Evaluation table) asks here, so the Active Status gate, the
label rule and the order cannot drift apart between them (ticket #768).
"""
from dataclasses import dataclass
from typing import Any, Collection, Dict, Mapping, Tuple

from core.filter_card_config import (
    BUILTIN_COLUMN_LABELS, CALCULATED_BUILTIN_ORDER, GROUP_EXCEL, GROUP_RAW,
    IDENTITY_BUILTIN_ORDER,
)
from core.project_model import is_channel_layer

OfferedField = Tuple[str, str]
"""``(key, label)`` of one offered field."""


@dataclass(frozen=True)
class FieldOffer:
    """
    The four sections of a Field offer, each in display order: Identity and
    Calculated metadata in their fixed built-in order, Raw and Excel metadata
    alphabetically by label.
    """

    identity: Tuple[OfferedField, ...]
    raw: Tuple[OfferedField, ...]
    excel: Tuple[OfferedField, ...]
    calculated: Tuple[OfferedField, ...]

    def keys(self) -> Tuple[str, ...]:
        return tuple(key for section in (self.identity, self.raw, self.excel, self.calculated)
                     for key, _label in section)


def is_active_field(config: Mapping[str, Any]) -> bool:
    """A schema field's Active Status; a field without the flag is inactive."""
    return bool(config.get("is_active", False))


def active_schema_fields(schema: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Opted-in fields from the metadata schema (Metadata and Filter Settings'
    "Active Status", ADR §1.188).
    """
    return {key: config for key, config in schema.items() if is_active_field(config)}


def schema_field_group(config: Dict[str, Any]) -> str:
    """
    Public (ticket #42): FilterFieldSelectionDialog sections its Raw metadata
    / Excel metadata columns off the same rule this module already used
    internally to pick a schema field's group.
    """
    return GROUP_RAW if is_channel_layer(config) else GROUP_EXCEL


def resolve_field_label(key: str, schema: Mapping[str, Mapping[str, Any]]) -> str:
    """
    What a field is called wherever it is shown: a built-in's fixed label, else
    the schema field's custom name, else its field_name, else the key itself --
    a blank custom name never yields a blank label.
    """
    if key in BUILTIN_COLUMN_LABELS:
        return BUILTIN_COLUMN_LABELS[key]
    config = schema.get(key, {})
    return config.get("custom_label") or config.get("field_name") or key


def build_field_offer(schema: Mapping[str, Mapping[str, Any]], *,
                      excluded: Collection[str] = ()) -> FieldOffer:
    """
    The Field offer over `schema`: every built-in and every active schema
    field, minus the keys in `excluded` (what one particular place never offers).
    """
    def builtins(order: Tuple[str, ...]) -> Tuple[OfferedField, ...]:
        return tuple((key, BUILTIN_COLUMN_LABELS[key]) for key in order if key not in excluded)

    raw, excel = [], []
    for key, config in schema.items():
        if key in excluded or not is_active_field(config):
            continue
        group = raw if schema_field_group(dict(config)) == GROUP_RAW else excel
        group.append((key, resolve_field_label(key, schema)))

    def by_label(item: OfferedField):
        return item[1].casefold()

    return FieldOffer(
        identity=builtins(IDENTITY_BUILTIN_ORDER),
        raw=tuple(sorted(raw, key=by_label)),
        excel=tuple(sorted(excel, key=by_label)),
        calculated=builtins(CALCULATED_BUILTIN_ORDER),
    )
