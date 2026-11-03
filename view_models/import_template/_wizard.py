"""
The import wizard's state: a sample workbook and the Import template being
built on it, one choice at a time.

Metadata choices are made on the sample's pieces: a new source has every piece
of its sample text dropped, and a piece is then made a field
(`assign_piece`) or dropped again. A choice the template cannot keep -- a
field fed from two sources, a key/value piece without a key, a split-unit
piece that is no number -- is refused with the reason and changes nothing.
"""

import dataclasses
import os
from typing import Iterable, List, Optional, Sequence

from core.import_template import (
    DATA_KIND_ORDER_CUT, DEFAULT_DELIMITERS, FIELD_KINDS, LAYOUT_SHARED_X, LAYOUT_SINGLE_CURVE, LAYOUT_XY_PAIRS, SHEETS_ALL, ImportTemplate, MetadataPiece,
    MetadataSource, TextPick,
)
from core.units import get_compatible_options
from io_modules.import_template import (
    TextFormat, Workbook, build_text_format, build_source_pieces, resolve_metadata_source_label,
    read_builtin_templates, resolve_cell_text, resolve_piece_index, resolve_read_sheets, resolve_number_unit,
)
from io_modules.number_pairs import read_number_pairs
from view_models.import_template._duplicates import (
    DuplicateGroup, build_template_keeping, resolve_kept_copies,
)
from view_models.import_template._preview import (
    PreviewSource, WizardPreview, build_metadata_sources, build_wizard_preview, resolve_sample_source_texts,
)

DEFAULT_TEMPLATE_NAME = "New template"
_SPEED_UNITS = frozenset({"rpm", "Hz", "rad/s"})
_GUESS_ROWS = 60


def _is_number(cell) -> bool:
    return bool(read_number_pairs([(cell, 0)]).pairs)


def _guess_heading(rows: Sequence[tuple]) -> Optional[int]:
    """The first row with text in its first cell and a number below it."""
    for index in range(min(len(rows) - 1, _GUESS_ROWS)):
        first, below = rows[index], rows[index + 1]
        if first and below and resolve_cell_text(first[0]) and not _is_number(first[0]) and _is_number(below[0]):
            return index
    return None


def _guess_layout(heading: tuple) -> str:
    cells = [resolve_cell_text(cell).lower() for cell in heading]
    if len(cells) >= 4 and cells[0] and cells[2] == cells[0]:
        return LAYOUT_XY_PAIRS
    if sum(1 for cell in cells[1:] if cell) >= 2:
        return LAYOUT_SHARED_X
    return LAYOUT_SINGLE_CURVE


def resolve_duplicate_field_problem(template: ImportTemplate) -> str:
    """
    Why a field of the template is fed from two pieces, blank when every field
    has one source. An order cut's order comes from its order role, so a field
    named "Order" would be a second source of it.
    """
    seen = {}
    for source in template.metadata:
        for rule in source.pieces:
            if rule.is_dropped:
                continue
            name = rule.field.strip().lower()
            if name == "order" and template.data_kind == DATA_KIND_ORDER_CUT:
                return (f"The order comes from the template's order, not from "
                        f"{resolve_metadata_source_label(source)}; a field has one source.")
            if name in seen:
                first, where = seen[name]
                return (f"The field '{first}' comes both from {where} and from "
                        f"{resolve_metadata_source_label(source)}; a field has one source.")
            seen[name] = (rule.field.strip(), resolve_metadata_source_label(source))
    return ""


def build_default_template(workbook: Workbook) -> ImportTemplate:
    """
    The wizard's first guess on a new sample: the first sheet of every file
    (sheet names differ from export to export), its heading row, column
    layout and channel name.
    """
    sheet = workbook.sheet_names[0] if workbook.sheet_names else ""
    rows = workbook.rows_of(sheet) or ()
    heading = _guess_heading(rows)
    anchor = resolve_cell_text(rows[heading][0]) if heading is not None else ""
    layout = _guess_layout(rows[heading]) if heading is not None else LAYOUT_SINGLE_CURVE
    # A pair's header column is its X column, whose heading cell names the speed, not the
    # channel: its name is guessed from the row above. Another layout's heading cell is the
    # channel's own, "Name (unit)".
    name = (TextPick(row_above=1) if layout == LAYOUT_XY_PAIRS and heading > 0
            else TextPick(row_above=0, before="("))
    extension = os.path.splitext(workbook.path)[1].lower() or ".xlsx"
    return ImportTemplate(
        name=DEFAULT_TEMPLATE_NAME, file_pattern=f"*{extension}",
        anchor_text=anchor, heading_row=0 if anchor else 1,
        layout=layout, sheet_rule=SHEETS_ALL,
        channel_name=(name,), order=1.0)


class ImportTemplateWizard:
    """
    The template being built on a sample, and which sheet the grid shows.

    Every choice goes through `change`; `preview()` reads the sample by the
    template as it stands, and `resolve_fit_problem` refuses one that does not
    read the sample. How the wizard ends is `WizardEnding`'s.
    """

    def __init__(self, workbook: Workbook, template: Optional[ImportTemplate] = None):
        # The sample the wizard was opened on, and the workbook the preview shows (`use_sample`).
        self.sample = self.workbook = workbook
        self.template = template or build_default_template(workbook)
        # The name of the template loaded for editing: Overwrite keeps it, Save as new leaves it.
        self.original_name = template.name if template is not None else ""
        read = [sheet for sheet in resolve_read_sheets(workbook.sheet_names, self.template)
                if sheet in workbook.sheet_names]
        names = workbook.sheet_names
        self.shown_sheet = read[0] if read else (names[0] if names else "")

    def change(self, **fields) -> None:
        """Makes choices: any ImportTemplate fields, by name."""
        self.template = dataclasses.replace(self.template, **fields)

    def show_sheet(self, sheet: str) -> None:
        self.shown_sheet = sheet

    def use_sample(self, workbook: Workbook) -> None:
        """Shows another sample file in the preview, to check the template fits it; the template is unchanged."""
        self.workbook = workbook
        read = [sheet for sheet in resolve_read_sheets(workbook.sheet_names, self.template)
                if sheet in workbook.sheet_names]
        names = workbook.sheet_names
        self.shown_sheet = read[0] if read else (names[0] if names else "")

    @property
    def detected_text_format(self) -> Optional[TextFormat]:
        """What the shown text sample suggests for its encoding, delimiter and decimal separator; None for a workbook."""
        return self.workbook.detected_text_format

    def resolve_text_format_to_read(self) -> Optional[TextFormat]:
        """
        The text format to read the shown sample again with, None when it was
        read with what the template says (an override, else the detected). The
        preview works on the sample in memory, so a changed override needs it
        read again (on a worker) and handed to `replace_shown_sample`.
        """
        used, detected = self.workbook.text_format, self.workbook.detected_text_format
        if used is None or detected is None:
            return None
        wanted = build_text_format(self.template)
        effective = TextFormat(wanted.encoding or detected.encoding, wanted.delimiter or detected.delimiter,
                               wanted.decimal or detected.decimal)
        return wanted if effective != used else None

    def replace_shown_sample(self, workbook: Workbook) -> None:
        """The shown sample read again, the same file with another text format; the template is unchanged."""
        if workbook.path == self.sample.path:
            self.sample = workbook
        self.workbook = workbook
        if self.shown_sheet not in workbook.sheet_names:
            self.shown_sheet = workbook.sheet_names[0] if workbook.sheet_names else ""

    def keep_duplicates(self, groups: Sequence[DuplicateGroup], *, picks=None, source_amplitude: str = "") -> None:
        """
        Writes the user's duplicate choice into the template: one copy kept of
        each group -- the one `picks` names (group number -> copy number), else
        the first with this Source amplitude -- the others left out. A group
        with no choice keeps all its copies. Decided on the first sample, the
        one the groups were found on.
        """
        self.template = build_template_keeping(
            self.template, self.sample, groups, resolve_kept_copies(groups, picks, source_amplitude))

    def preview(self) -> WizardPreview:
        return build_wizard_preview(self.workbook, self.template, self.shown_sheet)

    # ---- metadata ----------------------------------------------------------------

    def resolve_metadata_source(self, number: int) -> PreviewSource:
        """Source `number`'s text in the sample and its pieces with their rules -- quick, from the head of one sheet."""
        texts = resolve_sample_source_texts(self.workbook, self.template, self.shown_sheet)
        return build_metadata_sources(self.template, texts)[number]

    def _sample_pieces(self, number: int):
        text = resolve_sample_source_texts(self.workbook, self.template, self.shown_sheet)[number]
        return build_source_pieces(text, self.template.metadata[number].delimiters)

    def _all_dropped(self, number: int) -> tuple:
        """A drop rule for every sample piece -- none when the source drops pieces it does not name anyway."""
        if self.template.metadata[number].drop_unknown:
            return ()
        return tuple(MetadataPiece(piece.position) for piece in self._sample_pieces(number))

    def _replace_source(self, number: int, source: MetadataSource) -> None:
        sources = list(self.template.metadata)
        sources[number] = source
        self.change(metadata=tuple(sources))

    def add_metadata_source(self, source: str, row_above: int = 0,
                            delimiters: str = DEFAULT_DELIMITERS) -> int:
        """Adds a text metadata is taken from, every piece of it in the sample dropped; returns its number."""
        self.change(metadata=self.template.metadata + (
            MetadataSource(source=source, row_above=row_above, delimiters=delimiters),))
        number = len(self.template.metadata) - 1
        self._replace_source(number, dataclasses.replace(self.template.metadata[number],
                                                         pieces=self._all_dropped(number)))
        return number

    def remove_metadata_source(self, number: int) -> None:
        self.change(metadata=self.template.metadata[:number] + self.template.metadata[number + 1:])

    def change_metadata_source(self, number: int, *, delimiters: Optional[str] = None,
                               drop_unknown: Optional[bool] = None) -> None:
        """
        Changes how a source's text is split, or whether pieces no rule names
        are dropped. New delimiters split the text again into other pieces, so
        every piece is dropped and assigned afresh. While pieces no rule names
        are dropped, a drop rule is not needed (and would make a file with
        fewer pieces a misfit), so there are none; turned off, every sample
        piece without a field gets one again.
        """
        source = self.template.metadata[number]
        if delimiters is not None and delimiters != source.delimiters:
            self._replace_source(number, dataclasses.replace(source, delimiters=delimiters, pieces=()))
            self._replace_source(number, dataclasses.replace(self.template.metadata[number],
                                                             pieces=self._all_dropped(number)))
            source = self.template.metadata[number]
        if drop_unknown is not None and drop_unknown != source.drop_unknown:
            kept = tuple(rule for rule in source.pieces if not rule.is_dropped)
            self._replace_source(number, dataclasses.replace(source, drop_unknown=drop_unknown, pieces=kept))
            if not drop_unknown:
                count = len(self._sample_pieces(number))
                named = {resolve_piece_index(rule.position, count) for rule in kept}
                self._replace_source(number, dataclasses.replace(
                    self.template.metadata[number], pieces=kept + tuple(
                        MetadataPiece(position) for position in range(count) if position not in named)))

    def assign_piece(self, number: int, position: int, field: str, *, key_value: bool = False,
                     split_unit: bool = False, kind: str = "", from_end: bool = False) -> str:
        """
        Makes piece `position` (0 = the first, in the sample's text) of source
        `number` the field `field`: with `key_value` the field takes the
        piece's value and the sample's key is kept as the key a file must
        have; with `split_unit` the value is a number and the sample's unit is
        the field's unit; `from_end` counts the position from the end in other
        files. Returns why the choice is refused (and nothing changes), blank
        when it is made. A blank field drops the piece -- with `key_value` it
        is named after the key, so "Damping = 0.02" gives its name and value
        at once.
        """
        pieces = self._sample_pieces(number)
        if not 0 <= position < len(pieces):
            return f"The sample's text has no piece {position + 1}."
        piece = pieces[position]
        if kind and kind not in FIELD_KINDS:
            return f"'{kind}' is not a field kind; expected one of {', '.join(FIELD_KINDS)}."
        if key_value and not piece.key:
            return f"'{piece.text}' has no key: it is not 'key = value' or 'key value'."
        field = field.strip() or (piece.key if key_value else "")
        if not field:
            self.drop_piece(number, position)
            return ""
        value = piece.value if key_value else piece.text
        unit = ""
        if split_unit:
            number_unit = resolve_number_unit(value)
            if number_unit is None:
                return f"'{value}' is not a number with a unit."
            unit = number_unit[1]
        rule = MetadataPiece(position=position - len(pieces) if from_end else position, field=field.strip(),
                             key=piece.key if key_value else "", split_unit=split_unit, unit=unit, kind=kind)
        source = self._with_rule(number, position, len(pieces), rule)
        sources = list(self.template.metadata)
        sources[number] = source
        candidate = dataclasses.replace(self.template, metadata=tuple(sources))
        problem = resolve_duplicate_field_problem(candidate)
        if problem:
            return problem
        self.template = candidate
        return ""

    def drop_piece(self, number: int, position: int) -> None:
        """Drops piece `position` of source `number`: it is never stored."""
        pieces = self._sample_pieces(number)
        rule = None if self.template.metadata[number].drop_unknown else MetadataPiece(position=position)
        self._replace_source(number, self._with_rule(number, position, len(pieces), rule))

    def _with_rule(self, number: int, position: int, count: int,
                   rule: Optional[MetadataPiece]) -> MetadataSource:
        """Source `number` with `rule` (None: no rule) in place of the rule that names sample piece `position`."""
        source = self.template.metadata[number]
        kept = tuple(other for other in source.pieces if resolve_piece_index(other.position, count) != position)
        pieces = kept + ((rule,) if rule is not None else ())

        def sample_order(other: MetadataPiece) -> int:
            index = resolve_piece_index(other.position, count)
            return count if index is None else index

        return dataclasses.replace(source, pieces=tuple(sorted(pieces, key=sample_order)))

    @staticmethod
    def resolve_amplitude_unit_options(header_unit: str) -> List[str]:
        """
        The units offered for the amplitude: the header's own first (also one the
        program does not know), then the known ones, compatible first. Speed
        units are the X axis's, never an amplitude's.
        """
        known = [unit for unit in get_compatible_options(header_unit) if unit not in _SPEED_UNITS]
        own = [header_unit] if header_unit and header_unit != "unknown" and header_unit not in known else []
        return own + known

    def resolve_fit_problem(self, preview: WizardPreview) -> str:
        """Why the template cannot be kept whatever its name: no pattern, a field fed twice, no fit."""
        if not self.template.name.strip():
            return "Give the template a name."
        if not self.template.file_pattern.strip():
            return "Give the template a file name pattern."
        duplicate = resolve_duplicate_field_problem(self.template)
        if duplicate:
            return duplicate
        if preview.problem:
            return f"The sample does not fit: {preview.problem}"
        if not preview.channels:
            return "The template reads no channel from the sample."
        return ""


def resolve_library_save_problem(name: str, builtin_names: Optional[Iterable[str]] = None) -> str:
    """Why a template cannot go into the library under `name`, blank when it can: a built-in's name is refused."""
    name = name.strip()
    if not name:
        return "Give the template a name."
    names = builtin_names if builtin_names is not None else (t.name for t in read_builtin_templates())
    if name.lower() in {builtin.lower() for builtin in names}:
        return f"'{name}' is a built-in template; save under another name."
    return ""
