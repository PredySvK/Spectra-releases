"""
Metadata fields of a file read by an Import template (CONTEXT.md "Import template").

Kept fields live on the channel as `template:<field>` (resolve_template_field_key),
so a field name never collides with a channel fact or with another reader's
field; `build_template_schema_fields` is their Raw metadata schema. The chips the
fields are taken from are `_text_chips.py`.
"""

import re
from typing import Any, Dict, Iterable, Sequence

from core.import_template import ImportTemplate
from io_modules.metadata_schema import infer_field_kind, resolve_schema_field

TEMPLATE_FIELD_PREFIX = "template:"


def resolve_template_field_key(field: str) -> str:
    """The key a template field is stored under on a channel and in the schema."""
    return f"{TEMPLATE_FIELD_PREFIX}{field.strip()}"


def _label(field: str, unit: str) -> str:
    return f"{field.strip()} [{unit}]" if unit else field.strip()


def _delimiter_pattern(delimiters: str) -> str:
    """Every delimiter character; a "-" only where it is not a number's sign (after a letter or digit, or before no digit)."""
    others = "".join(character for character in delimiters if character != "-")
    alternatives = ["[" + re.escape(others) + "]"] if others else []
    if "-" in delimiters:
        alternatives.append(r"(?<=[^\W_])-|-(?![\d.,])")
    return "|".join(alternatives)


def build_template_schema_fields(templates: Iterable[ImportTemplate],
                                 values_by_key: Dict[str, Sequence[Any]]) -> Dict[str, Dict[str, Any]]:
    """
    The Raw metadata schema fields of these templates' kept fields, keyed by
    resolve_template_field_key: channel layer, offered, labelled with the unit,
    and of the kind the template sets -- else a number's field (the number in
    a chip) is a float and any other is detected from
    `values_by_key` as every Raw metadata field is.
    """
    fields: Dict[str, Dict[str, Any]] = {}
    for template in templates:
        for field in template.metadata_fields:
            key = resolve_template_field_key(field.field)
            if key in fields:
                continue
            kind = field.kind or ("float" if field.is_number else infer_field_kind(values_by_key.get(key, ())))
            definition = {"custom_label": _label(field.field, field.unit), "is_active": True,
                          "layer": "channel", "kind": kind}
            if field.is_number and field.unit:
                definition["unit"] = field.unit
            fields[key] = resolve_schema_field(definition)
    return fields
