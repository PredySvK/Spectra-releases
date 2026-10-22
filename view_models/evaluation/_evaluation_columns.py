"""
One description of an Evaluation metadata column: its label and whether it is active.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from core.filter_card_config import BUILTIN_COLUMN_KEYS, BUILTIN_COLUMN_LABELS
from selection.field_offer import is_active_field, resolve_field_label


@dataclass(frozen=True)
class ColumnDescriptor:
    """`is_active` is False for a deactivated schema field and for an unknown key."""

    key: str
    label: str
    is_active: bool
    is_builtin: bool


def build_schema_field_descriptor(key: str, field_cfg: Mapping[str, Any]) -> ColumnDescriptor:
    """A Metadata Editor schema field: label is custom_label, else field_name, else the key."""
    return ColumnDescriptor(
        key=key,
        label=resolve_field_label(key, {key: field_cfg}),
        # Active Status, the same gate as the Filters panel and the Cursor Box.
        is_active=is_active_field(field_cfg),
        is_builtin=False,
    )


def build_column_descriptor(key: str, schema: Mapping[str, Mapping[str, Any]]) -> ColumnDescriptor:
    """A built-in column, else a schema field, else an unknown key (inactive, labelled by itself)."""
    if key in BUILTIN_COLUMN_KEYS:
        return ColumnDescriptor(key, BUILTIN_COLUMN_LABELS.get(key, key), True, True)
    if key in schema:
        return build_schema_field_descriptor(key, schema[key])
    return ColumnDescriptor(key, key, False, False)
