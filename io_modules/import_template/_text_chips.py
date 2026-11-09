"""
The chips of the texts around a channel, and what the roles of a
Import template make of them (CONTEXT.md "Import template").

A text is split at every delimiter character into chips (blank ones left out,
each stripped); a chip with own cuts becomes its pieces, which are ordinary
chips addressed (source, chip, piece). Every chip keeps where it is in the
text, so adjacent name chips keep the text between them. A cut that does not
fit, a role whose chip is missing, an axis that is no X/Y/Z, an order with no
number and a field whose number has other text around it are why the channel
does not fit -- a misfit, never a guess.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.import_template import (
    CUT_AFTER_CHARACTERS, CUT_AFTER_TEXT, CUT_LETTERS_DIGITS, CUT_OUT, DATA_KIND_ORDER_CUT,
    SOURCE_FILE_NAME, SOURCE_FOLDER, SOURCE_HEADER, SOURCE_SHEET, ChipCut, ChipRef, ImportTemplate, MetadataField,
    TextSource,
)
from io_modules.import_template._metadata import _delimiter_pattern

# What joins the name chips of different texts, and the axis to the name.
NAME_JOIN = ":"

_AXIS_RE = re.compile(r"^[XYZ]$")
# The first number of a chip; a sign only where it is not a hyphen after a letter or digit ("A-70").
_CHIP_NUMBER_RE = re.compile(r"(?:(?<![^\W_])[+-])?\d+(?:[.,]\d+)?")
_RATE_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")

Span = Tuple[int, int]
SourceKey = Tuple[str, int]


def resolve_text_source_label(source) -> str:
    """Where a text source's text is, as a sentence names it (a TextSource or ChipRef)."""
    if source.source == SOURCE_HEADER:
        if source.row_above == 0:
            return "the heading row's header"
        return f"the header {source.row_above} row{'s' if source.row_above > 1 else ''} above the heading row"
    return {SOURCE_SHEET: "the sheet name", SOURCE_FILE_NAME: "the file name", SOURCE_FOLDER: "the folder"}[source.source]


def _stripped(text: str, start: int, end: int) -> Optional[Span]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def build_chip_spans(text: str, delimiters: str) -> Tuple[Span, ...]:
    """Where the chips of a text are: between the delimiters, stripped, blanks left out."""
    cuts = [match.span() for match in re.finditer(_delimiter_pattern(delimiters), text)] if delimiters else []
    bounds = [0] + [edge for span in cuts for edge in span] + [len(text)]
    spans = (_stripped(text, start, end) for start, end in zip(bounds[::2], bounds[1::2]))
    return tuple(span for span in spans if span is not None)


def _letter_digit_boundaries(text: str) -> List[int]:
    return [at for at in range(1, len(text))
            if not text[at - 1].isspace() and not text[at].isspace() and text[at - 1].isdigit() != text[at].isdigit()]


def _cut_points(text: str, cut: ChipCut) -> Tuple[List[int], Optional[Span], str]:
    """The points one cut splits a chip at, the span it removes, and why it does not fit (blank when it does)."""
    if cut.kind == CUT_LETTERS_DIGITS:
        found = _letter_digit_boundaries(text)
        return found, None, "" if found else "has no boundary between letters and digits"
    if cut.kind in (CUT_AFTER_TEXT, CUT_OUT):
        at = text.find(cut.text)
        if at < 0:
            return [], None, f"has no text '{cut.text}'"
        if cut.kind == CUT_AFTER_TEXT:
            return [at + len(cut.text)], None, ""
        return [at, at + len(cut.text)], (at, at + len(cut.text)), ""
    if len(text) <= cut.count:
        return [], None, f"is shorter than {cut.count + 1} characters"
    return [cut.count if cut.kind == CUT_AFTER_CHARACTERS else len(text) - cut.count], None, ""


def _cut_out_spans(text: str, cuts: Sequence[ChipCut]) -> Tuple[Tuple[Span, ...], Tuple[Span, ...], str]:
    """The pieces of a chip, the spans its cut_out cuts remove, and why a cut does not fit (blank when all do)."""
    points, removed = {0, len(text)}, []
    for cut in cuts:
        found, cut_out, problem = _cut_points(text, cut)
        if problem:
            return (), (), problem
        points.update(found)
        if cut_out is not None:
            removed.append(cut_out)
    ordered = sorted(points)
    spans = (_stripped(text, start, end) for start, end in zip(ordered, ordered[1:])
             if not any(first <= start and end <= last for first, last in removed))
    return tuple(span for span in spans if span is not None), tuple(removed), ""


def build_cut_spans(text: str, cuts: Sequence[ChipCut]) -> Tuple[Tuple[Span, ...], str]:
    """
    The pieces of one chip after its own cuts, as spans in the chip, and why a
    cut does not fit the chip (blank when every one does; then no pieces).
    """
    pieces, _, problem = _cut_out_spans(text, cuts)
    return pieces, problem


def _resolve_position(position: int, count: int) -> Optional[int]:
    index = position if position >= 0 else count + position
    return index if 0 <= index < count else None


@dataclass(frozen=True)
class TextChip:
    """One chip of a text: its address (chip, piece) and where it is in the text."""

    chip: int
    piece: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class TextChips:
    """
    The chips of one text, how many delimiter chips it has, why an own cut does
    not fit (blank when all do), and the spans of the text cut_out cuts removed.
    """

    text: str
    chips: Tuple[TextChip, ...]
    chip_count: int
    problem: str = ""
    removed: Tuple[Span, ...] = ()

    def is_joined(self, first: int, second: int) -> bool:
        """Whether chip `second` directly follows chip `first`, with no cut-out text between them."""
        if second != first + 1:
            return False
        gap = (self.chips[first].end, self.chips[second].start)
        return not any(gap[0] <= start and end <= gap[1] for start, end in self.removed)

    def resolve_index(self, ref: ChipRef) -> Optional[int]:
        """Where the chip a ref takes is in `chips`, None when the text has no such chip."""
        chip = _resolve_position(ref.chip, self.chip_count)
        return next((number for number, found in enumerate(self.chips)
                     if found.chip == chip and found.piece == ref.piece), None)


def build_text_chips(text: str, source: TextSource) -> TextChips:
    """The chips of a text by a source's delimiters and own cuts."""
    spans = build_chip_spans(text, source.delimiters)
    cuts_by_chip = {}
    for chip_cuts in source.cut_chips:
        index = _resolve_position(chip_cuts.chip, len(spans))
        if index is not None:
            cuts_by_chip[index] = chip_cuts.cuts
    chips: List[TextChip] = []
    removed: List[Span] = []
    for chip, (start, end) in enumerate(spans):
        if chip not in cuts_by_chip:
            chips.append(TextChip(chip, 0, start, end, text[start:end]))
            continue
        pieces, cut_out, problem = _cut_out_spans(text[start:end], cuts_by_chip[chip])
        removed.extend((start + first, start + last) for first, last in cut_out)
        if problem:
            return TextChips(text, (), len(spans),
                             f"chip '{text[start:end]}' of {resolve_text_source_label(source)} {problem}")
        chips.extend(TextChip(chip, piece, start + first, start + last, text[start + first:start + last])
                     for piece, (first, last) in enumerate(pieces))
    return TextChips(text, tuple(chips), len(spans), removed=tuple(removed))


def resolve_axis_text(chip: str) -> str:
    """The axis a chip states, as the name ends with it: unsigned and upper case ("+x" -> "X")."""
    return chip.lstrip("+-").strip().upper()


def resolve_chip_number(text: str) -> Optional[Tuple[float, str, str]]:
    """(65.0, "TEST", "NmA") of "TEST65NmA": the chip's first number and the text before and after it; None without one."""
    match = _CHIP_NUMBER_RE.search(text)
    if match is None:
        return None
    return float(match.group().replace(",", ".")), text[:match.start()], text[match.end():]


def resolve_rate_hz(text: str) -> Optional[float]:
    """The sample rate in Hz a text states ("Sample rate: 25.6 kHz" -> 25600.0), None when it states no number."""
    match = _RATE_RE.search(text if "." in text else text.replace(",", "."))
    if match is None:
        return None
    return float(match.group()) * (1000.0 if "khz" in text.lower() else 1.0)


@dataclass(frozen=True)
class ChipRoles:
    """What a template's roles make of one channel's texts, and why they do not fit (blank when they do)."""

    name: str = ""
    order: Optional[float] = None
    sample_rate_text: str = ""
    metadata: Tuple[Tuple[str, Any], ...] = ()
    problem: str = ""


class _Misfit(Exception):
    pass


def resolve_chip_label(ref: ChipRef) -> str:
    """Which chip of its text a ref takes, as a sentence names it: "chip 2", "chip 1 from the end, piece 2"."""
    position = f"{ref.chip + 1}" if ref.chip >= 0 else f"{-ref.chip} from the end"
    return f"chip {position}" + (f", piece {ref.piece + 1}" if ref.piece else "")


def _chip_of(chips: Mapping[SourceKey, TextChips], ref: ChipRef) -> Tuple[TextChips, int]:
    text_chips = chips[ref.source_key]
    index = text_chips.resolve_index(ref)
    if index is None:
        raise _Misfit(f"{resolve_text_source_label(ref)} '{text_chips.text}' has no {resolve_chip_label(ref)}")
    return text_chips, index


def _resolve_chip_name(chips: Mapping[SourceKey, TextChips], refs: Sequence[ChipRef]) -> str:
    """
    The channel name of these name chips, in order: adjacent chips of one text
    keep the text between them (unless a cut removed it), the others are joined by ":". Raises _Misfit
    for a missing chip.
    """
    parts: List[List[Any]] = []        # [source key, index of the last chip, start, end]
    for ref in refs:
        text_chips, index = _chip_of(chips, ref)
        chip = text_chips.chips[index]
        last = parts[-1] if parts else None
        if last is not None and last[0] == ref.source_key and text_chips.is_joined(last[1], index):
            last[1], last[3] = index, chip.end
        else:
            parts.append([ref.source_key, index, chip.start, chip.end])
    return NAME_JOIN.join(chips[key].text[start:end] for key, _, start, end in parts)


def _field_value(chips: Mapping[SourceKey, TextChips], field: MetadataField) -> Any:
    text_chips, index = _chip_of(chips, field.chip)
    text = text_chips.chips[index].text
    if not field.is_number:
        return text
    where = f"chip '{text}' of {resolve_text_source_label(field.chip)}"
    number = resolve_chip_number(text)
    if number is None:
        raise _Misfit(f"{where} has no number for the field '{field.field}'")
    value, before, after = number
    if (before, after) != (field.text_before, field.text_after):
        raise _Misfit(f"{where} has '{before}' and '{after}' around its number; the field '{field.field}' "
                      f"expects '{field.text_before}' and '{field.text_after}'")
    return value


def build_chip_roles(template: ImportTemplate, texts: Mapping[SourceKey, str]) -> ChipRoles:
    """
    The name (with the axis appended as ":X", unsigned and upper case), order,
    sample-rate text and metadata fields one channel's texts give by the
    template's roles. `texts` holds the text of every source of the template.
    """
    chips: Dict[SourceKey, TextChips] = {source.key: build_text_chips(texts[source.key], source)
                                         for source in template.texts}
    problem = next((text_chips.problem for text_chips in chips.values() if text_chips.problem), "")
    if problem:
        return ChipRoles(problem=problem)
    try:
        name = _resolve_chip_name(chips, template.channel_name)
        if template.axis is not None:
            text_chips, index = _chip_of(chips, template.axis)
            if any(ref.source_key == template.axis.source_key and text_chips.resolve_index(ref) == index
                   for ref in template.channel_name):
                raise _Misfit("the axis chip is also a part of the name, so the axis would be in the name twice")
            axis = resolve_axis_text(text_chips.chips[index].text)
            if not _AXIS_RE.match(axis):
                raise _Misfit(f"'{text_chips.chips[index].text}' is not an axis X, Y or Z")
            name = f"{name}{NAME_JOIN}{axis}"
        order: Optional[float] = None
        if template.data_kind == DATA_KIND_ORDER_CUT:       # only an order cut has an order
            if isinstance(template.order, ChipRef):
                text_chips, index = _chip_of(chips, template.order)
                number = resolve_chip_number(text_chips.chips[index].text)
                if number is None:
                    raise _Misfit(f"no order in the chip '{text_chips.chips[index].text}'")
                order = number[0]
            else:
                order = float(template.order)
        rate_text = ""
        if isinstance(template.sample_rate, ChipRef):
            text_chips, index = _chip_of(chips, template.sample_rate)
            rate_text = text_chips.chips[index].text
        metadata = tuple((field.field, _field_value(chips, field)) for field in template.metadata_fields)
    except _Misfit as misfit:
        return ChipRoles(problem=str(misfit))
    return ChipRoles(name=name, order=order, sample_rate_text=rate_text, metadata=metadata)
