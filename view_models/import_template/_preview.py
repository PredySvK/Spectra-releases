"""
What the import wizard shows for a template on a sample: the shown sheet as a
grid of cell texts and roles, the channels the template reads, the texts
around the first channel that pieces can be picked from, each metadata source
text split into its pieces, and the metadata table -- every resulting channel's
fields, of the kinds the Data Pool schema gives them.

Pure: plain values in, plain values out, safe on a worker thread.
"""

import dataclasses
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from core.import_template import (
    PICK_FILE_NAME, PICK_FOLDER, PICK_HEADER, PICK_SHEET, SHEETS_LISTED, ImportTemplate, TextPick,
)
from io_modules.import_template import (
    SheetReading, Workbook, build_source_pieces, build_template_reading, build_template_schema_fields,
    resolve_metadata_source_label, resolve_cell_text, resolve_header_column, resolve_metadata_source_text,
    resolve_pick_source_text, resolve_piece_index, resolve_head_row_count, resolve_read_sheets, resolve_template_field_key,
)
from io_modules.number_pairs import read_number_pairs

CELL_HEADER = "header"
CELL_DATA = "data"
CELL_IGNORED = "ignored"

# The grid shows the head of the sheet only; the channels table counts every row.
PREVIEW_ROWS = 200
_SOURCE_TEXT_ROWS = 8


@dataclass(frozen=True)
class PreviewChannel:
    """One resulting channel, as the channels table shows it."""

    sheet: str
    name: str
    x_unit: str
    unit: str
    channel_type: str
    order: Optional[float]
    source_amplitude: str
    points: int
    lost_rows: int
    problem: str
    metadata: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PreviewField:
    """One column of the metadata table: a field, as the Filters panel will name it, and its kind."""

    field: str
    label: str
    kind: str


@dataclass(frozen=True)
class PreviewPiece:
    """One piece of a metadata source text in the sample, and the rule the template has for it (field blank = dropped)."""

    position: int
    text: str
    field: str
    key: str
    split_unit: bool
    kind: str
    from_end: bool


@dataclass(frozen=True)
class PreviewSource:
    """A metadata source's text in the sample, split into its pieces."""

    label: str
    text: str
    pieces: Tuple[PreviewPiece, ...]


@dataclass(frozen=True)
class WizardPreview:
    """The shown sheet's cells and their roles, the resulting channels, and why the template does not fit."""

    sheet: str
    cells: Tuple[Tuple[str, ...], ...]
    roles: Tuple[Tuple[str, ...], ...]
    channels: Tuple[PreviewChannel, ...]
    misfit: str
    problem: str
    source_texts: Tuple[Tuple[str, str], ...]
    metadata_fields: Tuple[PreviewField, ...] = ()
    metadata_sources: Tuple[PreviewSource, ...] = ()


def _grid(rows: Sequence[tuple]) -> Tuple[Tuple[str, ...], ...]:
    shown = rows[:PREVIEW_ROWS]
    width = max((len(row) for row in shown), default=0)
    return tuple(tuple(resolve_cell_text(row[column]) if column < len(row) else "" for column in range(width))
                 for row in shown)


def _roles(rows: Sequence[tuple], cells, reading: Optional[SheetReading]) -> Tuple[Tuple[str, ...], ...]:
    roles: List[List[str]] = [[CELL_IGNORED] * len(row) for row in cells]
    if reading is None:
        return tuple(tuple(row) for row in roles)
    for channel in reading.channels:
        columns = (channel.x_column, channel.y_column)
        for row in range(reading.header_top_row, min(reading.heading_row + 1, len(roles))):
            for column in columns:
                if column < len(roles[row]):
                    roles[row][column] = CELL_HEADER
        for row in range(reading.data_row, len(roles)):
            cells_of_row = rows[row]
            pair = tuple(cells_of_row[column] if column < len(cells_of_row) else None for column in columns)
            if read_number_pairs([pair]).pairs:
                for column in columns:
                    if column < len(roles[row]):
                        roles[row][column] = CELL_DATA
    return tuple(tuple(row) for row in roles)


def _source_texts(workbook: Workbook, rows, reading: Optional[SheetReading],
                  template: ImportTemplate) -> Tuple[Tuple[str, str], ...]:
    texts: List[Tuple[str, str]] = []
    if reading is not None and reading.channels:
        channel = reading.channels[0]
        column = resolve_header_column(template.layout, channel.x_column, channel.y_column)
        for above in range(min(reading.heading_row, _SOURCE_TEXT_ROWS - 1) + 1):
            label = ("Header, heading row" if above == 0 else
                     f"Header, {above} row{'s' if above > 1 else ''} above")
            texts.append((label, resolve_pick_source_text(
                rows, reading.heading_row, column, TextPick(row_above=above, source=PICK_HEADER),
                reading.sheet, workbook.path)))
    sheet = reading.sheet if reading is not None else ""
    for label, source in (("Sheet name", PICK_SHEET), ("File name", PICK_FILE_NAME), ("Folder", PICK_FOLDER)):
        texts.append((label, resolve_pick_source_text((), 0, 0, TextPick(source=source), sheet, workbook.path)))
    return tuple(texts)


def resolve_sample_source_texts(workbook: Workbook, template: ImportTemplate, sheet: str) -> Tuple[str, ...]:
    """
    Each metadata source's text around the first channel of the shown sheet
    (else of the first read sheet), read without the metadata rules so a source
    that does not fit yet still shows its pieces. Blank when there is no channel.
    Reads only the head of one sheet, so it is quick enough for the GUI thread.
    """
    read = resolve_read_sheets(workbook.sheet_names, template)
    sheet = sheet if sheet in read else (read[0] if read else "")
    head = (workbook.rows_of(sheet) or ())[:resolve_head_row_count(template)]
    reading = build_template_reading(Workbook(workbook.path, ((sheet, head),)),
                                     dataclasses.replace(template, metadata=(), sheets=(sheet,), sheet_rule=SHEETS_LISTED))
    if not reading.sheets or not reading.sheets[0].channels:
        return tuple("" for _ in template.metadata)
    shown = reading.sheets[0]
    channel = shown.channels[0]
    column = resolve_header_column(template.layout, channel.x_column, channel.y_column)
    texts = []
    for source in template.metadata:
        try:
            texts.append(resolve_metadata_source_text(head, shown.heading_row, column, source, sheet,
                                                      workbook.path))
        except ValueError:
            texts.append("")
    return tuple(texts)


def build_metadata_sources(template: ImportTemplate, texts: Sequence[str]) -> Tuple[PreviewSource, ...]:
    sources = []
    for source, text in zip(template.metadata, texts):
        pieces = build_source_pieces(text, source.delimiters)
        shown = []
        for piece in pieces:
            rule = next((rule for rule in source.pieces
                         if resolve_piece_index(rule.position, len(pieces)) == piece.position), None)
            shown.append(PreviewPiece(
                position=piece.position, text=piece.text, field=rule.field if rule else "",
                key=rule.key if rule else "", split_unit=rule.split_unit if rule else False,
                kind=rule.kind if rule else "", from_end=rule is not None and rule.position < 0))
        sources.append(PreviewSource(resolve_metadata_source_label(source).capitalize(), text, tuple(shown)))
    return tuple(sources)


def _shown_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return "" if value is None else str(value)


def build_wizard_preview(workbook: Workbook, template: ImportTemplate, sheet: str) -> WizardPreview:
    """The preview of `template` on the sample, with `sheet` shown in the grid."""
    reading = build_template_reading(workbook, template)
    rows = workbook.rows_of(sheet) or ()
    shown = next((sheet_reading for sheet_reading in reading.sheets if sheet_reading.sheet == sheet), None)
    cells = _grid(rows)
    values_by_key = {}
    for channel in reading.channels:
        for field, value in channel.metadata:
            values_by_key.setdefault(resolve_template_field_key(field), []).append(value)
    schema = build_template_schema_fields((template,), values_by_key)
    names = dict.fromkeys(field for channel in reading.channels for field, _ in channel.metadata)
    fields = tuple(PreviewField(name, schema[key]["custom_label"], schema[key]["kind"])
                   for name, key in ((name, resolve_template_field_key(name)) for name in names) if key in schema)
    channels = tuple(
        PreviewChannel(sheet=channel.sheet, name=channel.name, x_unit=channel.x_unit, unit=channel.unit,
                       channel_type=channel.channel_type, order=channel.order,
                       source_amplitude=channel.source_amplitude, points=len(channel.pairs.pairs),
                       lost_rows=channel.pairs.lost_rows, problem=channel.problem,
                       metadata=tuple(_shown_value(dict(channel.metadata).get(field.field)) for field in fields))
        for channel in reading.channels)
    if shown is None and reading.sheets:
        texts_from = reading.sheets[0]
        texts_rows = workbook.rows_of(texts_from.sheet) or ()
    else:
        texts_from, texts_rows = shown, rows
    return WizardPreview(
        sheet=sheet, cells=cells, roles=_roles(rows, cells, shown), channels=channels,
        misfit=reading.misfit, problem=reading.first_problem(),
        source_texts=_source_texts(workbook, texts_rows, texts_from, template),
        metadata_fields=fields,
        metadata_sources=build_metadata_sources(template, resolve_sample_source_texts(workbook, template, sheet)))
