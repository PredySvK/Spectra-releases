"""
Step 3 of the import wizard (#1031): the chips of every channel's texts on
all the samples, how each chip changes across them, the roles the user gives
the chips, the first guess of those roles, and what the roles make of one
channel.

A text source is a header row (counted up from the heading row), the sheet
name, the file name or the folder (core.import_template.TextSource). A header
text is split at ",:;\\-" -- an underscore stays, "Mount_A(Shaft)" is one chip
-- and a name text (sheet, file, folder) also at "_" and a space. A chip is
addressed by a ChipRef, so a role names the same chip in every channel.

A text whose chip count differs between the channels (a chip more in a few
headers) is counted from its end where that reads better
(`resolve_chip_anchor`): a chip given a role is taken from the start or from
the end, whichever is in every channel, reads as the role (an order, an axis, a
rate) and gives the fewest distinct values -- the odd channels then give values
the others have. A text with one chip count, and a text with own cuts, is
counted from the start.

Pure: plain values in, plain values out. `build_sample_chips` runs on a
worker with the preview; the rest is cheap enough for the GUI thread.
"""

import re
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from core.import_template import (
    DATA_KIND_ORDER_CUT, FIELD_VALUE_NUMBER, SOURCE_FILE_NAME, SOURCE_FOLDER, SOURCE_HEADER, SOURCE_SHEET, ROLE_AXIS,
    ROLE_FIELDS, ROLE_NAME, ROLE_ORDER, ROLE_SAMPLE_RATE, ChipRef, ImportTemplate, MetadataField, TextSource,
)
from io_modules.import_template import (
    ChipRoles, TextChips, build_chip_roles, build_text_chips, resolve_chip_number, resolve_text_source_label,
)

SourceKey = Tuple[str, int]

HEADER_DELIMITERS = ",:;\\-"
NAME_TEXT_DELIMITERS = "_,;- "

# How a chip changes across every channel of every sample.
CHIP_IN_COLUMNS = "in_columns"
CHIP_BETWEEN_SHEETS = "between_sheets"
CHIP_BETWEEN_FILES = "between_files"
CHIP_SAME = "same"
CHIP_MISSING = "missing"

# The role kinds of step 3, in the order a chip with several shows them.
CHIP_ROLE_KINDS = (ROLE_NAME, ROLE_AXIS, ROLE_ORDER, ROLE_SAMPLE_RATE, ROLE_FIELDS)

_ORDER_LIKE_RE = re.compile(r"^(order\s*|h)\d+(\.\d+)?$", re.IGNORECASE)
_AXIS_LIKE_RE = re.compile(r"^[+-]?[XYZ]$", re.IGNORECASE)
_RATE_LIKE_RE = re.compile(r"\d.*hz", re.IGNORECASE)
_KEY_VALUE_RE = re.compile(r"^\s*([^=]*?\S)\s*=\s*\S")        # "Damping = 0.04": the key before the "="
_KEY_BEFORE_NUMBER_RE = re.compile(r"^\s*([^=]*?\S)\s*=\s*$")


def build_chip_source(source: str, row_above: int = 0) -> TextSource:
    """A text source split the way step 3 splits it (see the module docstring)."""
    delimiters = HEADER_DELIMITERS if source == SOURCE_HEADER else NAME_TEXT_DELIMITERS
    return TextSource(source, row_above if source == SOURCE_HEADER else 0, delimiters)


@dataclass(frozen=True)
class ChannelTexts:
    """
    One channel of a sample and the text of every source it has (a header row
    above the top of its sheet is absent). `header_column` is the column its
    header cells are in (a pair's X column, else the amplitude column).
    """

    path: str
    sheet: str
    heading_row: int
    header_column: int
    x_column: int
    y_column: int
    texts: Tuple[Tuple[SourceKey, str], ...]

    def resolve_text(self, key: SourceKey) -> Optional[str]:
        return next((text for found, text in self.texts if found == key), None)


@dataclass(frozen=True)
class ChipChange:
    """How one chip changes across the channels (CHIP_*), and its distinct values in channel order."""

    ref: ChipRef
    change: str
    values: Tuple[str, ...]


_NO_CHIPS = TextChips("", (), 0)


def _is_count_varying(counts: Sequence[int]) -> bool:
    """Whether the texts with chips have different chip counts (a missing or blank text says nothing)."""
    return len({count for count in counts if count > 0}) > 1


@dataclass(frozen=True)
class SampleChips:
    """
    The text sources in text order (header rows top down, then sheet, file,
    folder), every channel, every chip's change -- counted from the end too in
    a text whose chip count varies -- and every source's chip count in each
    channel (-1: the channel has no such text).
    """

    sources: Tuple[TextSource, ...] = ()
    channels: Tuple[ChannelTexts, ...] = ()
    changes: Tuple[ChipChange, ...] = ()
    chip_counts: Tuple[Tuple[SourceKey, Tuple[int, ...]], ...] = ()

    def resolve_source(self, key: SourceKey) -> Optional[TextSource]:
        return next((source for source in self.sources if source.key == key), None)

    def resolve_chips(self, channel: int, key: SourceKey) -> TextChips:
        """The chips of one channel's text of a source; none when the channel has no such text."""
        source = self.resolve_source(key)
        text = self.channels[channel].resolve_text(key) if 0 <= channel < len(self.channels) else None
        return _NO_CHIPS if source is None or text is None else build_text_chips(text, source)

    def resolve_change(self, ref: ChipRef) -> Optional[ChipChange]:
        return next((change for change in self.changes if change.ref == ref), None)

    def _counts(self, key: SourceKey) -> Tuple[int, ...]:
        return next((counts for found, counts in self.chip_counts if found == key), ())

    def resolve_chip_count(self, key: SourceKey, channel: int) -> int:
        """How many delimiter chips one channel's text of a source has, -1 when it has no such text."""
        counts = self._counts(key)
        return counts[channel] if 0 <= channel < len(counts) else -1

    def resolve_usual_chip_count(self, key: SourceKey) -> int:
        """The chip count most channels' text of a source has (the larger one on a tie; blank texts left out)."""
        counts = [count for count in self._counts(key) if count > 0]
        return max(set(counts), key=lambda count: (counts.count(count), count)) if counts else 0

    def is_counted_from_either_end(self, key: SourceKey) -> bool:
        """
        Whether a chip of the source can be counted from the end: its chip count varies between the
        channels whose text has chips, and it has no own cuts.
        """
        source = self.resolve_source(key)
        return source is not None and not source.cut_chips and _is_count_varying(self._counts(key))

    def resolve_position(self, ref: ChipRef, channel: int) -> Optional[int]:
        """The delimiter chip, counted from the start, that a ref takes in one channel's text; None when it has none."""
        count = self.resolve_chip_count(ref.source_key, channel)
        index = ref.chip if ref.chip >= 0 else count + ref.chip
        return index if 0 <= index < count else None

    def is_same_chip(self, ref: ChipRef, other: ChipRef, channel: int) -> bool:
        """Whether two refs take the same chip of one channel's text (one may count from the end)."""
        if ref == other:
            return True
        if ref.source_key != other.source_key or ref.piece != other.piece:
            return False
        position = self.resolve_position(ref, channel)
        return position is not None and position == self.resolve_position(other, channel)

    def resolve_flipped(self, ref: ChipRef, channel: int) -> Optional[ChipRef]:
        """The same chip of one channel's text counted from the other end; None when the channel has no such chip."""
        position = self.resolve_position(ref, channel)
        if position is None:
            return None
        chip = position - self.resolve_chip_count(ref.source_key, channel) if ref.chip >= 0 else position
        return ChipRef(ref.source, ref.row_above, chip, ref.piece)

    def resolve_text_position(self, ref: ChipRef) -> Tuple[int, int, int]:
        """Where a chip is in the texts read top down: its source, then its chip (in the usual chip count) and piece."""
        keys = [source.key for source in self.sources]
        index = keys.index(ref.source_key) if ref.source_key in keys else len(keys)
        chip = ref.chip if ref.chip >= 0 else self.resolve_usual_chip_count(ref.source_key) + ref.chip
        return index, chip, ref.piece


def _ref(key: SourceKey, chip: int, piece: int) -> ChipRef:
    return ChipRef(key[0], key[1], chip, piece)


def _change_of(values: Sequence[Tuple[ChannelTexts, Optional[str]]]) -> str:
    if any(value is None for _, value in values):
        return CHIP_MISSING
    if len({value for _, value in values}) == 1:
        return CHIP_SAME
    by_sheet: Dict[Tuple[str, str], Set[str]] = {}
    by_file: Dict[str, Set[str]] = {}
    for channel, value in values:
        by_sheet.setdefault((channel.path, channel.sheet), set()).add(value)
        by_file.setdefault(channel.path, set()).add(value)
    if any(len(found) > 1 for found in by_sheet.values()):
        return CHIP_IN_COLUMNS
    if any(len(found) > 1 for found in by_file.values()):
        return CHIP_BETWEEN_SHEETS
    return CHIP_BETWEEN_FILES


def _chip_change(ref: ChipRef, channels: Sequence[ChannelTexts], split: Sequence[TextChips]) -> ChipChange:
    values = []
    for channel, chips in zip(channels, split):
        index = chips.resolve_index(ref)
        values.append((channel, chips.chips[index].text if index is not None else None))
    return ChipChange(ref, _change_of(values), tuple(dict.fromkeys(value for _, value in values if value is not None)))


def build_sample_chips(channels: Sequence[ChannelTexts], sources: Sequence[TextSource]) -> SampleChips:
    """The chips of every channel's texts and how each chip changes across all of them (a worker)."""
    changes: List[ChipChange] = []
    counts: List[Tuple[SourceKey, Tuple[int, ...]]] = []
    for source in sources:
        texts = [channel.resolve_text(source.key) for channel in channels]
        split = [build_text_chips(text, source) if text is not None else _NO_CHIPS for text in texts]
        found = tuple(chips.chip_count if text is not None else -1 for text, chips in zip(texts, split))
        counts.append((source.key, found))
        positions = sorted({(chip.chip, chip.piece) for chips in split for chip in chips.chips})
        changes.extend(_chip_change(_ref(source.key, chip, piece), channels, split) for chip, piece in positions)
        if not source.cut_chips and _is_count_varying(found):
            changes.extend(_chip_change(_ref(source.key, -back, 0), channels, split)
                           for back in range(1, max(found) + 1))
    return SampleChips(tuple(sources), tuple(channels), tuple(changes), tuple(counts))


def _is_present(change: Optional[ChipChange]) -> bool:
    return change is not None and change.change != CHIP_MISSING and bool(change.values)


def _reads_as(kind: str):
    """What every value of a chip with this role must look like; None when any text will do."""
    pattern = {ROLE_ORDER: _ORDER_LIKE_RE.match, ROLE_AXIS: _AXIS_LIKE_RE.match,
               ROLE_SAMPLE_RATE: _RATE_LIKE_RE.search}.get(kind)
    return (lambda values: all(pattern(value) for value in values)) if pattern is not None else None


def _pick_anchor(start: ChipRef, end: ChipRef, chips: SampleChips, fits) -> ChipRef:
    """
    From the start or from the end: the one in every channel that reads as
    the role (`fits`), then the one with fewer distinct values; from the
    start on a tie or when neither fits.
    """
    fitting = []
    for ref in (start, end):
        change = chips.resolve_change(ref)
        if _is_present(change) and (fits is None or fits(change.values)):
            fitting.append((len(change.values), ref.chip < 0, ref))
    return min(fitting)[2] if fitting else start


def resolve_chip_anchor(chips: SampleChips, kind: str, ref: ChipRef, channel: int) -> ChipRef:
    """
    The ref a role takes for the chip `ref` names in one channel's text:
    counted from the start or from the end (see the module docstring). A text
    with one chip count, a piece and an own cut keep the ref as it is.
    """
    if ref.piece or not chips.is_counted_from_either_end(ref.source_key):
        return ref
    position = chips.resolve_position(ref, channel)
    if position is None:
        return ref
    count = chips.resolve_chip_count(ref.source_key, channel)
    start, end = _ref(ref.source_key, position, 0), _ref(ref.source_key, position - count, 0)
    return _pick_anchor(start, end, chips, _reads_as(kind))


def resolve_chip_sources(heading_rows: int, with_sheet: bool) -> Tuple[TextSource, ...]:
    """The text sources step 3 offers: `heading_rows` header rows (the heading row too) top down, the sheet, file, folder."""
    rows = tuple(build_chip_source(SOURCE_HEADER, row_above) for row_above in range(heading_rows - 1, -1, -1))
    sheet = (build_chip_source(SOURCE_SHEET),) if with_sheet else ()
    return rows + sheet + (build_chip_source(SOURCE_FILE_NAME), build_chip_source(SOURCE_FOLDER))


@dataclass(frozen=True)
class SampleRoles:
    """
    The roles of step 3: the name chips in name order, the axis, the order
    chip -- or one order for every channel, `fixed_order` (0: none) -- and
    the sample rate chip, the metadata fields (each takes one chip). One chip
    may hold several roles.
    """

    name: Tuple[ChipRef, ...] = ()
    axis: Optional[ChipRef] = None
    order: Optional[ChipRef] = None
    fixed_order: float = 0.0
    sample_rate: Optional[ChipRef] = None
    fields: Tuple[MetadataField, ...] = ()

    def resolve_refs(self, kind: str) -> Tuple[ChipRef, ...]:
        if kind == ROLE_NAME:
            return self.name
        if kind == ROLE_FIELDS:
            return tuple(dict.fromkeys(field.chip for field in self.fields))
        found = {ROLE_AXIS: self.axis, ROLE_ORDER: self.order, ROLE_SAMPLE_RATE: self.sample_rate}[kind]
        return (found,) if found is not None else ()

    def resolve_kinds(self, ref: ChipRef) -> Tuple[str, ...]:
        """The roles a chip holds, in CHIP_ROLE_KINDS order."""
        return tuple(kind for kind in CHIP_ROLE_KINDS if ref in self.resolve_refs(kind))

    def with_role(self, kind: str, ref: ChipRef, chips: SampleChips) -> "SampleRoles":
        """This chip in this role: a new name chip goes where it is in the texts, the axis, order and rate are replaced."""
        if kind == ROLE_FIELDS:
            raise ValueError("A metadata field needs its name: give it with with_field.")
        if kind != ROLE_NAME:
            return replace(self, **{kind: ref})
        if ref in self.name:
            return self
        mine = chips.resolve_text_position(ref)
        at = next((number for number, other in enumerate(self.name) if chips.resolve_text_position(other) > mine),
                  len(self.name))
        return replace(self, name=self.name[:at] + (ref,) + self.name[at:])

    def without_role(self, kind: str, ref: ChipRef) -> "SampleRoles":
        """This one role taken off the chip (a metadata role: every field of it); its other roles stay."""
        if kind == ROLE_FIELDS:
            return replace(self, fields=tuple(field for field in self.fields if field.chip != ref))
        if kind == ROLE_NAME:
            return replace(self, name=tuple(other for other in self.name if other != ref))
        return replace(self, **{kind: None}) if ref in self.resolve_refs(kind) else self

    def without_chip(self, key: SourceKey, chip: int, usual_count: int = 0) -> "SampleRoles":
        """
        Every role of every piece of delimiter chip `chip` (from the start) of a source taken off; a role
        counting from the end takes it when it is that chip in the text's usual chip count.
        """
        def mine(ref: Optional[ChipRef]) -> bool:
            return (ref is not None and ref.source_key == key
                    and (ref.chip if ref.chip >= 0 else usual_count + ref.chip) == chip)

        return replace(
            self, name=tuple(ref for ref in self.name if not mine(ref)),
            axis=None if mine(self.axis) else self.axis, order=None if mine(self.order) else self.order,
            sample_rate=None if mine(self.sample_rate) else self.sample_rate,
            fields=tuple(field for field in self.fields if not mine(field.chip)))

    def with_field(self, field: MetadataField) -> "SampleRoles":
        """The field added, or replacing the one of the same name (the field kind and unit are edited so)."""
        others = tuple(other for other in self.fields if other.field.casefold() != field.field.casefold())
        return replace(self, fields=others + (field,))

    def without_field(self, name: str) -> "SampleRoles":
        return replace(self, fields=tuple(field for field in self.fields if field.field.casefold() != name.casefold()))

    def with_ref_replaced(self, kind: str, ref: ChipRef, new: ChipRef) -> "SampleRoles":
        """The role `kind` takes `new` where it took `ref` (a name chip keeps its place, a field its settings)."""
        if kind == ROLE_NAME:
            return replace(self, name=tuple(new if other == ref else other for other in self.name))
        if kind == ROLE_FIELDS:
            return replace(self, fields=tuple(replace(field, chip=new) if field.chip == ref else field
                                              for field in self.fields))
        return replace(self, **{kind: new}) if ref in self.resolve_refs(kind) else self

    def with_name_moved(self, index: int, to: int) -> "SampleRoles":
        """The name chip `index` moved to the place `to` of the name."""
        if not (0 <= index < len(self.name) and 0 <= to < len(self.name)) or index == to:
            return self
        name = list(self.name)
        name.insert(to, name.pop(index))
        return replace(self, name=tuple(name))

    @property
    def is_axis_in_name(self) -> bool:
        return self.axis is not None and self.axis in self.name


def _guessed_anchor(chips: SampleChips, start: ChipRef, end: ChipRef) -> ChipRef:
    """The end a chip of the usual count is counted from before its role is known: the one an order or rate reads in."""
    for fits in (_reads_as(ROLE_ORDER), _reads_as(ROLE_SAMPLE_RATE)):
        fitting = [ref for ref in (start, end) if _is_present(chips.resolve_change(ref))
                   and fits(chips.resolve_change(ref).values)]
        if len(fitting) == 1:
            return fitting[0]
    return _pick_anchor(start, end, chips, None)


def _resolve_guessed_changes(chips: SampleChips) -> List[ChipChange]:
    """The chips the first guess looks at, in text order (see resolve_role_suggestion)."""
    guessed: List[ChipChange] = []
    for source in chips.sources:
        key = source.key
        if not chips.is_counted_from_either_end(key):
            guessed.extend(change for change in chips.changes if change.ref.source_key == key and change.ref.chip >= 0)
            continue
        usual = chips.resolve_usual_chip_count(key)
        for position in range(usual):
            change = chips.resolve_change(_guessed_anchor(chips, _ref(key, position, 0), _ref(key, position - usual, 0)))
            if change is not None:
                guessed.append(change)
    return guessed


def resolve_role_suggestion(chips: SampleChips, with_order: bool, with_rate: bool) -> SampleRoles:
    """
    The first guess of the roles from how the chips change: a chip that
    reads like an order ("Order 22", "H1") is the order (the first one in the
    texts), one that reads like a sample rate is the rate, one that changes
    in the columns is the axis when it is X/Y/Z and else a part of the name,
    and a "key = number" chip is the field of that key. The user corrects it.
    A text whose chip count varies offers the chips of its usual count, each
    counted from the start or from the end as `resolve_chip_anchor` would.
    """
    roles = SampleRoles()
    for change in _resolve_guessed_changes(chips):
        values = change.values
        if not values:
            continue
        if all(_ORDER_LIKE_RE.match(value) for value in values):
            if with_order and roles.order is None:
                roles = replace(roles, order=change.ref)
        elif with_rate and roles.sample_rate is None and all(_RATE_LIKE_RE.search(value) for value in values):
            roles = replace(roles, sample_rate=change.ref)
        elif all(_KEY_VALUE_RE.match(value) for value in values):
            field = _guess_key_field(chips, change.ref, with_order)
            if field is not None:
                roles = roles.with_field(field)
        elif change.change == CHIP_IN_COLUMNS:
            if roles.axis is None and all(_AXIS_LIKE_RE.match(value) for value in values):
                roles = replace(roles, axis=change.ref)
            else:
                roles = replace(roles, name=roles.name + (change.ref,))
    return roles


def resolve_channel_roles(template: ImportTemplate, chips: SampleChips, channel: int) -> ChipRoles:
    """What the template's roles make of one channel of the chips (name with the axis, order), as the reader would."""
    texts: Dict[SourceKey, str] = {}
    for source in template.texts:
        text = chips.channels[channel].resolve_text(source.key) if 0 <= channel < len(chips.channels) else None
        if text is None:
            return ChipRoles(problem=f"the channel has no {resolve_text_source_label(source)}")
        texts[source.key] = text
    return build_chip_roles(template, texts)


def resolve_role_ref(chips: SampleChips, roles: SampleRoles, kind: str, channel: int,
                     ref: ChipRef) -> Optional[ChipRef]:
    """The ref by which the role `kind` takes the chip `ref` names in one channel's text; None when it does not."""
    return next((own for own in roles.resolve_refs(kind) if chips.is_same_chip(own, ref, channel)), None)


def resolve_chip_kinds(chips: SampleChips, roles: SampleRoles, channel: int, ref: ChipRef) -> Tuple[str, ...]:
    """The roles the chip `ref` names in one channel's text holds, in CHIP_ROLE_KINDS order (counted from either end)."""
    return tuple(kind for kind in CHIP_ROLE_KINDS if resolve_role_ref(chips, roles, kind, channel, ref) is not None)


def resolve_chip_marks(chips: SampleChips, roles: SampleRoles, channel: int,
                       key: SourceKey) -> Tuple[Tuple[int, int, Tuple[str, ...]], ...]:
    """(start, end, role kinds) of the chips with a role in one channel's text of a source."""
    marks = []
    for found in chips.resolve_chips(channel, key).chips:
        kinds = resolve_chip_kinds(chips, roles, channel, _ref(key, found.chip, found.piece))
        if kinds:
            marks.append((found.start, found.end, kinds))
    return tuple(marks)


def resolve_name_joins(chips: SampleChips, roles: SampleRoles, channel: int) -> Tuple[bool, ...]:
    """For every name chip after the first, whether it directly follows the one before in its text (the text between stays)."""
    joins = []
    for first, second in zip(roles.name, roles.name[1:]):
        joined = False
        if first.source_key == second.source_key:
            text_chips = chips.resolve_chips(channel, first.source_key)
            one, two = text_chips.resolve_index(first), text_chips.resolve_index(second)
            joined = one is not None and two is not None and text_chips.is_joined(one, two)
        joins.append(joined)
    return tuple(joins)


def resolve_chip_texts(roles: SampleRoles) -> Tuple[TextSource, ...]:
    """The text sources the roles take chips from, in text order: the template lists only those."""
    keys = {ref.source_key for kind in CHIP_ROLE_KINDS for ref in roles.resolve_refs(kind)}
    rank = {SOURCE_SHEET: 1, SOURCE_FILE_NAME: 2, SOURCE_FOLDER: 3}
    ordered = sorted(keys, key=lambda key: (rank.get(key[0], 0), -key[1]))
    return tuple(build_chip_source(source, row_above) for source, row_above in ordered)


def resolve_order_role(roles: SampleRoles, data_kind: str) -> Union[ChipRef, float]:
    """What the template's order is: the order chip, else the one order for all; 1.0 for no order cut."""
    if data_kind != DATA_KIND_ORDER_CUT:
        return 1.0
    return roles.order if roles.order is not None else roles.fixed_order


@dataclass(frozen=True)
class FieldOffer:
    """
    What the wizard offers for a metadata field taken from a chip: a name
    (the key of "key = value"), whether the field can be the number in the
    chip -- then the text around it and the unit made of the letters after it
    -- and the chip's values. `number_problem` says why the number is not offered.
    """

    values: Tuple[str, ...] = ()
    name: str = ""
    is_number: bool = False
    text_before: str = ""
    text_after: str = ""
    unit: str = ""
    number_problem: str = ""


def build_field_offer(chips: SampleChips, ref: ChipRef) -> FieldOffer:
    """The offer for a field taken from this chip, from its values across all the samples."""
    change = chips.resolve_change(ref)
    values = change.values if change is not None else ()
    if not values:
        return FieldOffer(number_problem="the chip has no text")
    found = [resolve_chip_number(value) for value in values]
    for value, number in zip(values, found):
        if number is None:
            return FieldOffer(values, number_problem=f"'{value}' has no number")
    around = {(before, after) for _, before, after in found}
    if len(around) > 1:
        return FieldOffer(values, number_problem="the text around the number differs between the samples")
    (before, after), = around
    key = _KEY_BEFORE_NUMBER_RE.match(before)
    return FieldOffer(values, key.group(1) if key else "", True, before, after, after.strip())


def build_metadata_field(name: str, ref: ChipRef, offer: FieldOffer, *, as_number: bool, unit: str = "",
                         kind: str = "") -> MetadataField:
    """The field `name` from a chip: the number in it (with the offer's surrounding text and `unit`) or the whole chip."""
    if as_number and offer.is_number:
        return MetadataField(name.strip(), ref, FIELD_VALUE_NUMBER, unit.strip(), offer.text_before,
                             offer.text_after, kind)
    return MetadataField(name.strip(), ref, kind=kind)


def _guess_key_field(chips: SampleChips, ref: ChipRef, with_order: bool) -> Optional[MetadataField]:
    """The field a "key = number" chip is, None when it holds no number or the key is the order of an order cut."""
    offer = build_field_offer(chips, ref)
    if not offer.is_number or not offer.name or (with_order and offer.name.casefold() == "order"):
        return None
    return build_metadata_field(offer.name, ref, offer, as_number=True)
