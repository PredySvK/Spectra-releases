"""
MASTA result (.xlsx) reader: order amplitude against speed per housing
location and axis, read as an Imported result (§1.134).

Layout of the first sheet -- every channel is a pair of columns, each with its
own speed column, because MASTA's speed steps are not shared between pairs:

    row 1  "<axis>, At housing: <design>\\<location>"     -> name "<location>:<axis>"
    row 2  result type, damping included, "... Order <n>-Damping = ..."
    row 3  scenario
    row 4  "Speed (rev/min)" | "Amplitude (<unit>)"
    row 5+ rpm | amplitude, either of them possibly stored as text

The header is Raw metadata of each channel, read at scan: design, scenario,
damping and description_1..N (row 2's comma segments left once the Order and
Damping keywords are taken out). The order goes to the block, not a facet.
"""

import os
import re
from typing import List, Optional, Tuple

import numpy as np

from core.block_kinds import KIND_ORDER_CUT, STEP_READ
from core.data_block import Acquisition, NVHDataBlock, Provenance
from core.models import FUNC_TYPE_ORDER_FUNCTION, ChannelMetadata, MeasurementRunIndex
from core.units import determine_channel_type

_HEADER_ROWS = 4
_LOCATION_RE = re.compile(r"^\s*([XYZ])\s*,.*\\([^\\]+?)\s*$")
_DESIGN_RE = re.compile(r"At housing:\s*(.*)\\")
_SPEED_HEADER = "speed (rev/min)"
_UNIT_RE = re.compile(r"\(([^)]*)\)\s*$")
_ORDER_RE = re.compile(r"\bOrder\s+(\d+(?:\.\d+)?)")
_DAMPING_RE = re.compile(r"\bDamping\s*=\s*([^\s,]+)")
_SEGMENT_EDGES = " \t-–:;"


def _parse_result_type(text: str) -> Tuple[Optional[float], str, List[str]]:
    """Row 2 as (order, damping, descriptions); a missing keyword is None / ""."""
    order_match = _ORDER_RE.search(text)
    damping_match = _DAMPING_RE.search(text)
    descriptions = []
    for segment in text.split(","):
        segment = _DAMPING_RE.sub("", _ORDER_RE.sub("", segment)).strip(_SEGMENT_EDGES)
        if segment:
            descriptions.append(segment)
    return (float(order_match.group(1)) if order_match else None,
            damping_match.group(1) if damping_match else "",
            descriptions)


def _read_rows(file_path: str, max_row: Optional[int] = None) -> List[tuple]:
    import openpyxl
    workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    try:
        return list(workbook.worksheets[0].iter_rows(max_row=max_row, values_only=True))
    finally:
        workbook.close()


def is_masta_file(file_path: str) -> bool:
    """Whether the workbook's header is a MASTA result's. Any failure to read it is a no."""
    try:
        rows = _read_rows(file_path, max_row=_HEADER_ROWS)
    except Exception:
        return False
    return (len(rows) == _HEADER_ROWS and bool(rows[0]) and bool(rows[3])
            and _LOCATION_RE.match(str(rows[0][0] or "")) is not None
            and str(rows[3][0] or "").strip().lower() == _SPEED_HEADER)


def _parse_number(cell) -> Optional[float]:
    """A cell as a number, or None for a blank or a non-number (a footer, a note)."""
    if isinstance(cell, str):
        cell = cell.strip()
        if "," in cell and "." not in cell:
            cell = cell.replace(",", ".")   # Number stored as text with a decimal comma.
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def _resolve_channel_indices(rows) -> List[int]:
    """Column pairs headed by a housing location; a stray trailing column is not a channel."""
    return [index for index in range(len(rows[0]) // 2)
            if _LOCATION_RE.match(str(rows[0][2 * index] or "")) is not None]


class AccReaderMasta:
    """Parser for MASTA result workbooks; one channel per (location, axis) column pair."""

    def __init__(self, file_path: str):
        self.file_path = file_path

    def scan_file_structure(self) -> MeasurementRunIndex:
        return MeasurementRunIndex(os.path.basename(self.file_path), self.file_path)

    def load_channels_on_demand(self, run_index: MeasurementRunIndex):
        if run_index.available_channels:
            return
        rows = _read_rows(self.file_path)
        for index in _resolve_channel_indices(rows):
            name, unit = self._resolve_name_and_unit(rows, index)
            meta = ChannelMetadata(index=index, name=name,
                                   channel_type=determine_channel_type(unit, name), unit=unit)
            meta.func_type = FUNC_TYPE_ORDER_FUNCTION
            meta.block_kind = KIND_ORDER_CUT
            meta.num_pts = len(self._read_pairs(rows, index))
            design_match = _DESIGN_RE.search(str(rows[0][2 * index]))
            meta.design = design_match.group(1).strip() if design_match else ""
            meta.scenario = str(rows[2][2 * index] or "").strip()
            _, meta.damping, descriptions = _parse_result_type(str(rows[1][2 * index] or ""))
            for number, description in enumerate(descriptions, start=1):
                setattr(meta, f"description_{number}", description)
            run_index.add_channel_metadata(f"Col #{index}: {name}", meta)

    @staticmethod
    def _resolve_name_and_unit(rows, index: int):
        axis, location = _LOCATION_RE.match(str(rows[0][2 * index])).groups()
        unit_match = _UNIT_RE.search(str(rows[3][2 * index + 1] or ""))
        return f"{location}:{axis}", (unit_match.group(1).strip() if unit_match else "unknown")

    @staticmethod
    def _read_pairs(rows, index: int) -> List[tuple]:
        """(rpm, amplitude) of one channel; a pair ends where its columns run out."""
        pairs = []
        for row in rows[_HEADER_ROWS:]:
            cells = row[2 * index: 2 * index + 2]
            if len(cells) < 2:
                continue
            rpm, amplitude = _parse_number(cells[0]), _parse_number(cells[1])
            if rpm is not None and amplitude is not None:
                pairs.append((rpm, amplitude))
        return pairs

    def read_single_channel_data(self, dataset_index: int) -> NVHDataBlock:
        """
        A finished order_cut block, not a RawChannel: a RawChannel is a
        waveform. DataAccessor still adds where it came from and its channel type.
        """
        rows = _read_rows(self.file_path)
        if dataset_index not in _resolve_channel_indices(rows):
            raise IndexError(
                f"Channel index {dataset_index} is not a channel of {os.path.basename(self.file_path)}.")
        name, unit = self._resolve_name_and_unit(rows, dataset_index)
        pairs = np.asarray(self._read_pairs(rows, dataset_index), dtype=np.float64).reshape(-1, 2)
        order, _, _ = _parse_result_type(str(rows[1][2 * dataset_index] or ""))
        return NVHDataBlock.order_cut(
            name=name, values=pairs[:, 1], rpm=pairs[:, 0], order=order,
            value_unit=unit, processing=None,
            acquisition=Acquisition(num_pts=len(pairs), recorded_unit=unit),
            provenance=Provenance(step=STEP_READ),
        )
