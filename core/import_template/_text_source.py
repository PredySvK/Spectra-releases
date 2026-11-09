"""
The texts around a channel in an Import template: sources, chips
and roles (CONTEXT.md "Import template").

A text source is a column header row (counted up from the heading row, 0 = the
heading row itself), the sheet name, the file name or the folder. It is split
at its delimiters into chips; a chip may hold its own cuts, whose pieces are
ordinary chips addressed as (source, chip, piece). A role -- channel name,
axis, order, sample rate or a metadata field -- names one chip by a ChipRef.
Everything here is a value the reader looks at; reading it is
io_modules/import_template.
"""

from dataclasses import dataclass
from typing import Any, Dict, Tuple

# Where a text is taken from.
SOURCE_HEADER = "header"
SOURCE_SHEET = "sheet"
SOURCE_FILE_NAME = "file_name"
SOURCE_FOLDER = "folder"
TEXT_SOURCES = (SOURCE_HEADER, SOURCE_SHEET, SOURCE_FILE_NAME, SOURCE_FOLDER)

# The characters a text is split at, unless the template says others.
DEFAULT_DELIMITERS = "_,:\\-;"
# The kinds a metadata field can be; blank is detected from the values.
FIELD_KINDS = ("str", "int", "float", "date")

# A chip's own cuts. letters_digits: at every boundary between a letter and a
# digit. after_text: right after `text`. after_characters: after `count`
# characters. before_end: `count` characters before the end. cut_out: `text` is
# removed and splits the chip like a delimiter.
CUT_LETTERS_DIGITS = "letters_digits"
CUT_AFTER_TEXT = "after_text"
CUT_AFTER_CHARACTERS = "after_characters"
CUT_BEFORE_END = "before_end"
CUT_OUT = "cut_out"
CUT_KINDS = (CUT_LETTERS_DIGITS, CUT_AFTER_TEXT, CUT_AFTER_CHARACTERS, CUT_BEFORE_END, CUT_OUT)
_CUTS_WITH_TEXT = (CUT_AFTER_TEXT, CUT_OUT)
_CUTS_WITH_COUNT = (CUT_AFTER_CHARACTERS, CUT_BEFORE_END)

# What a metadata field takes from its chip: the whole chip, or the number in it.
FIELD_VALUE_CHIP = "chip"
FIELD_VALUE_NUMBER = "number"
FIELD_VALUES = (FIELD_VALUE_CHIP, FIELD_VALUE_NUMBER)


def resolve_source_key(source: str, row_above: int) -> Tuple[str, int]:
    """The identity of a text source: its kind, and for a header its row (other kinds have none)."""
    return source, (row_above if source == SOURCE_HEADER else 0)


def _checked_source(data: Dict[str, Any]) -> Tuple[str, int]:
    source = data.get("source")
    if source not in TEXT_SOURCES:
        raise ValueError(f"Unknown text source {source!r}; expected one of {TEXT_SOURCES}.")
    row_above = int(data.get("row_above", 0))
    if row_above < 0:
        raise ValueError(f"A header row cannot be {row_above} rows above the heading row.")
    return resolve_source_key(source, row_above)


@dataclass(frozen=True)
class ChipCut:
    """One of a chip's own cuts (see CUT_KINDS); `text` or `count` is what the kind needs."""

    kind: str
    text: str = ""
    count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"cut": self.kind}
        if self.kind in _CUTS_WITH_TEXT:
            data["text"] = self.text
        if self.kind in _CUTS_WITH_COUNT:
            data["count"] = self.count
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChipCut":
        kind = data.get("cut")
        if kind not in CUT_KINDS:
            raise ValueError(f"Unknown chip cut {kind!r}; expected one of {CUT_KINDS}.")
        text, count = str(data.get("text", "")), int(data.get("count", 0))
        if kind in _CUTS_WITH_TEXT and not text:
            raise ValueError(f"The chip cut {kind!r} needs the text it cuts at.")
        if kind in _CUTS_WITH_COUNT and count < 1:
            raise ValueError(f"The chip cut {kind!r} cannot count {count} characters.")
        return cls(kind, text if kind in _CUTS_WITH_TEXT else "", count if kind in _CUTS_WITH_COUNT else 0)


@dataclass(frozen=True)
class ChipCuts:
    """
    The own cuts of one chip of a source, applied in order. `chip` counts the
    chips from 0, or from the end when negative (-1 = the last).
    """

    chip: int
    cuts: Tuple[ChipCut, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {"chip": self.chip, "cuts": [cut.to_dict() for cut in self.cuts]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChipCuts":
        cuts = tuple(ChipCut.from_dict(cut) for cut in data.get("cuts", ()))
        if not cuts:
            raise ValueError(f"Chip {data.get('chip')} lists no cut.")
        return cls(int(data["chip"]), cuts)


@dataclass(frozen=True)
class TextSource:
    """
    A text around a channel, split into chips: at every character of
    `delimiters` (blank chips left out; a "-" that is a number's sign, "-70Nm",
    does not split), then each chip of `cut_chips` by its own cuts.
    """

    source: str
    row_above: int = 0
    delimiters: str = DEFAULT_DELIMITERS
    cut_chips: Tuple[ChipCuts, ...] = ()

    @property
    def key(self) -> Tuple[str, int]:
        return resolve_source_key(self.source, self.row_above)

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "row_above": self.row_above, "delimiters": self.delimiters,
                "cuts": [chip.to_dict() for chip in self.cut_chips]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TextSource":
        source, row_above = _checked_source(data)
        cut_chips = tuple(ChipCuts.from_dict(chip) for chip in data.get("cuts", ()))
        positions = [chip.chip for chip in cut_chips]
        if len(set(positions)) != len(positions):
            raise ValueError(f"A chip of the text source {source!r} lists its cuts twice.")
        return cls(source, row_above, str(data.get("delimiters", DEFAULT_DELIMITERS)), cut_chips)


@dataclass(frozen=True)
class ChipRef:
    """
    One chip a role takes: the source (`source`, `row_above` as in TextSource),
    the chip (from 0, or from the end when negative) and, when the chip has own
    cuts, the piece of it (from 0; 0 for an uncut chip).
    """

    source: str
    row_above: int = 0
    chip: int = 0
    piece: int = 0

    @property
    def source_key(self) -> Tuple[str, int]:
        return resolve_source_key(self.source, self.row_above)

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "row_above": self.row_above, "chip": self.chip, "piece": self.piece}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChipRef":
        source, row_above = _checked_source(data)
        piece = int(data.get("piece", 0))
        if piece < 0:
            raise ValueError(f"A chip has no piece {piece}.")
        return cls(source, row_above, int(data.get("chip", 0)), piece)


@dataclass(frozen=True)
class MetadataField:
    """
    A metadata field and the chip it is taken from. `value` says whether the
    field is the whole chip or the number in it (FIELD_VALUES). A number's field
    is in `unit`, and the text around the number must be `text_before` and
    `text_after` in every file, or the file does not fit. `kind` overrides the
    field kind detected from the values; a number is a float.
    """

    field: str
    chip: ChipRef
    value: str = FIELD_VALUE_CHIP
    unit: str = ""
    text_before: str = ""
    text_after: str = ""
    kind: str = ""

    @property
    def is_number(self) -> bool:
        return self.value == FIELD_VALUE_NUMBER

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "chip": self.chip.to_dict(), "value": self.value, "unit": self.unit,
                "text_before": self.text_before, "text_after": self.text_after, "kind": self.kind}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetadataField":
        field = str(data.get("field", "")).strip()
        if not field:
            raise ValueError("A metadata field needs a name.")
        value, kind = data.get("value", FIELD_VALUE_CHIP), data.get("kind", "")
        if value not in FIELD_VALUES:
            raise ValueError(f"Unknown field value {value!r}; expected one of {FIELD_VALUES}.")
        if kind and kind not in FIELD_KINDS:
            raise ValueError(f"Unknown field kind {kind!r}; expected one of {FIELD_KINDS}.")
        number = value == FIELD_VALUE_NUMBER
        return cls(field, ChipRef.from_dict(data["chip"]), value, str(data.get("unit", "")) if number else "",
                   str(data.get("text_before", "")) if number else "",
                   str(data.get("text_after", "")) if number else "", kind)
