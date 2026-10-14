"""
ANSYS harmonic-response CSV reader: one node's response to an unbalance load,
read as a first-order Imported result (§1.134).

One file per Design point and node, written by the user's export script:

    DP<n>_Freq_Resp_<channel>.csv       -> channel "<channel>", design_point "DP<n>"
    "Frequency [Hz],Amplitude [mm/s˛]"  (every line may be wrapped in quotes)
    "10.,1.8202e-002"

The unbalance force m·e·ω² acts at the rotation frequency, so the curve is
order 1 against rpm = 60 · f. The file's amplitude is returned as it is; DataAccessor turns it into RMS
(Source amplitude), so the conversion lives in one place.
"""

import os
import re
from typing import List, Tuple

import numpy as np

from core.block_kinds import KIND_ORDER_CUT, STEP_READ
from core.data_block import Acquisition, NVHDataBlock, Provenance
from core.models import FUNC_TYPE_ORDER_FUNCTION, ChannelMetadata, MeasurementRunIndex
from core.units import determine_channel_type

# Fixed on purpose: the export script is fixed. A configurable pattern is the
# import wizard's job (ROADMAP B14).
_FILE_NAME_RE = re.compile(r"^(DP\d+)_Freq_Resp_(.+)\.csv$", re.IGNORECASE)
_AMPLITUDE_HEADER_RE = re.compile(r"^Amplitude \[([^\]]*)\]$")
_FREQUENCY_HEADER = "Frequency [Hz]"
_ORDER = 1.0


def _split_line(line: str) -> List[str]:
    line = line.strip()
    if len(line) >= 2 and line[0] == line[-1] == '"':
        line = line[1:-1]
    return [cell.strip() for cell in line.split(",")]


def _read_unit(header_line: str) -> str:
    """The amplitude unit, or ValueError for any other header."""
    cells = _split_line(header_line)
    match = _AMPLITUDE_HEADER_RE.match(cells[1]) if len(cells) == 2 else None
    if cells[0] != _FREQUENCY_HEADER or match is None:
        raise ValueError("Not an ANSYS harmonic-response header.")
    return match.group(1).strip().replace("˛", "²")   # The script writes ² as ˛.


def _read_file(file_path: str) -> Tuple[str, np.ndarray]:
    """(unit, n×2 array of frequency, peak amplitude); rows that are not two numbers are dropped."""
    with open(file_path, encoding="utf-8-sig") as stream:
        unit = _read_unit(stream.readline())
        pairs = []
        for line in stream:
            cells = _split_line(line)
            if len(cells) != 2:
                continue
            try:
                pairs.append((float(cells[0]), float(cells[1])))
            except ValueError:
                continue
    return unit, np.asarray(pairs, dtype=np.float64).reshape(-1, 2)


def is_ansys_file(file_path: str) -> bool:
    """Whether the name and header are an ANSYS harmonic response's. Any failure to read it is a no."""
    if _FILE_NAME_RE.match(os.path.basename(file_path)) is None:
        return False
    try:
        with open(file_path, encoding="utf-8-sig") as stream:
            _read_unit(stream.readline())
    except (OSError, UnicodeError, ValueError):
        return False
    return True


def _resolve_name(file_path: str) -> Tuple[str, str]:
    """(design point, channel name) from the file name."""
    design_point, channel = _FILE_NAME_RE.match(os.path.basename(file_path)).groups()
    return design_point.upper(), channel


class AccReaderAnsys:
    """Parser for ANSYS harmonic-response CSVs; the whole file is one channel."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def scan_file_structure(self) -> MeasurementRunIndex:
        return MeasurementRunIndex(os.path.basename(self.file_path), self.file_path)

    def load_channels_on_demand(self, run_index: MeasurementRunIndex):
        if run_index.available_channels:
            return
        design_point, name = _resolve_name(self.file_path)
        unit, pairs = _read_file(self.file_path)
        meta = ChannelMetadata(index=0, name=name,
                               channel_type=determine_channel_type(unit, name), unit=unit)
        meta.func_type = FUNC_TYPE_ORDER_FUNCTION
        meta.block_kind = KIND_ORDER_CUT
        meta.num_pts = len(pairs)
        meta.design_point = design_point
        run_index.add_channel_metadata(f"Col #0: {name}", meta)

    def read_single_channel_data(self, dataset_index: int) -> NVHDataBlock:
        """A finished order_cut block in the file's own amplitude; DataAccessor adds where it came
        from and its channel type, and converts the Source amplitude to RMS."""
        if dataset_index != 0:
            raise IndexError(
                f"Channel index {dataset_index} is not a channel of {os.path.basename(self.file_path)}.")
        _, name = _resolve_name(self.file_path)
        unit, pairs = _read_file(self.file_path)
        return NVHDataBlock.order_cut(
            name=name, values=pairs[:, 1], rpm=pairs[:, 0] * 60, order=_ORDER,
            value_unit=unit, processing=None,
            acquisition=Acquisition(num_pts=len(pairs), recorded_unit=unit),
            provenance=Provenance(step=STEP_READ),
        )
