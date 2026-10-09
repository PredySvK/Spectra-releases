"""Tab-separated Imported results: rev/s followed by named amplitude columns."""

import os
import re

import numpy as np

from core.block_kinds import KIND_ORDER_CUT, STEP_READ
from core.data_block import Acquisition, NVHDataBlock, Provenance
from core.models import FUNC_TYPE_ORDER_FUNCTION, ChannelMetadata, MeasurementRunIndex
from core.units import determine_channel_type


_CHANNEL_HEADER = re.compile(r"^\s*(.+?)\s+\(([^()]+)\)\s*$")
# The filename convention is deliberately confined to this reader.
_ORDER_SUFFIX = re.compile(r"_H(\d+(?:\.\d+)?)$", re.IGNORECASE)

META_RECORDED_AXIS_UNIT = "recorded_axis_unit"


def _resolve_value_unit(recorded_unit: str) -> str:
    # Display only, to match MASTA's "m/s²"; unit compatibility already treats
    # both spellings alike (core.units.sanitize_unit_string).
    return "m/s²" if recorded_unit == "m/s2" else recorded_unit


def _read_header(stream) -> list[tuple[str, str]]:
    cells = stream.readline().strip().split("\t")
    if len(cells) < 2 or cells[0].strip() != "(rev/s)":
        raise ValueError("Not a processed-measurement header.")
    channels = []
    for cell in cells[1:]:
        match = _CHANNEL_HEADER.fullmatch(cell)
        if match is None:
            raise ValueError("Expected a channel name followed by its unit in parentheses.")
        channels.append((match.group(1).strip(), match.group(2).strip()))
    return channels


def is_processed_measurement_file(file_path: str) -> bool:
    """Recognise only the format's header; unrelated text is silently ignored."""
    try:
        with open(file_path, encoding="utf-8-sig") as stream:
            _read_header(stream)
    except (OSError, UnicodeError, ValueError):
        return False
    return True


class AccReaderProcessedMeasurement:
    """Read finished order curves, without claiming a waveform or DSP settings."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def scan_file_structure(self) -> MeasurementRunIndex:
        return MeasurementRunIndex(os.path.basename(self.file_path), self.file_path)

    def _read_columns(self):
        with open(self.file_path, encoding="utf-8-sig") as stream:
            channels = _read_header(stream)
            rows = [line.split("\t") for line in stream if line.strip()]
        if any(len(row) != len(channels) + 1 for row in rows):
            raise ValueError("Data column count does not match the processed-measurement header.")
        matrix = np.asarray(rows, dtype=np.float64).reshape(-1, len(channels) + 1)
        return channels, matrix

    def load_channels_on_demand(self, run_index: MeasurementRunIndex):
        if run_index.available_channels:
            return
        channels, matrix = self._read_columns()
        for index, (name, recorded_unit) in enumerate(channels):
            unit = _resolve_value_unit(recorded_unit)
            meta = ChannelMetadata(index, name, determine_channel_type(unit, name), unit)
            meta.func_type = FUNC_TYPE_ORDER_FUNCTION
            meta.block_kind = KIND_ORDER_CUT
            meta.num_pts = len(matrix)
            meta.ordinate_axis_units_lab = recorded_unit
            run_index.add_channel_metadata(f"Col #{index}: {name}", meta)

    def read_single_channel_data(self, dataset_index: int) -> NVHDataBlock:
        channels, matrix = self._read_columns()
        if not 0 <= dataset_index < len(channels):
            raise IndexError(f"Channel index {dataset_index} is not a processed-measurement channel.")
        name, unit = channels[dataset_index]
        order = _ORDER_SUFFIX.search(os.path.splitext(os.path.basename(self.file_path))[0])
        return NVHDataBlock.order_cut(
            name=name, values=matrix[:, dataset_index + 1], rpm=matrix[:, 0] * 60,
            order=float(order.group(1)) if order else None,
            value_unit=_resolve_value_unit(unit), processing=None,
            acquisition=Acquisition(num_pts=len(matrix), recorded_unit=unit),
            provenance=Provenance(step=STEP_READ),
            metadata={META_RECORDED_AXIS_UNIT: "rev/s"},
        )
