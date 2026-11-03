"""
Metadata of a file read by an Import template: the pieces of each metadata
source text, and the fields they become (CONTEXT.md "Import template").

A text is split at every delimiter character; each piece is named by its
position. A piece no rule of the source names, a rule that names no piece, a
key or unit other than the template's, or a split-unit value that is not a
number are why the text does not fit -- a misfit, never a guess. Dropped
pieces are never returned, so they never reach the project.

Kept fields live on the channel as `template:<field>` (resolve_template_field_key),
so a field name never collides with a channel fact or with another reader's
field; `build_template_schema_fields` is their Raw metadata schema.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.import_template import ImportTemplate, MetadataPiece, MetadataSource
from io_modules.metadata_schema import infer_field_kind, resolve_schema_field

TEMPLATE_FIELD_PREFIX = "template:"

_NUMBER_WITH_UNIT_RE = re.compile(r"^\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$")


@dataclass(frozen=True)
class SourcePiece:
    """One piece of a metadata source text, and its key and value when it reads as "key = value" / "key value"."""

    position: int
    text: str
    key: str
    value: str


def resolve_template_field_key(field: str) -> str:
    """The key a template field is stored under on a channel and in the schema."""
    return f"{TEMPLATE_FIELD_PREFIX}{field.strip()}"


def resolve_field_label(piece: MetadataPiece) -> str:
    """The field's name as the Filters panel shows it: with its unit, "Torque [Nm]"."""
    field = piece.field.strip()
    return f"{field} [{piece.unit}]" if piece.split_unit and piece.unit else field


def resolve_key_value(text: str) -> Tuple[str, str]:
    """("key", "value") of "key = value" or "key value" (the last word is the value); ("", text) otherwise."""
    if "=" in text:
        key, value = text.split("=", 1)
        return key.strip(), value.strip()
    parts = text.rsplit(None, 1)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ("", text.strip())


def resolve_number_unit(text: str) -> Optional[Tuple[float, str]]:
    """(-70.0, "Nm") of "-70Nm" or "-70 Nm"; None when the text does not start with a number."""
    match = _NUMBER_WITH_UNIT_RE.match(text)
    if match is None:
        return None
    return float(match.group(1).replace(",", ".")), match.group(2)


def _delimiter_pattern(delimiters: str) -> str:
    """Every delimiter character; a "-" only where it is not a number's sign (after a letter or digit, or before no digit)."""
    others = "".join(character for character in delimiters if character != "-")
    alternatives = ["[" + re.escape(others) + "]"] if others else []
    if "-" in delimiters:
        alternatives.append(r"(?<=[^\W_])-|-(?![\d.,])")
    return "|".join(alternatives)


def build_source_pieces(text: str, delimiters: str) -> Tuple[SourcePiece, ...]:
    """The text's pieces: split at every delimiter, stripped, blanks left out."""
    parts = re.split(_delimiter_pattern(delimiters), text) if delimiters else [text]
    pieces = [part.strip() for part in parts if part.strip()]
    return tuple(SourcePiece(position, piece, *resolve_key_value(piece)) for position, piece in enumerate(pieces))


def resolve_piece_index(position: int, count: int) -> Optional[int]:
    """The 0-based piece a rule's position names in a text of `count` pieces, None when there is no such piece."""
    index = position if position >= 0 else count + position
    return index if 0 <= index < count else None


def _value(piece: SourcePiece, rule: MetadataPiece, describe: str) -> Tuple[Any, str]:
    text = piece.text
    if rule.key:
        if piece.key.lower() != rule.key.lower():
            return None, f"{describe} is '{piece.text}', the template expects the key '{rule.key}'"
        text = piece.value
    if not rule.split_unit:
        return text, ""
    number = resolve_number_unit(text)
    if number is None:
        return None, f"{describe} '{text}' is not a number with a unit"
    value, unit = number
    if unit != rule.unit:
        return None, f"{describe} '{text}' is in '{unit or 'no unit'}', the template expects '{rule.unit}'"
    return value, ""


def resolve_source_fields(text: str, source: MetadataSource, where: str) -> Tuple[Tuple[Tuple[str, Any], ...], str]:
    """
    The kept fields (field, value) one source text gives, in rule order, and
    why the text does not fit the source's rules (blank when it does).
    """
    pieces = build_source_pieces(text, source.delimiters)
    named: List[Tuple[int, MetadataPiece]] = []
    for rule in source.pieces:
        index = resolve_piece_index(rule.position, len(pieces))
        if index is None:
            return (), f"{where} '{text}' has no piece {_describe_position(rule.position)}"
        if any(index == other for other, _ in named):
            return (), f"{where} '{text}' has too few pieces: two rules of the template name one piece"
        named.append((index, rule))
    unknown = [piece.text for piece in pieces if all(piece.position != index for index, _ in named)]
    if unknown and not source.drop_unknown:
        return (), f"{where} '{text}' has a piece the template does not know: '{unknown[0]}'"
    fields: List[Tuple[str, Any]] = []
    for index, rule in named:
        if rule.is_dropped:
            continue
        value, problem = _value(pieces[index], rule, f"piece {index + 1} of {where}")
        if problem:
            return (), problem
        fields.append((rule.field.strip(), value))
    return tuple(fields), ""


def _describe_position(position: int) -> str:
    return f"{position + 1}" if position >= 0 else f"{-position} from the end"


def list_template_pieces(template: ImportTemplate) -> Tuple[MetadataPiece, ...]:
    """Every kept piece rule of the template, in source order."""
    return tuple(rule for source in template.metadata for rule in source.pieces if not rule.is_dropped)


def build_template_schema_fields(templates: Iterable[ImportTemplate],
                                 values_by_key: Dict[str, Sequence[Any]]) -> Dict[str, Dict[str, Any]]:
    """
    The Raw metadata schema fields of these templates' kept pieces, keyed by
    resolve_template_field_key: channel layer, offered, labelled with the unit,
    and of the kind the template sets -- else a split-unit field is a float and
    any other is detected from `values_by_key` as every Raw metadata field is.
    """
    fields: Dict[str, Dict[str, Any]] = {}
    for template in templates:
        for rule in list_template_pieces(template):
            key = resolve_template_field_key(rule.field)
            if key in fields:
                continue
            kind = rule.kind or ("float" if rule.split_unit else infer_field_kind(values_by_key.get(key, ())))
            definition = {"custom_label": resolve_field_label(rule), "is_active": True,
                          "layer": "channel", "kind": kind}
            if rule.split_unit and rule.unit:
                definition["unit"] = rule.unit
            fields[key] = resolve_schema_field(definition)
    return fields
