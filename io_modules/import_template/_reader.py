"""
A table file (.xlsx, .txt, .csv) read by an Import template, as an Imported result
-- or, for a time signal, as a waveform.

The reader protocol is the one every reader keeps (MeasurementReader): channels
are listed at scan, a channel is read on demand as a finished block of the
template's data kind (order cut, spectrum, Overall Level or order residual,
none with a SpectralProcessing) in the file's own amplitude (DataAccessor
converts the Source amplitude).

What a template finds in a file is `build_template_reading` (_table.py), the
same call the import wizard's preview makes. A channel the template cannot
name, order or unit makes the file unreadable at scan, so a misfit never
reaches the pool half read. A row of a channel that is not two numbers is a
Lost part (§1.177). The channel index is its number across the read sheets.

A time signal is no Imported result: its channels are read like a `.unv` one
(RawChannel, no Source amplitude), carry their sample rate, and the channel
the template names as speed is a tacho.
"""

import fnmatch
import functools
import os
from typing import List, Union

import numpy as np

from core.block_kinds import (
    KIND_ORDER_CUT, KIND_ORDER_RESIDUAL, KIND_OVERALL_LEVEL, KIND_SPECTRUM, STEP_READ,
)
from core.data_block import Acquisition, NVHDataBlock, Provenance, RawChannel
from core.import_template import (
    DATA_KIND_ORDER_CUT, DATA_KIND_ORDER_RESIDUAL, DATA_KIND_OVERALL_LEVEL, DATA_KIND_SPECTRUM,
    DATA_KIND_TIME_SIGNAL, ImportTemplate,
)
from core.models import FUNC_TYPE_ORDER_FUNCTION, ChannelMetadata, MeasurementRunIndex
from io_modules.import_template._metadata import resolve_template_field_key
from io_modules.import_template._table import (
    TemplateReading, build_template_reading, build_text_format, read_workbook, resolve_head_row_count, resolve_read_sheets,
    resolve_linear_values, resolve_x_factor,
)
from io_modules.measurement_files import file_stamp
from io_modules.number_pairs import build_lost_rows_part


_BLOCK_KIND = {
    DATA_KIND_ORDER_CUT: KIND_ORDER_CUT,
    DATA_KIND_SPECTRUM: KIND_SPECTRUM,
    DATA_KIND_OVERALL_LEVEL: KIND_OVERALL_LEVEL,
    DATA_KIND_ORDER_RESIDUAL: KIND_ORDER_RESIDUAL,
}


@functools.lru_cache(maxsize=2)
def _reading_cached(path: str, _mtime_ns: int, _size: int, template: ImportTemplate) -> TemplateReading:
    """Read once per file stamp and template: DataAccessor opens a fresh reader per channel."""
    return _read(path, template)


def _sheets_of(template: ImportTemplate):
    """What `read_workbook` takes to read the sheets the template's sheet rule picks."""
    return lambda names: resolve_read_sheets(names, template)


def _read(path: str, template: ImportTemplate) -> TemplateReading:
    return build_template_reading(read_workbook(path, _sheets_of(template), text_format=build_text_format(template)), template)


def _reading_of(file_path: str, template: ImportTemplate) -> TemplateReading:
    stamp = file_stamp(file_path)
    if stamp is None:
        return _read(file_path, template)
    # The path as spelled, not canonical_path: a template reads metadata out of
    # the file and folder names, which the canonical form has lowercased on Windows.
    return _reading_cached(file_path, stamp["mtime_ns"], stamp["size"], template)


def discard_import_template_caches() -> None:
    """Forget the read workbook, so the next read parses it again."""
    _reading_cached.cache_clear()


def resolve_template_name_fit(file_path: str, template: ImportTemplate) -> bool:
    """Whether the file's name fits the template's name pattern. No disk access."""
    return fnmatch.fnmatch(os.path.basename(file_path).lower(), template.file_pattern.lower())


def read_template_misfit_reason(file_path: str, template: ImportTemplate) -> str:
    """
    Why the file's content does not fit the template, blank when it does: the
    same reading as the scan's, of only the head of the sheets (a read sheet is
    missing, has no heading row, its heading row forms no channel, or a
    channel's header or the file's metadata does not fit). Any failure to read
    it is a misfit.
    """
    max_row = resolve_head_row_count(template)
    try:
        workbook = read_workbook(file_path, _sheets_of(template), max_row=max_row,
                                 text_format=build_text_format(template))
    except Exception as error:
        return f"cannot be read as a workbook ({error})"
    return build_template_reading(workbook, template).first_problem()


def read_template_candidates(directory: str, templates) -> List[str]:
    """The files directly in `directory` whose names fit any of the templates' patterns, sorted."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return sorted(os.path.join(directory, name) for name in names
                  if os.path.isfile(os.path.join(directory, name))
                  and any(resolve_template_name_fit(name, template) for template in templates))


def read_template_match(file_path: str, template: ImportTemplate) -> bool:
    """Whether the file's name fits the template's pattern and its header holds the anchor."""
    return resolve_template_name_fit(file_path, template) and not read_template_misfit_reason(file_path, template)


class AccReaderImportTemplate:
    """Parser for table files described by an Import template; one channel per column group."""

    def __init__(self, file_path: str, template: ImportTemplate):
        self.file_path = file_path
        self.template = template

    def read_run_index(self) -> MeasurementRunIndex:
        """The file's channels and Lost parts, read from its header (MeasurementReader)."""
        run_index = MeasurementRunIndex(os.path.basename(self.file_path), self.file_path)
        self._read_channels(run_index)
        return run_index

    def _read_channels(self, run_index: MeasurementRunIndex) -> None:
        for channel in self._reading().channels:
            meta = ChannelMetadata(index=channel.index, name=channel.name,
                                   channel_type=channel.channel_type, unit=channel.unit)
            if self.template.data_kind == DATA_KIND_TIME_SIGNAL:
                times = np.asarray(channel.pairs.pairs, dtype=np.float64).reshape(-1, 2)[:, 0]
                meta.abscissa_min = float(times[0]) * resolve_x_factor(self.template.data_kind, channel.x_unit)
                meta.abscissa_inc = 1.0 / channel.sample_rate
                meta.sampling_rate = channel.sample_rate
            else:
                meta.func_type = FUNC_TYPE_ORDER_FUNCTION
                meta.block_kind = _BLOCK_KIND[self.template.data_kind]
                meta.source_amplitude = channel.source_amplitude
            meta.num_pts = len(channel.pairs.pairs)
            meta.import_template = self.template.name
            for field, value in channel.metadata:
                setattr(meta, resolve_template_field_key(field), value)
            lost_part = build_lost_rows_part(channel.index, channel.pairs.lost_rows)
            if lost_part is not None:
                run_index.lost_parts.append(lost_part)
            run_index.add_channel_metadata(f"Col #{channel.index}: {channel.name}", meta)

    def read_single_channel_data(self, dataset_index: int) -> Union[RawChannel, NVHDataBlock]:
        channels = self._reading().channels
        if not 0 <= dataset_index < len(channels):
            raise IndexError(
                f"Channel index {dataset_index} is not a channel of {os.path.basename(self.file_path)}.")
        channel = channels[dataset_index]
        pairs = np.asarray(channel.pairs.pairs, dtype=np.float64).reshape(-1, 2)
        x = pairs[:, 0] * resolve_x_factor(self.template.data_kind, channel.x_unit)
        kind = self.template.data_kind
        if kind == DATA_KIND_TIME_SIGNAL:
            return RawChannel(
                name=channel.name, values=pairs[:, 1], times=x,
                acquisition=Acquisition(dt=1.0 / channel.sample_rate, abscissa_min=float(x[0]),
                                        num_pts=len(pairs), recorded_unit=channel.unit))
        common = dict(name=channel.name, values=resolve_linear_values(channel), value_unit=channel.unit, processing=None,
                      acquisition=Acquisition(num_pts=len(pairs), recorded_unit=channel.unit),
                      provenance=Provenance(step=STEP_READ))
        if kind == DATA_KIND_ORDER_CUT:
            return NVHDataBlock.order_cut(rpm=x, order=channel.order, **common)
        if kind == DATA_KIND_SPECTRUM:
            return NVHDataBlock.spectrum(frequencies=x, **common)
        if kind == DATA_KIND_ORDER_RESIDUAL:
            return NVHDataBlock.order_residual(rpm=x, **common)
        return NVHDataBlock.read_overall_level(
            rpm=x, **{key: value for key, value in common.items() if key != "processing"})

    def _reading(self) -> TemplateReading:
        """What the template reads in the file; ValueError naming the template when it does not fit."""
        reading = _reading_of(self.file_path, self.template)
        problem = reading.first_problem()
        if problem:
            raise ValueError(f"{os.path.basename(self.file_path)} does not fit the Import template "
                             f"'{self.template.name}': {problem}.")
        return reading

