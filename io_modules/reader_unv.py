# =====================================================================
# FILE: io_modules/reader_unv.py
# =====================================================================
"""
Universal File Format (.unv) reader compliant with the SDRC/Siemens 58 standard.
Extracts deep physical hardware variables from dataset headers.
Returns RawChannel parts; DataAccessor assembles the finished NVHDataBlock,
because classifying a channel needs the unit/name knowledge one layer up.
"""

import os
from dataclasses import dataclass

import pyuff
import numpy as np

from core.models import (
    FUNC_TYPE_TIME_RESPONSE, ChannelMetadata, MeasurementRunIndex, is_time_response,
)
from core.data_block import Acquisition, RawChannel
from core.units import determine_channel_type

# Every func_type other than FUNC_TYPE_TIME_RESPONSE (spectra, correlations,
# FRFs, ...) has an abscissa that is not seconds, so treating it as one would
# silently derive a bogus sampling rate.


@dataclass(frozen=True)
class _Fast58bOffset:
    """Everything _read_via_fast_path needs to seek/decode one 58b dataset without reopening pyuff."""
    data_offset: int
    n_bytes: int
    byte_order: int
    ord_data_type: int
    num_pts: int
    abscissa_min: float
    abscissa_inc: float
    raw_unit: str
    name: str
    rsp_node: int
    rsp_dir: int
    ref_node: int
    ref_dir: int
    func_type: int


# UFF58 header records are fixed-width Fortran records, not whitespace-separated:
# a blank or multi-word text field (entity name, axis label) shifts every field
# after it under str.split() (issue #323). Widths match pyuff's own reader.
_RECORD6_WIDTHS = (5, 10, 5, 10, 11, 10, 4, 11, 10, 4)  # 2(I5,I10),2(1X,A10,2I10,I4)
_RECORD10_WIDTHS = (10, 5, 5, 5, 21, 21)                 # I10,3I5,2(1X,A20)


def _split_fixed_width(line: bytes, widths) -> list:
    """Cut one header record into its stripped text fields by column."""
    text = line.decode("latin1", errors="replace").rstrip("\r\n")
    fields, start = [], 0
    for width in widths:
        fields.append(text[start:start + width].strip())
        start += width
    return fields


def _int_or(field: str, default: int) -> int:
    try:
        return int(field)
    except ValueError:
        return default


class AsciiDataset58Encountered(Exception):
    """
    Raised internally when a dataset tag is "58" (ASCII) rather than "58b"
    (binary). The ASCII body carries no byte count in its header, so it can't
    be skip-seeked past the way 58b can -- bailing out to the pyuff fallback
    for the whole file is simpler and safer than re-implementing the ASCII
    58 record scanner here (ticket #100 only targets the binary path, which
    is what every file in this project's datasets actually uses).
    """


class AccReaderUnv:
    """
    UNV reader with a zero-copy binary fast path for Dataset 58b (real data,
    evenly-spaced abscissa, IEEE754) -- measured 2026-09-12 on a 17-channel /
    124.5 MB real file: header scan 328 ms -> 0.5 ms, per-channel read 263 ms
    -> ~5 ms (see docs/ARCHITECTURE_DECISIONS.md, ticket #100). Every other
    dataset 58 layout (ASCII, complex ordinate data, uneven abscissa spacing)
    falls back to the original pyuff-based parse, so a file this reader has
    never been validated against degrades to the previous, already-correct
    behaviour rather than risk a silent mis-parse.
    """

    # UFF58 Record 7 Field 1 (ord_data_type): the fast path only decodes real
    # data (2=single, 4=double). Complex (5,6) interleaves real/imaginary
    # floats and needs a different np.frombuffer stride -- see
    # pyuff.datasets.dataset_58._extract58 for the full 8-case table.
    _REAL_ORD_DATA_TYPES = {2: 4, 4: 8}  # ord_data_type -> bytes per sample

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._dataset_offsets = {}  # set_idx -> fast-path read descriptor
        self._scanned = False

    def scan_file_structure(self) -> MeasurementRunIndex:
        file_name = os.path.basename(self.file_path)
        return MeasurementRunIndex(file_name, self.file_path)

    def load_channels_on_demand(self, run_index: MeasurementRunIndex):
        if run_index.available_channels:
            return

        try:
            self._fast_scan_headers(run_index)
            self._scanned = True
        except Exception as e:
            # Safe fallback: any dataset 58 layout the fast scanner does not
            # recognise (ASCII, or a malformed/unexpected header) re-parses
            # the whole file through pyuff exactly as before this ticket.
            print(f"FAST_SCAN_FALLBACK: Falling back to pyuff for {run_index.file_name}: {e}")
            run_index.available_channels.clear()
            self._dataset_offsets = {}
            self._load_channels_via_pyuff(run_index)
            self._scanned = True

    def _ensure_scanned(self):
        """
        Populates self._dataset_offsets without touching a MeasurementRunIndex.

        DataAccessor.fetch_channel_data builds a fresh AccReaderUnv per
        channel read (io_modules/data_accessor.py) -- load_channels_on_demand
        is not guaranteed to have run on this instance -- so
        read_single_channel_data must be able to populate the fast-path offset
        map on its own. A failed scan just leaves the map empty: every read
        then falls back to pyuff per dataset, identical to pre-#100 behaviour.
        """
        if self._scanned:
            return
        self._scanned = True
        try:
            self._fast_scan_headers(None)
        except Exception:
            self._dataset_offsets = {}

    def _fast_scan_headers(self, run_index):
        """
        Streams the file once, locating each dataset 58 block by its '-1'
        delimiters without loading the binary payload -- only 58b headers
        (11 fixed ASCII lines) are read; the payload is skipped via seek().

        `run_index` is optional: load_channels_on_demand wants channel
        metadata registered, read_single_channel_data (via _ensure_scanned)
        only wants the byte-offset map and skips that work.
        """
        with open(self.file_path, "rb") as f:
            set_idx = 0
            while True:
                line = f.readline()
                if not line:
                    break
                if line.strip() != b"-1":
                    continue

                type_line = f.readline()
                if not type_line:
                    break
                type_parts = type_line.split()
                if not type_parts:
                    continue

                tag = type_parts[0].decode("latin1", errors="replace")
                if tag == "58b":
                    set_idx = self._scan_one_58b(f, type_parts, set_idx, run_index)
                elif tag.startswith("58"):
                    # ASCII dataset 58: no byte count in its header, so it
                    # can't be skip-seeked -- bail out to the whole-file
                    # pyuff fallback rather than silently drop this channel.
                    raise AsciiDataset58Encountered(f"ASCII dataset 58 at set #{set_idx}")
                else:
                    # Non-58 dataset (e.g. 151, 164): skip to its delimiter.
                    set_idx += 1
                    while True:
                        cur = f.readline()
                        if not cur or cur.strip() == b"-1":
                            break

    def _scan_one_58b(self, f, type_parts, set_idx, run_index) -> int:
        byte_order = int(type_parts[1])  # 1 = little endian (<), 2 = big endian (>)
        fp_fmt = int(type_parts[2])      # 2 = IEEE 754 float
        n_ascii = int(type_parts[3])     # typically 11
        n_bytes = int(type_parts[4])

        header_lines = [f.readline() for _ in range(n_ascii)]
        data_offset = f.tell()

        id1 = header_lines[0].decode("latin1", errors="replace").strip()
        id5 = header_lines[4].decode("latin1", errors="replace").strip()
        if not id5:
            id5 = f"Dataset_{set_idx}"

        l7_fields = _split_fixed_width(header_lines[5], _RECORD6_WIDTHS)
        func_type_code = _int_or(l7_fields[0], 1)
        rsp_node = _int_or(l7_fields[5], 0)
        rsp_dir = _int_or(l7_fields[6], 0)
        ref_node = _int_or(l7_fields[8], 0)
        ref_dir = _int_or(l7_fields[9], 0)

        l8_parts = header_lines[6].split()
        ord_data_type = int(l8_parts[0])
        num_pts = int(l8_parts[1])
        abscissa_spacing = int(l8_parts[2])
        abscissa_min = float(l8_parts[3])
        abscissa_inc = float(l8_parts[4])

        # Ordinate units label: the same field pyuff returns as ordinate_axis_units_lab.
        raw_unit = _split_fixed_width(header_lines[8], _RECORD10_WIDTHS)[5]

        if run_index is not None:
            unique_name = f"Set #{set_idx}: {id1}" if id1 else f"Set #{set_idx}: {id5}"
            channel_type = "tacho" if func_type_code == 5 else determine_channel_type(raw_unit, id1)

            meta = ChannelMetadata(
                index=set_idx, name=id1 if id1 else id5, channel_type=channel_type, unit=raw_unit,
            )
            meta.func_type = func_type_code
            meta.abscissa_inc = abscissa_inc
            meta.abscissa_min = abscissa_min
            meta.sampling_rate = (1.0 / abscissa_inc) if abscissa_inc > 0 else 0.0
            meta.num_pts = num_pts
            meta.id1 = id1
            meta.id2 = header_lines[1].decode("latin1", errors="replace").strip()
            meta.id3 = header_lines[2].decode("latin1", errors="replace").strip()
            meta.id4 = header_lines[3].decode("latin1", errors="replace").strip()
            meta.id5 = id5
            meta.ordinate_axis_units_lab = raw_unit
            meta.rsp_node = rsp_node
            meta.rsp_dir = rsp_dir
            meta.ref_node = ref_node
            meta.ref_dir = ref_dir

            run_index.add_channel_metadata(unique_name, meta)

        # Store a fast read descriptor only for the one layout this parser
        # actually decodes correctly (real data, even abscissa spacing,
        # IEEE754). Complex data (5/6), uneven spacing (abscissa_spacing==0,
        # which stores X/Y pairs instead of plain Y values) or a byte count
        # that doesn't match num_pts*itemsize all get left out of
        # _dataset_offsets -- read_single_channel_data then transparently
        # falls back to pyuff.read_sets for just that one dataset.
        itemsize = self._REAL_ORD_DATA_TYPES.get(ord_data_type)
        layout_ok = (
            fp_fmt == 2
            and itemsize is not None
            and abscissa_spacing == 1
            and n_bytes == num_pts * itemsize
        )
        if layout_ok:
            self._dataset_offsets[set_idx] = _Fast58bOffset(
                data_offset=data_offset, n_bytes=n_bytes, byte_order=byte_order,
                ord_data_type=ord_data_type, num_pts=num_pts,
                abscissa_min=abscissa_min, abscissa_inc=abscissa_inc,
                raw_unit=raw_unit, name=id1 or id5,
                rsp_node=rsp_node, rsp_dir=rsp_dir, ref_node=ref_node, ref_dir=ref_dir,
                func_type=func_type_code,
            )

        # Skip the binary payload and consume the closing "-1" delimiter.
        f.seek(data_offset + n_bytes)
        f.readline()
        return set_idx + 1

    def _load_channels_via_pyuff(self, run_index: MeasurementRunIndex):
        uff = pyuff.UFF(self.file_path)
        try:
            datasets = uff.get_set_types()
        except Exception as e:
            print(f"LAZY_PARSE_ERROR: Failed to enumerate datasets in {run_index.file_name}: {str(e)}")
            return

        # Each dataset is parsed independently: one malformed header must not silently
        # drop every channel after it, which would read as "the file only has N
        # channels" instead of "the parser choked partway through".
        for idx, ds_type in enumerate(datasets):
            ds_str = str(ds_type).strip()
            if not ds_str.startswith('58'):
                continue
            try:
                ds_header = uff.read_sets(setn=idx, header_only=True)

                id1 = str(ds_header.get('id1', '')).strip()
                id2 = str(ds_header.get('id2', '')).strip()
                id3 = str(ds_header.get('id3', '')).strip()
                id4 = str(ds_header.get('id4', '')).strip()
                id5 = str(ds_header.get('id5', f'Dataset_{idx}')).strip()

                unique_name = f"Set #{idx}: {id1}" if id1 else f"Set #{idx}: {id5}"
                raw_unit = str(ds_header.get('ordinate_axis_units_lab', 'g')).strip()

                func_type_code = int(ds_header.get('func_type', 1))

                # One classification rule for all readers, shared with
                # apply_unit_overrides via core.units (audit 02 finding 7.4):
                # three hand-rolled copies disagreed, so a tacho in Hz/rad/s
                # read as an accelerometer and got DC-removed. func_type 5 is a
                # UNV-only tacho encoding core.units cannot see from unit/name.
                if func_type_code == 5:
                    channel_type = "tacho"
                else:
                    channel_type = determine_channel_type(raw_unit, id1)

                meta = ChannelMetadata(
                    index=idx,
                    name=id1 if id1 else id5,
                    channel_type=channel_type,
                    unit=raw_unit
                )

                meta.func_type = int(ds_header.get('func_type', 1))
                meta.abscissa_inc = float(ds_header.get('abscissa_inc', 0.0))
                meta.abscissa_min = float(ds_header.get('abscissa_min', 0.0))
                meta.sampling_rate = (1.0 / meta.abscissa_inc) if meta.abscissa_inc > 0 else 0.0

                raw_num_pts = ds_header.get('num_pts')
                if raw_num_pts is not None:
                    meta.num_pts = int(raw_num_pts)
                else:
                    x_data = ds_header.get('x')
                    meta.num_pts = len(x_data) if x_data is not None else 0

                # id1..id5 are per-dataset UFF header fields, not one value per
                # file (BUGS.md N1/N2) -- stored on the channel like every
                # other Level-1 fact so the Metadata Editor's "channel" layer
                # can read them without assuming a single value for the whole
                # measurement.
                meta.id1 = id1
                meta.id2 = id2
                meta.id3 = id3
                meta.id4 = id4
                meta.id5 = id5
                meta.ordinate_axis_units_lab = raw_unit

                meta.rsp_node = int(ds_header.get('rsp_node', 0))
                meta.rsp_dir = int(ds_header.get('rsp_dir', 0))
                meta.ref_node = int(ds_header.get('ref_node', 0))
                meta.ref_dir = int(ds_header.get('ref_dir', 0))

                run_index.add_channel_metadata(unique_name, meta)
            except Exception as e:
                print(f"LAZY_PARSE_ERROR: Failed to map dataset #{idx} in {run_index.file_name}: {str(e)}")
                continue

    def read_single_channel_data(self, dataset_index: int) -> RawChannel:
        self._ensure_scanned()

        if dataset_index in self._dataset_offsets:
            return self._read_via_fast_path(dataset_index)
        return self._read_single_channel_via_pyuff(dataset_index)

    def _read_via_fast_path(self, dataset_index: int) -> RawChannel:
        offset = self._dataset_offsets[dataset_index]

        if not is_time_response(offset.func_type):
            raise ValueError(
                f"Dataset #{dataset_index} in {os.path.basename(self.file_path)} has "
                f"func_type={offset.func_type}, not a time response (1). This tool only processes "
                "time-domain waveforms; frequency- or correlation-domain UNV datasets are "
                "not supported."
            )

        endian = "<" if offset.byte_order == 1 else ">"
        # Only ord_data_type 2 (single) / 4 (double) ever reach here --
        # _scan_one_58b excludes complex types (5,6) from the offset map.
        dtype = f"{endian}f4" if offset.ord_data_type == 2 else f"{endian}f8"

        with open(self.file_path, "rb") as f:
            f.seek(offset.data_offset)
            raw_bytes = f.read(offset.n_bytes)

        data_arr = np.frombuffer(raw_bytes, dtype=dtype).astype(np.float64)
        time_arr = np.linspace(
            offset.abscissa_min, offset.abscissa_min + (offset.num_pts - 1) * offset.abscissa_inc,
            offset.num_pts, dtype=np.float64,
        )

        return RawChannel(
            name=offset.name,
            values=data_arr,
            times=time_arr,
            acquisition=Acquisition(
                dt=offset.abscissa_inc,
                abscissa_min=offset.abscissa_min,
                num_pts=offset.num_pts,
                recorded_unit=offset.raw_unit,
                rsp_node=offset.rsp_node,
                rsp_dir=offset.rsp_dir,
                ref_node=offset.ref_node,
                ref_dir=offset.ref_dir,
            ),
        )

    def _read_single_channel_via_pyuff(self, dataset_index: int) -> RawChannel:
        uff = pyuff.UFF(self.file_path)
        ds = uff.read_sets(setn=dataset_index)

        func_type = int(ds.get('func_type', FUNC_TYPE_TIME_RESPONSE))
        if not is_time_response(func_type):
            raise ValueError(
                f"Dataset #{dataset_index} in {os.path.basename(self.file_path)} has "
                f"func_type={func_type}, not a time response (1). This tool only processes "
                "time-domain waveforms; frequency- or correlation-domain UNV datasets are "
                "not supported."
            )

        time_arr = np.asarray(ds['x'])
        raw_data = np.asarray(ds['data'])

        # DC Offset removal logic is strictly removed from I/O layer.

        block_name = ds.get('id1', f'Channel_{dataset_index}').strip()
        y_axis_unit = ds.get('ordinate_axis_units_lab', 'g').strip()

        return RawChannel(
            name=block_name,
            values=raw_data,
            times=time_arr,
            acquisition=Acquisition(
                dt=float(ds.get('abscissa_inc', 0.0)),
                abscissa_min=float(ds.get('abscissa_min', 0.0)),
                num_pts=len(raw_data),
                recorded_unit=y_axis_unit,
                # Response and reference DOF: the physical measurement point,
                # and the pairing key against a FEM model.
                rsp_node=int(ds.get('rsp_node', 0)),
                rsp_dir=int(ds.get('rsp_dir', 0)),
                ref_node=int(ds.get('ref_node', 0)),
                ref_dir=int(ds.get('ref_dir', 0)),
            ),
        )
