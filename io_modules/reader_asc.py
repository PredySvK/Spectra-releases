# =====================================================================
# FILE: io_modules/reader_asc.py
# =====================================================================
"""
High-performance Siemens Testlab ASCII (.asc) file reader.
Parses strict BEGIN/END metadata header blocks and intelligently handles
both explicit (Column 0) and implicit (Calculated) time vectors.
Returns RawChannel parts; DataAccessor assembles the finished NVHDataBlock,
because classifying a channel needs the unit/name knowledge one layer up.
All internal documentation strings are standardly written in English.
"""

import os
import re
import threading
from typing import Any, Optional

import numpy as np
from core.models import MeasurementRunIndex, ChannelMetadata
from core.data_block import Acquisition, RawChannel
from core.units import determine_channel_type
from io_modules.measurement_files import canonical_path, file_stamp


class _SingleSlotCache:
    """
    One (canonical_path, file_stamp) -> value slot, shared by every
    AccReaderAsc instance for one file's worth of derived data.

    Ticket #100: DataAccessor builds a fresh AccReaderAsc per channel
    (io_modules/data_accessor.py), so without this an N-channel .asc file
    reparses its whole text N times. Keyed by file_stamp() so a re-measured
    file is never served stale data; a miss (different file, or this file
    changed) just re-parses, same outcome as if the cache did not exist --
    it is derived and safe to drop at any time. Bounded to one entry because
    the common access pattern is "every channel of one file, one after
    another"; cross-file concurrency (quick_scan_directory's
    ThreadPoolExecutor) degrades to cache-miss-and-reparse rather than
    corrupt data, since the slot is only ever read under the lock and
    validated by its stamp before use.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._slot: Optional[tuple] = None  # (key, stamp, value)

    def get(self, key: str, stamp: dict) -> Optional[Any]:
        with self._lock:
            slot = self._slot
        if slot is not None and slot[0] == key and slot[1] == stamp:
            return slot[2]
        return None

    def set(self, key: str, stamp: dict, value: Any) -> None:
        with self._lock:
            self._slot = (key, stamp, value)

    def clear(self) -> None:
        with self._lock:
            self._slot = None


# Ticket #100: np.loadtxt's cost is dominated by splitting every row, not by
# how many columns usecols keeps (measured 2026-09-12: ~170 ms/channel either
# way on a 3-channel/30 MB file), and _parse_header_and_structure's line-count
# scan pays for re-reading the whole file regardless of the matrix cache
# (~45 ms on the same file). Two slots because they cache independent things
# at independent granularity (header fields vs. the decoded matrix).
_MATRIX_CACHE = _SingleSlotCache()   # value: the full np.ndarray (every column, time included)
_HEADER_CACHE = _SingleSlotCache()   # value: dict of the _HEADER_FIELDS below


def discard_asc_caches() -> None:
    """Forget the parsed file, so the next read parses it again (a Benchmark case starts cold)."""
    _MATRIX_CACHE.clear()
    _HEADER_CACHE.clear()


class AccReaderAsc:
    """
    Parser for Siemens Simcenter Testlab .asc text files.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._header_lines_count = 0
        self._start = 0.0
        self._delta = 0.0
        self._channel_names = []
        self._units = []
        self._has_explicit_time = False
        self._delimiter = None
        self._num_pts = 0

    def scan_file_structure(self) -> MeasurementRunIndex:
        """Registers the file envelope inside the workspace."""
        file_name = os.path.basename(self.file_path)
        return MeasurementRunIndex(file_name, self.file_path)

    _HEADER_FIELDS = (
        "_header_lines_count", "_start", "_delta", "_channel_names",
        "_units", "_has_explicit_time", "_delimiter", "_num_pts",
    )

    def _parse_header_and_structure(self):
        """Extracts metadata from the BEGIN...END block and sniffs data delimiters."""
        if self._header_lines_count > 0:
            return  # Prevent redundant parsing

        key = canonical_path(self.file_path)
        stamp = file_stamp(self.file_path)
        cached = _HEADER_CACHE.get(key, stamp)
        if cached is not None:
            for field in self._HEADER_FIELDS:
                setattr(self, field, cached[field])
            return

        self._scan_header_and_structure()
        _HEADER_CACHE.set(key, stamp, {field: getattr(self, field) for field in self._HEADER_FIELDS})

    def _scan_header_and_structure(self):
        """The actual BEGIN...END scan -- see _parse_header_and_structure for the cache wrapped around it."""
        in_header = False

        with open(self.file_path, 'r', encoding='utf-8') as f:
            for line_idx, line in enumerate(f):
                clean_line = line.strip()

                if clean_line == "BEGIN":
                    in_header = True
                    continue

                if clean_line == "END":
                    self._header_lines_count = line_idx + 1
                    in_header = False

                    # Sniff delimiter from the first non-empty data line and count
                    # non-empty rows for a truthful num_pts (BUGS.md N1/N2, #325) --
                    # the header carries no point count for this format, unlike
                    # UNV's num_pts/x-array, so the only honest way to know it
                    # is to count the data rows once during the scan. Trailing
                    # blank lines must not inflate num_pts.
                    first_data_line = None
                    data_rows_count = 0
                    for data_line in f:
                        stripped_data = data_line.strip()
                        if not stripped_data:
                            continue
                        if first_data_line is None:
                            first_data_line = stripped_data
                        data_rows_count += 1

                    self._delimiter = "," if (first_data_line and "," in first_data_line) else None
                    self._num_pts = data_rows_count
                    break

                if in_header:
                    if clean_line.startswith("START"):
                        self._start = float(clean_line.split("=")[1].strip())
                    elif clean_line.startswith("DELTA"):
                        self._delta = float(clean_line.split("=")[1].strip())
                    elif clean_line.startswith("RATE"):
                        rate = float(clean_line.split("=")[1].strip())
                        if rate > 0:
                            self._delta = 1.0 / rate
                    elif clean_line.startswith("CHANNELNAME"):
                        match = re.search(r"\[(.*?)\]", clean_line)
                        if match:
                            items = match.group(1).split(",")
                            self._channel_names = [x.strip(" '\"") for x in items]
                    elif clean_line.startswith("UNIT"):
                        match = re.search(r"\[(.*?)\]", clean_line)
                        if match:
                            items = match.group(1).split(",")
                            self._units = [x.strip(" '\"") for x in items]

        # Determine if the first column is an explicit Time vector
        if self._channel_names and self._channel_names[0].lower() in ['time', 'elap_time', 'time1', 'sec', 's']:
            self._has_explicit_time = True
        elif self._units and self._units[0].lower() in ['s', 'sec']:
            self._has_explicit_time = True
        else:
            self._has_explicit_time = False

    def load_channels_on_demand(self, run_index: MeasurementRunIndex):
        """
        Populates ChannelMetadata entities dynamically based on discovered columns in ASC file.
        """
        if run_index.available_channels:
            return

        self._parse_header_and_structure()

        # Skip the 0-th column if it's reserved purely for the Time axis
        start_col = 1 if self._has_explicit_time else 0

        # Create mapping entities for all valid data columns
        for i in range(start_col, len(self._channel_names)):
            ch_name = self._channel_names[i]
            ch_unit = self._units[i] if i < len(self._units) else "unknown"

            # One classification rule for all readers, shared with
            # apply_unit_overrides via core.units (audit 02 finding 7.4): the
            # hand-rolled copy here had no voltage branch at all and missed
            # Hz/rad/s tachos and mbar/bar microphones.
            ctype = determine_channel_type(ch_unit, ch_name)

            meta = ChannelMetadata(index=i, name=ch_name, channel_type=ctype, unit=ch_unit)
            meta.abscissa_inc = self._delta
            meta.abscissa_min = self._start
            meta.func_type = 1
            meta.num_pts = self._num_pts
            meta.sampling_rate = (1.0 / self._delta) if self._delta > 0 else 0.0
            meta.ordinate_axis_units_lab = ch_unit

            run_index.add_channel_metadata(f"Col #{i} [{ctype.upper()}]: {ch_name}", meta)

    def _load_full_matrix(self) -> np.ndarray:
        """
        The file's full numeric body (every column, time included if
        present), parsed once and shared with every other channel of this
        file via _MATRIX_CACHE -- see that module-level comment for why.
        """
        key = canonical_path(self.file_path)
        stamp = file_stamp(self.file_path)
        cached = _MATRIX_CACHE.get(key, stamp)
        if cached is not None:
            return cached

        try:
            matrix = np.loadtxt(
                self.file_path,
                delimiter=self._delimiter,
                skiprows=self._header_lines_count,
                max_rows=self._num_pts if self._num_pts > 0 else None,
            )
        except ValueError as exc:
            raise ValueError(
                f"Failed to parse numeric data in {os.path.basename(self.file_path)}: {exc}"
            ) from exc

        if self._num_pts == 0:
            n_cols = max(len(self._channel_names), 1)
            matrix = matrix.reshape(0, n_cols)
        elif self._num_pts == 1:
            # A single data row: loadtxt collapses to 0-D (1 column) or 1-D (N columns).
            # The number of parsed elements in that single row is its actual column count.
            actual_cols = matrix.size
            if self._channel_names:
                expected_cols = len(self._channel_names)
                if actual_cols != expected_cols:
                    raise ValueError(
                        f"Column count in {os.path.basename(self.file_path)} ({actual_cols}) "
                        f"does not match header channels ({expected_cols})."
                    )
            matrix = matrix.reshape(1, actual_cols)
        else:
            # Multiple data rows:
            if matrix.ndim == 1:
                # 1-D across multiple rows means loadtxt parsed exactly 1 column.
                actual_cols = 1
                if self._channel_names:
                    expected_cols = len(self._channel_names)
                    if actual_cols != expected_cols:
                        raise ValueError(
                            f"Column count in {os.path.basename(self.file_path)} ({actual_cols}) "
                            f"does not match header channels ({expected_cols})."
                        )
                matrix = matrix.reshape(-1, 1)
            else:
                if self._channel_names:
                    expected_cols = len(self._channel_names)
                    if matrix.shape[1] != expected_cols:
                        raise ValueError(
                            f"Column count in {os.path.basename(self.file_path)} ({matrix.shape[1]}) "
                            f"does not match header channels ({expected_cols})."
                        )

        _MATRIX_CACHE.set(key, stamp, matrix)
        return matrix

    def read_single_channel_data(self, dataset_index: int) -> RawChannel:
        # numpy would read a negative index as a column counted from the end
        # -- another sensor's data under the requested name (#379).
        if dataset_index < 0:
            raise IndexError(
                f"Channel index {dataset_index} is not a column of "
                f"{os.path.basename(self.file_path)}."
            )
        self._parse_header_and_structure()

        # np.loadtxt drops to 1-D for a single data row; the reshape in
        # _load_full_matrix keeps a one-sample file from failing "too many
        # indices" the way the old per-channel loadtxt call once did (audit
        # 02 finding 5.9).
        matrix = self._load_full_matrix()

        if self._has_explicit_time:
            time_arr = matrix[:, 0].astype(np.float64)
            data_arr = matrix[:, dataset_index].astype(np.float64)
        else:
            data_arr = np.atleast_1d(matrix[:, dataset_index]).astype(np.float64)
            time_arr = (np.arange(len(data_arr)) * self._delta + self._start).astype(np.float64)

        # DC Offset removal logic is strictly removed from I/O layer.

        block_name = self._channel_names[dataset_index] if dataset_index < len(
            self._channel_names) else f"Channel_{dataset_index}"
        y_axis_unit = self._units[dataset_index] if dataset_index < len(self._units) else "unknown"

        return RawChannel(
            name=block_name,
            values=data_arr,
            times=time_arr,
            acquisition=Acquisition(
                dt=self._delta,
                abscissa_min=self._start,
                num_pts=len(data_arr),
                recorded_unit=y_axis_unit,
            ),
        )

