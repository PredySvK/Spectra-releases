"""
What the import wizard shows for a template on all its samples: a tab for
every file and sheet (a skipped one with its reason), every channel of every
sample as the template reads it, and what the heading cells state before any
override -- the units and whether an amplitude header says RMS, Peak or
Peak-to-Peak -- and the chips of every channel's texts for step 3
(`SampleChips`).

Pure: plain values in, plain values out, safe on a worker thread. It reads
through the same `build_template_reading` as the Data Pool scan.
"""

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from core.import_template import SOURCE_FILE_NAME, SOURCE_FOLDER, SOURCE_HEADER, SOURCE_SHEET, ImportTemplate
from core.units import determine_channel_type
from io_modules.import_template import (
    Workbook, build_template_reading, resolve_cell_text, resolve_chip_source_text, resolve_header_column,
    resolve_header_unit, resolve_read_sheets, resolve_source_amplitude,
)
from view_models.import_template._chip_cuts import SourceCuts, apply_chip_cuts
from view_models.import_template._sample_chips import (
    ChannelTexts, SampleChips, build_chip_source, build_sample_chips, resolve_chip_sources,
)

# Why a tab is not read, when the sheet rule leaves it out.
NOT_BY_SHEET_RULE = "the sheet rule does not read it"

# The grid shows the head of the sheet only; the channels table counts every row.
PREVIEW_ROWS = 200


@dataclass(frozen=True)
class SampleSheet:
    """
    One tab of the preview: a sheet of a sample, its head as cell texts, and --
    when it is read -- its heading row, first data row, X columns and channel
    columns (rows and columns from 0). `skipped` says why it is not read.
    """

    path: str
    sheet: str
    label: str
    cells: Tuple[Tuple[str, ...], ...]
    skipped: str = ""
    heading_row: int = -1
    data_row: int = -1
    x_columns: Tuple[int, ...] = ()
    channel_columns: Tuple[int, ...] = ()


@dataclass(frozen=True)
class SampleChannel:
    """One channel of a sample as the template reads it, and why it does not fit (blank when it does)."""

    path: str
    sheet: str
    name: str
    x_unit: str
    unit: str
    order: Optional[float]
    points: int
    lost_rows: int
    problem: str
    x_column: int
    y_column: int


@dataclass(frozen=True)
class SkippedSampleSheet:
    """A sheet of a sample the template does not read, and why."""

    path: str
    sheet: str
    reason: str


@dataclass(frozen=True)
class SampleUnits:
    """The units one sample's heading cells state (X and amplitude), before any override; "unknown" for none."""

    path: str
    x_units: Tuple[str, ...]
    amplitude_units: Tuple[str, ...]


@dataclass(frozen=True)
class SamplePreview:
    """
    Every tab, every channel and skipped sheet, the files that do not fit at
    all (path, why), the units each sample states, the amplitude heading cells
    that say only "Amplitude", and the channel type the first channel would be
    given automatically (with the unit it is read in). `chips` are the
    texts of `channels`, in the same order, split for step 3.
    """

    sheets: Tuple[SampleSheet, ...] = ()
    channels: Tuple[SampleChannel, ...] = ()
    skipped_sheets: Tuple[SkippedSampleSheet, ...] = ()
    misfits: Tuple[Tuple[str, str], ...] = ()
    units: Tuple[SampleUnits, ...] = ()
    bare_amplitude_headers: Tuple[str, ...] = ()
    automatic_channel_type: str = ""
    automatic_channel_unit: str = ""
    chips: SampleChips = SampleChips()


def resolve_sample_label(path: str, sheet: str) -> str:
    """How a tab names a sheet: the file name, and the sheet after it when they differ (a workbook)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem if sheet == stem else f"{stem} › {sheet}"


def _cells(rows: Sequence[tuple]) -> Tuple[Tuple[str, ...], ...]:
    shown = rows[:PREVIEW_ROWS]
    width = max((len(row) for row in shown), default=0)
    return tuple(tuple(resolve_cell_text(row[column]) if column < len(row) else "" for column in range(width))
                 for row in shown)


def _cell(rows: Sequence[tuple], row: int, column: int):
    cells = rows[row] if 0 <= row < len(rows) else ()
    return cells[column] if 0 <= column < len(cells) else None


def _channel_texts(workbook: Workbook, sheet: str, rows, heading_row: int, template: ImportTemplate,
                   x_column: int, y_column: int) -> ChannelTexts:
    column = resolve_header_column(template.layout, x_column, y_column)
    sources = [build_chip_source(SOURCE_HEADER, row_above) for row_above in range(heading_row + 1)]
    sources += [build_chip_source(kind) for kind in (SOURCE_SHEET, SOURCE_FILE_NAME, SOURCE_FOLDER)]
    texts = tuple((source.key, resolve_chip_source_text(rows, heading_row, column, y_column, source, sheet,
                                                        workbook.path)) for source in sources)
    return ChannelTexts(workbook.path, sheet, heading_row, column, x_column, y_column, texts)


def build_sample_preview(samples: Sequence[Workbook], template: ImportTemplate,
                         cuts: SourceCuts = ()) -> SamplePreview:
    """The preview of `template` on every sample, in sample order; `cuts` are the own cuts of the chips (#1033)."""
    sheets: List[SampleSheet] = []
    channels: List[SampleChannel] = []
    skipped: List[SkippedSampleSheet] = []
    misfits: List[Tuple[str, str]] = []
    units: List[SampleUnits] = []
    bare: List[str] = []
    texts: List[ChannelTexts] = []
    for workbook in samples:
        reading = build_template_reading(workbook, template)
        read_by_rule = set(resolve_read_sheets(workbook.sheet_names, template))
        skipped_by_sheet = {sheet.sheet: sheet.reason for sheet in reading.skipped_sheets}
        readings = {sheet.sheet: sheet for sheet in reading.sheets}
        if reading.misfit:
            misfits.append((workbook.path, reading.misfit))
        x_units, amplitude_units = [], []
        for name, rows in workbook.sheets:
            label = resolve_sample_label(workbook.path, name)
            found = readings.get(name)
            if found is None:
                reason = (skipped_by_sheet.get(name)
                          or (NOT_BY_SHEET_RULE if name not in read_by_rule else f"the file does not fit: {reading.misfit}"))
                sheets.append(SampleSheet(workbook.path, name, label, _cells(rows), skipped=reason))
                skipped.append(SkippedSampleSheet(workbook.path, name, reason))
                continue
            sheets.append(SampleSheet(
                workbook.path, name, label, _cells(rows), heading_row=found.heading_row, data_row=found.data_row,
                x_columns=tuple(sorted({channel.x_column for channel in found.channels if channel.x_column >= 0})),
                channel_columns=tuple(channel.y_column for channel in found.channels)))
            for channel in found.channels:
                amplitude_cell = _cell(rows, found.heading_row, channel.y_column)
                if channel.x_column >= 0:
                    x_units.append(resolve_header_unit(_cell(rows, found.heading_row, channel.x_column)))
                amplitude_units.append(resolve_header_unit(amplitude_cell))
                if not resolve_source_amplitude(amplitude_cell, ""):
                    bare.append(resolve_cell_text(amplitude_cell))
                channels.append(SampleChannel(
                    workbook.path, name, channel.name, channel.x_unit, channel.unit, channel.order,
                    len(channel.pairs.pairs), channel.pairs.lost_rows, channel.problem,
                    channel.x_column, channel.y_column))
                texts.append(_channel_texts(workbook, name, rows, found.heading_row, template,
                                            channel.x_column, channel.y_column))
        units.append(SampleUnits(workbook.path, tuple(dict.fromkeys(x_units)), tuple(dict.fromkeys(amplitude_units))))
    first = channels[0] if channels else None
    with_sheet = any(channel.sheet != os.path.splitext(os.path.basename(channel.path))[0] for channel in channels)
    rows_up = max((channel.heading_row for channel in texts), default=-1) + 1
    chips = build_sample_chips(texts, apply_chip_cuts(resolve_chip_sources(rows_up, with_sheet), cuts))
    return SamplePreview(
        sheets=tuple(sheets), channels=tuple(channels), skipped_sheets=tuple(skipped), misfits=tuple(misfits),
        units=tuple(units), bare_amplitude_headers=tuple(dict.fromkeys(bare)),
        automatic_channel_type=determine_channel_type(first.unit, first.name) if first is not None else "",
        automatic_channel_unit=first.unit if first is not None else "", chips=chips)
