"""
The one reading of a table file by an Import template.

The Data Pool's reader and the import wizard's preview both call
`build_template_reading`, so the preview can never show something the scan
does not do. It works on a `Workbook` already in memory (`read_workbook` is the
only disk access) and never raises for a file that does not fit: a whole-file
misfit is `TemplateReading.misfit`, a channel the template cannot name, order
or unit is that channel's `problem`. Rows of a channel that are not two numbers
are lost rows (§1.177), not problems. Metadata (_metadata.py) that does not fit
is a misfit of the file (file name, folder, sheet name) or a problem of the
channel (column header).
"""

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from core.channel_types import CHANNEL_TYPE_TACHO
from core.import_template import (
    DATA_KIND_ORDER_CUT, DATA_KIND_SPECTRUM, DATA_KIND_TIME_SIGNAL, LAYOUT_SHARED_X, LAYOUT_SINGLE_CURVE, LAYOUT_XY_PAIRS,
    PICK_FILE_NAME, PICK_FOLDER, PICK_HEADER, PICK_SHEET, SHEETS_ALL, SHEETS_FIRST_N, SHEETS_WITHOUT_LAST_N,
    ImportTemplate, MetadataSource, TextPick,
)
from io_modules.import_template._db_reference import convert_db_to_linear, resolve_db_reference
from core.source_amplitude import (
    SOURCE_AMPLITUDE_PEAK, SOURCE_AMPLITUDE_PEAK_TO_PEAK, SOURCE_AMPLITUDE_RMS,
)
from core.units import determine_channel_type
from io_modules.import_template._metadata import resolve_source_fields
from io_modules.import_template._text_table import TextFormat, is_text_table, read_text_rows
from io_modules.number_pairs import NumberPairs, read_number_pairs

# The X column of a channel that has none: a time signal without a time column.
NO_X_COLUMN = -1

# How far down a sheet an anchor text is looked for.
ANCHOR_SEARCH_ROWS = 60

_UNIT_RE = re.compile(r"\(([^)]*)\)\s*$")
_PEAK_TO_PEAK_RE = re.compile(r"peak[\s-]*to[\s-]*peak|\bp[\s-]?p\b|\bpk[\s-]?pk\b")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
_RATE_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_AXIS_RE = re.compile(r"^[+-]?[XYZ]$")

# Speed units the X of an order cut, Overall Level or residual may be in, and their factor to rpm.
RPM_PER_UNIT = {"rev/min": 1.0, "rpm": 1.0, "rev/s": 60.0, "hz": 60.0}
# Frequency units the X of a spectrum may be in, and their factor to Hz.
HZ_PER_UNIT = {"hz": 1.0, "khz": 1000.0}
# Time units the time column of a time signal may be in, and their factor to seconds.
SECONDS_PER_UNIT = {"s": 1.0, "sec": 1.0, "ms": 1e-3}

# How far a sample's time may lie from an evenly spaced grid, in sample steps, before the step is not uniform.
UNIFORM_STEP_TOLERANCE = 0.1


def resolve_x_units(data_kind: str) -> Dict[str, float]:
    """The units the X column of this data kind may be in, each with its factor to the axis unit (rpm, Hz, s)."""
    if data_kind == DATA_KIND_TIME_SIGNAL:
        return SECONDS_PER_UNIT
    return HZ_PER_UNIT if data_kind == DATA_KIND_SPECTRUM else RPM_PER_UNIT


def resolve_x_factor(data_kind: str, unit: str) -> float:
    """The factor from X values in `unit` to the axis unit; KeyError for a unit the data kind does not know."""
    return resolve_x_units(data_kind)[unit.lower()]


@dataclass(frozen=True)
class Workbook:
    """
    A table file's sheets in file order, each its rows of cell values. A text
    file is one sheet named like the file; `text_format` is how it was parsed
    and `detected_text_format` what the file itself suggests (None for a workbook).
    """

    path: str
    sheets: Tuple[Tuple[str, Tuple[tuple, ...]], ...]
    text_format: Optional[TextFormat] = None
    detected_text_format: Optional[TextFormat] = None

    @property
    def sheet_names(self) -> Tuple[str, ...]:
        return tuple(name for name, _ in self.sheets)

    def rows_of(self, sheet: str) -> Optional[Tuple[tuple, ...]]:
        for name, rows in self.sheets:
            if name == sheet:
                return rows
        return None


def build_text_format(template: ImportTemplate) -> TextFormat:
    """The parsing the template sets for a text file; a blank field is detected from each file."""
    return TextFormat(template.encoding, template.delimiter, template.decimal_separator)


def read_workbook(path: str, sheets: Union[None, Sequence[str], Callable[[Sequence[str]], Sequence[str]]] = None,
                  max_row: Optional[int] = None, text_format: TextFormat = TextFormat()) -> Workbook:
    """
    The workbook's sheets in file order: every sheet when `sheets` is None,
    else only those named (a missing one is left out), and only the first
    sheet for an empty `sheets` -- what a template without its own sheet list
    reads. `sheets` may also be a function of the file's sheet names that
    returns the ones to read (`resolve_read_sheets` of a template). A text file (.txt, .csv) is one sheet named like the file, parsed
    with `text_format` (blank fields detected). Reads the whole file: call it
    on a worker thread.
    """
    if is_text_table(path):
        rows, used, detected = read_text_rows(path, text_format, max_row)
        name = os.path.splitext(os.path.basename(path))[0]
        if callable(sheets):
            sheets = sheets([name])
        listed = sheets is None or not sheets or name in sheets
        return Workbook(path, ((name, rows),) if listed else (), used, detected)
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if callable(sheets):
            wanted = set(sheets([sheet.title for sheet in book.worksheets]))
            read = [sheet for sheet in book.worksheets if sheet.title in wanted]
        elif sheets is None:
            read = list(book.worksheets)
        elif not sheets:
            read = list(book.worksheets[:1])
        else:
            read = [sheet for sheet in book.worksheets if sheet.title in set(sheets)]
        return Workbook(path, tuple(
            (sheet.title, tuple(sheet.iter_rows(max_row=max_row, values_only=True))) for sheet in read))
    finally:
        book.close()


@dataclass(frozen=True)
class TemplateChannel:
    """One channel the template finds, with everything the reader reports about it."""

    index: int
    sheet: str
    x_column: int
    y_column: int
    name: str
    x_unit: str
    unit: str
    channel_type: str
    order: Optional[float]
    source_amplitude: str
    pairs: NumberPairs
    db_reference: float = 0.0
    sample_rate: float = 0.0
    problem: str = ""
    metadata: Tuple[Tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class SheetReading:
    """Where the template found the header and data of one sheet, and its channels."""

    sheet: str
    heading_row: int
    header_top_row: int
    data_row: int
    channels: Tuple[TemplateChannel, ...]


@dataclass(frozen=True)
class TemplateReading:
    """A file read by a template: its sheets, or why it does not fit the template."""

    sheets: Tuple[SheetReading, ...] = ()
    misfit: str = ""
    channels: Tuple[TemplateChannel, ...] = field(default=())

    def first_problem(self) -> str:
        """The misfit, else the first channel's problem, blank when the file reads clean."""
        if self.misfit:
            return self.misfit
        return next((f"{channel.name or f'channel {channel.index}'}: {channel.problem}"
                     for channel in self.channels if channel.problem), "")


def resolve_linear_values(channel: TemplateChannel) -> np.ndarray:
    """The channel's amplitudes as the file's linear amplitude: values stated in dB are converted, others are as read."""
    values = np.asarray(channel.pairs.pairs, dtype=np.float64).reshape(-1, 2)[:, 1]
    return convert_db_to_linear(values, channel.db_reference) if channel.db_reference > 0 else values


def resolve_head_row_count(template: ImportTemplate) -> int:
    """How many rows of a sheet hold everything but the data: where the anchor is looked for, and the first data row."""
    return max(ANCHOR_SEARCH_ROWS, template.heading_row) + template.data_offset


def resolve_cell_text(cell) -> str:
    return "" if cell is None else str(cell).strip()


def resolve_read_sheets(sheet_names: Sequence[str], template: ImportTemplate) -> Tuple[str, ...]:
    """The sheets the template reads of a file with these sheets, by its sheet rule."""
    rule, count = template.sheet_rule, max(1, template.sheet_count)
    if rule == SHEETS_ALL:
        return tuple(sheet_names)
    if rule == SHEETS_FIRST_N:
        return tuple(sheet_names[:count])
    if rule == SHEETS_WITHOUT_LAST_N:
        return tuple(sheet_names[:max(1, len(sheet_names) - count)])
    if template.sheets:
        return tuple(template.sheets)
    return tuple(sheet_names[:1])


def resolve_heading_row(rows: Sequence[tuple], template: ImportTemplate) -> Optional[int]:
    """The index of the sheet's heading row, or None when the template does not find it."""
    anchor = template.anchor_text.strip().lower()
    if anchor:
        for index, row in enumerate(rows[:ANCHOR_SEARCH_ROWS]):
            if row and resolve_cell_text(row[0]).lower() == anchor:
                return index
        return None
    index = template.heading_row - 1
    return index if 0 <= index < len(rows) else None


def _describe_missing_heading(template: ImportTemplate, sheet: str) -> str:
    if template.anchor_text.strip():
        return f"the anchor '{template.anchor_text}' is not in the first column of sheet '{sheet}'"
    return f"sheet '{sheet}' has no row {template.heading_row}"


def _channel_columns(heading: tuple, layout: str, time_column: bool = True) -> List[Tuple[int, int]]:
    """
    (X column, amplitude column) of each channel the heading row's cells form.
    Without a time column (a time signal that has none) every column is a
    signal and X column is NO_X_COLUMN.
    """
    cells = [resolve_cell_text(cell) for cell in heading]
    if not time_column:
        if layout == LAYOUT_SINGLE_CURVE:
            return [(NO_X_COLUMN, 0)] if cells and cells[0] else []
        return [(NO_X_COLUMN, column) for column, cell in enumerate(cells) if cell]
    if layout == LAYOUT_XY_PAIRS:
        first = cells[0].lower() if cells else ""
        return [(2 * pair, 2 * pair + 1) for pair in range(len(cells) // 2)
                if first and cells[2 * pair].lower() == first and cells[2 * pair + 1]]
    if layout == LAYOUT_SHARED_X:
        return [(0, column) for column in range(1, len(cells)) if cells[column]]
    if layout == LAYOUT_SINGLE_CURVE:
        return [(0, 1)] if len(cells) >= 2 and cells[1] else []
    raise ValueError(f"Unknown column layout {layout!r}.")


def _resolve_sample_rate(template: ImportTemplate, rows, heading_row: int, sheet: str, file_path: str) -> float:
    """The sample rate in Hz a time signal without a time column states; ValueError when it states none."""
    stated = template.sample_rate
    if not isinstance(stated, TextPick):
        return float(stated)
    text = resolve_pick(rows, heading_row, 0, stated, sheet, file_path)
    match = _RATE_RE.search(text if "." in text else text.replace(",", "."))
    if match is None:
        raise ValueError("no sample rate in the header text the template takes it from")
    return float(match.group()) * (1000.0 if "khz" in text.lower() else 1.0)


def resolve_uniform_sample_rate(seconds: np.ndarray) -> Tuple[float, str]:
    """(sample rate in Hz, "") of evenly spaced times, else (0.0, why the time step is not uniform)."""
    if len(seconds) < 2:
        return 0.0, "fewer than two samples, so no sample rate"
    step = (seconds[-1] - seconds[0]) / (len(seconds) - 1)
    if not step > 0:
        return 0.0, "the time does not increase"
    drift = float(np.abs(seconds - (seconds[0] + np.arange(len(seconds)) * step)).max()) / step
    if drift > UNIFORM_STEP_TOLERANCE:
        return 0.0, (f"the time step is not uniform (a sample lies {drift:.2f} steps off an even grid), "
                     f"and it is not resampled")
    return 1.0 / step, ""


def resolve_header_column(layout: str, x_column: int, y_column: int) -> int:
    """The column whose header cells describe a channel: a pair's X column, else the amplitude column."""
    return x_column if layout == LAYOUT_XY_PAIRS else y_column


def _apply_pick(text: str, pick: TextPick) -> str:
    if pick.split:
        parts = text.split(pick.split)
        text = parts[pick.piece] if pick.piece < len(parts) else ""
    if pick.after:
        text = text.split(pick.after, 1)[1] if pick.after in text else ""
    if pick.before:
        text = text.split(pick.before, 1)[0]
    return text.strip()


def resolve_pick_source_text(rows: Sequence[tuple], heading_row: int, column: int, pick: TextPick,
                             sheet: str, file_path: str) -> str:
    """The whole text a pick cuts its piece from; ValueError for a header row above the sheet."""
    if pick.source == PICK_SHEET:
        return sheet
    if pick.source == PICK_FILE_NAME:
        return os.path.splitext(os.path.basename(file_path))[0]
    if pick.source == PICK_FOLDER:
        return os.path.basename(os.path.dirname(os.path.abspath(file_path)))
    row = heading_row - pick.row_above
    if row < 0:
        raise ValueError(f"header row {pick.row_above} above the heading row does not exist")
    cells = rows[row]
    return resolve_cell_text(cells[column]) if column < len(cells) else ""


def resolve_pick(rows, heading_row: int, column: int, pick: TextPick, sheet: str, file_path: str) -> str:
    return _apply_pick(resolve_pick_source_text(rows, heading_row, column, pick, sheet, file_path), pick)


def resolve_source_amplitude(cell, bare: str) -> str:
    """The Source amplitude the amplitude header says (RMS / Peak / Peak-to-Peak), else what a bare "Amplitude" means."""
    text = _UNIT_RE.sub("", resolve_cell_text(cell)).lower()
    if _PEAK_TO_PEAK_RE.search(text):
        return SOURCE_AMPLITUDE_PEAK_TO_PEAK
    if re.search(r"\brms\b", text):
        return SOURCE_AMPLITUDE_RMS
    if re.search(r"\bpeak\b", text):
        return SOURCE_AMPLITUDE_PEAK
    return bare


def resolve_header_unit(cell) -> str:
    """The trailing "(unit)" of a heading cell, "unknown" when it has none."""
    match = _UNIT_RE.search(resolve_cell_text(cell))
    return match.group(1).strip().replace("˛", "²") if match else "unknown"   # ANSYS writes ² as ˛.


def resolve_metadata_source_text(rows: Sequence[tuple], heading_row: int, column: int,
                                 source: MetadataSource, sheet: str, file_path: str) -> str:
    """The whole text a metadata source splits into pieces; ValueError for a header row above the sheet."""
    return resolve_pick_source_text(rows, heading_row, column,
                                    TextPick(row_above=source.row_above, source=source.source), sheet, file_path)


def resolve_metadata_source_label(source: MetadataSource) -> str:
    """Where a metadata source's text is, as a sentence names it."""
    if source.source == PICK_HEADER:
        if source.row_above == 0:
            return "the heading row's header"
        return f"the header {source.row_above} row{'s' if source.row_above > 1 else ''} above the heading row"
    return {PICK_SHEET: "the sheet name", PICK_FILE_NAME: "the file name", PICK_FOLDER: "the folder"}[source.source]


# Metadata kept from each of a template's sources, by the source's position in `template.metadata`.
_SourceFields = Dict[int, Tuple[Tuple[str, Any], ...]]


def _resolve_fields(template: ImportTemplate, kinds: Tuple[str, ...], rows, heading_row: int, column: int,
                    sheet: str, file_path: str) -> Tuple[_SourceFields, str]:
    """The fields of the template's metadata sources of these kinds, and why one does not fit."""
    fields: _SourceFields = {}
    for number, source in enumerate(template.metadata):
        if source.source not in kinds:
            continue
        try:
            text = resolve_metadata_source_text(rows, heading_row, column, source, sheet, file_path)
        except ValueError as error:
            return fields, str(error)
        fields[number], problem = resolve_source_fields(text, source, resolve_metadata_source_label(source))
        if problem:
            return fields, problem
    return fields, ""


def _in_template_order(*parts: _SourceFields) -> Tuple[Tuple[str, Any], ...]:
    merged: _SourceFields = {}
    for part in parts:
        merged.update(part)
    return tuple(field for number in sorted(merged) for field in merged[number])


def _cell(row: tuple, column: int):
    return row[column] if column < len(row) else None


def _read_channel(index: int, sheet: str, rows, heading_row: int, data_row: int,
                  columns: Tuple[int, int], template: ImportTemplate, file_path: str,
                  outer_fields: _SourceFields) -> TemplateChannel:
    x_column, y_column = columns
    described_by = resolve_header_column(template.layout, x_column, y_column)
    heading = rows[heading_row]
    timed = template.data_kind == DATA_KIND_TIME_SIGNAL
    has_x = x_column != NO_X_COLUMN
    x_unit = (template.x_unit or resolve_header_unit(_cell(heading, x_column))) if has_x else "s"
    unit = template.amplitude_unit or resolve_header_unit(_cell(heading, y_column))
    source_amplitude = (template.fixed_source_amplitude
                        or resolve_source_amplitude(_cell(heading, y_column), template.source_amplitude))
    problems: List[str] = []
    if has_x:
        pairs = read_number_pairs((_cell(row, x_column), _cell(row, y_column)) for row in rows[data_row:])
    else:   # One value per row: the row's place on the stated rate is its time.
        values = read_number_pairs((_cell(row, y_column),) * 2 for row in rows[data_row:])
        if values.lost_rows:    # a dropped row would shift every later sample earlier in time
            problems.append(f"{values.lost_rows} row(s) are not numbers, which would shift the time "
                            f"of the samples after them (there is no time column to keep it)")
        pairs = NumberPairs([(float(number), pair[1]) for number, pair in enumerate(values.pairs)],
                            values.lost_rows)

    def pick(part: TextPick) -> str:
        try:
            return resolve_pick(rows, heading_row, described_by, part, sheet, file_path)
        except ValueError as error:
            problems.append(str(error))
            return ""

    sample_rate = 0.0
    if timed and not has_x:
        try:
            sample_rate = _resolve_sample_rate(template, rows, heading_row, sheet, file_path)
        except ValueError as error:
            problems.append(str(error))
        else:
            if sample_rate > 0:
                pairs = NumberPairs([(number / sample_rate, value) for number, value in pairs.pairs],
                                    pairs.lost_rows)
            else:
                problems.append("the sample rate is not a positive number")
    name = "".join(part if isinstance(part, str) else pick(part) for part in template.channel_name)
    if not name.strip(": ") and not problems:
        problems.append(f"column {y_column + 1} has no header text for the channel name")
    if template.axis is not None:
        axis = pick(template.axis).upper()
        if _AXIS_RE.match(axis):
            name = f"{name}:{axis}"
        elif not problems:
            problems.append(f"'{axis}' is not an axis X, Y or Z")
    order: Optional[float] = None
    if template.data_kind == DATA_KIND_ORDER_CUT:       # only an order cut has an order
        if isinstance(template.order, TextPick):
            match = _NUMBER_RE.search(pick(template.order))
            if match is not None:
                order = float(match.group())
            elif not problems:
                problems.append("no order in the text the template takes it from")
        else:
            order = float(template.order)
    db_reference = 0.0
    if template.values_in_db:
        reference = resolve_db_reference(unit, template.db_reference)
        if reference is None and not problems:
            problems.append(f"no dB reference is known for the unit '{unit}'; state the amplitude unit "
                            f"of the linear value and the reference")
        db_reference = reference or 0.0
    if x_unit.lower() not in resolve_x_units(template.data_kind) and not problems:
        what = {DATA_KIND_SPECTRUM: "frequency", DATA_KIND_TIME_SIGNAL: "time"}.get(template.data_kind, "speed")
        problems.append(f"{what} unit '{x_unit}' is not one the template reader knows")
    if timed and not problems:
        seconds = np.asarray(pairs.pairs, dtype=np.float64).reshape(-1, 2)[:, 0] * resolve_x_factor(
            template.data_kind, x_unit)
        sample_rate, problem = resolve_uniform_sample_rate(seconds)
        if problem:
            problems.append(problem)
    header_fields, problem = _resolve_fields(template, (PICK_HEADER,), rows, heading_row, described_by,
                                             sheet, file_path)
    if problem and not problems:
        problems.append(problem)
    return TemplateChannel(
        index=index, sheet=sheet, x_column=x_column, y_column=y_column, name=name,
        x_unit=x_unit, unit=unit, channel_type=_resolve_channel_type(template, unit, name),
        order=order, source_amplitude=source_amplitude, pairs=pairs, db_reference=db_reference,
        sample_rate=sample_rate,
        problem=problems[0] if problems else "",
        metadata=_in_template_order(outer_fields, header_fields))


def _resolve_channel_type(template: ImportTemplate, unit: str, name: str) -> str:
    """The channel type: the speed channel of a time signal is the tacho, else the template's or the unit's."""
    if (template.data_kind == DATA_KIND_TIME_SIGNAL and template.speed_channel.strip()
            and name.strip().lower() == template.speed_channel.strip().lower()):
        return CHANNEL_TYPE_TACHO
    return template.channel_type or determine_channel_type(unit, name)


def _header_top_row(template: ImportTemplate, heading_row: int) -> int:
    picks = [part for part in template.channel_name if isinstance(part, TextPick)]
    picks += [pick for pick in (template.axis, template.order) if isinstance(pick, TextPick)]
    picks += list(template.metadata)
    if isinstance(template.sample_rate, TextPick):
        picks.append(template.sample_rate)
    reach = max((pick.row_above for pick in picks if pick.source == PICK_HEADER), default=0)
    return max(0, heading_row - reach)


def build_template_reading(workbook: Workbook, template: ImportTemplate) -> TemplateReading:
    """Every channel the template reads in the workbook, or why the workbook does not fit it."""
    readings: List[SheetReading] = []
    channels: List[TemplateChannel] = []
    sheets = resolve_read_sheets(workbook.sheet_names, template)
    if not sheets:
        return TemplateReading(misfit="the workbook has no sheet")
    timed = template.data_kind == DATA_KIND_TIME_SIGNAL
    file_fields, misfit = _resolve_fields(template, (PICK_FILE_NAME, PICK_FOLDER), (), 0, 0, "", workbook.path)
    if misfit:
        return TemplateReading(misfit=misfit)
    for sheet in sheets:
        rows = workbook.rows_of(sheet)
        if rows is None:
            return TemplateReading(misfit=f"the workbook has no sheet '{sheet}'")
        heading_row = resolve_heading_row(rows, template)
        if heading_row is None:
            return TemplateReading(misfit=_describe_missing_heading(template, sheet))
        skipped = {column for name, column in template.skipped_columns if name == sheet}
        columns = [pair for pair in _channel_columns(rows[heading_row], template.layout,
                                                     template.time_column or not timed)
                   if pair[1] not in skipped]
        if not columns:
            return TemplateReading(misfit=f"the heading row of sheet '{sheet}' forms no channel "
                                          f"in the column layout {template.layout}")
        sheet_fields, misfit = _resolve_fields(template, (PICK_SHEET,), rows, heading_row, 0, sheet,
                                               workbook.path)
        if misfit:
            return TemplateReading(misfit=misfit)
        data_row = heading_row + template.data_offset
        outer_fields = {**file_fields, **sheet_fields}
        sheet_channels = tuple(
            _read_channel(len(channels) + number, sheet, rows, heading_row, data_row, pair, template,
                          workbook.path, outer_fields)
            for number, pair in enumerate(columns))
        channels.extend(sheet_channels)
        readings.append(SheetReading(sheet, heading_row, _header_top_row(template, heading_row),
                                     data_row, sheet_channels))
    speed = template.speed_channel.strip().lower()
    if timed and speed and not any(channel.name.strip().lower() == speed for channel in channels):
        return TemplateReading(misfit=f"no channel is named '{template.speed_channel}', the speed channel "
                                      f"of the template")
    return TemplateReading(sheets=tuple(readings), channels=tuple(channels))
