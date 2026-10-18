# =====================================================================
# FILE: io_modules/reader_ldsf.py
# =====================================================================
"""
Simcenter Testlab LDSF (.ldsf) reader for raw time recordings (#604).

The layout was worked out black-box from Testlab files paired with their UNV
exports; docs/ldsf_format.md describes it and names the sample pair
that proved each field. The reader is deliberately strict: anything those
samples did not show (another format version, a sample type other than
float32, a second stream, an unknown time-axis field) is refused with the
file name and the reason, never read on a guess.

Returns RawChannel parts; DataAccessor assembles the finished NVHDataBlock,
because classifying a channel needs the unit/name knowledge one layer up.
"""

import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from core.models import FUNC_TYPE_TIME_RESPONSE, ChannelMetadata, MeasurementRunIndex
from core.data_block import Acquisition, RawChannel
from core.units import determine_channel_type


_MAGIC = b"LMS Data Streaming Format, version 13, byte order 4321"
_MAGIC_PREFIX = b"LMS Data Streaming Format, version "

# Every section starts with an 8-byte marker, then 0xFE and a u32 length.
_HEADER_OFFSET = 0x40
_HEADER_MARKER = b"\xff" * 8                      # header and index section
_SAMPLE_RECORD_MARKER = b"\xfd" + b"\xff" * 7     # one record of samples
_SAMPLE_START_MARKER = b"\xfc" + b"\xff" * 7      # last 8 bytes before a record's samples
_SAMPLE_RECORD_HEADER_SIZE = 0x40                 # samples start this far after the record marker

# Field tags (one byte each). Only the ones the reader relies on are named.
_TAG_INDEX_OFFSET = 0x50     # header: absolute offset of the index section
_TAG_STREAM = 0x53           # header and index: one stream of channels
_TAG_AXIS = 0x54             # stream: one axis (0 = time, 1.. = channels)
_TAG_STREAM_ID = 0x25
_TAG_RECORD_CAPACITY = 0x59  # stream: samples per channel in one record
_TAG_AXIS_ID = 0x26
_TAG_STORAGE = 0x5A          # axis: how its values are stored
_TAG_STORAGE_TYPE = 0x28
_TAG_TIME_STEP = 0x1A        # time axis storage: the time step as a fraction
_TAG_QUANTITY = 0x10         # axis: quantity and unit
_TAG_UNIT = 0x36
_TAG_CHANNEL_NAME = 0x3B
_TAG_RECORD_OFFSETS = 0x27   # index stream: u64 offset of every record's samples
_TAG_SAMPLE_COUNT = 0x11     # index axis: samples written for this axis
_TAG_RECORD_INDEX = 0x5B     # sample record: its position in the stream
_TAG_RECORD_BYTES = 0x5C     # sample record: bytes of samples it holds (all channels)

# A field's length is one byte, or an escape byte and a wider length.
_LENGTH_U16 = 0xFD
_LENGTH_U32 = 0xFE

_STORAGE_IMPLICIT = 0        # the time axis: computed from the time step
_STORAGE_FLOAT32 = 7         # a channel: little-endian float32 engineering values
_RAW_STREAM_ID = 0           # streams 1.. in the index are min/max previews
_MIN_TIME_STEP = 1e-7        # 10 MHz
_MAX_TIME_STEP = 1.0         # 1 Hz


class LdsfFormatError(ValueError):
    """The file is not an LDSF time recording this reader understands."""


@dataclass(frozen=True)
class _Channel:
    name: str
    unit: str
    num_pts: int


@dataclass(frozen=True)
class _Layout:
    time_step: float
    record_capacity: int                 # samples per channel in one record
    record_offsets: Tuple[int, ...]      # absolute offset of each record's samples
    channels: Tuple[_Channel, ...]       # in storage order inside a record


def _read_fields(data: bytes, padded: bool = False) -> List[Tuple[int, bytes]]:
    """
    One level of tag-length-value fields; a nested field stays raw bytes for the caller.

    `padded`: the fields are followed by zero padding. Tag 0 never occurs, so
    the first zero tag ends them, and everything after it must be zero.
    """
    fields = []
    pos = 0
    while pos < len(data):
        if padded and data[pos] == 0:
            if any(data[pos:]):
                raise LdsfFormatError("fields are not followed by zero padding")
            break
        if pos + 2 > len(data):
            raise LdsfFormatError("field header runs past the end of its section")
        tag, length = data[pos], data[pos + 1]
        pos += 2
        if length == _LENGTH_U16:
            length = struct.unpack_from("<H", data, pos)[0]
            pos += 2
        elif length == _LENGTH_U32:
            length = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif length == 0xFF:
            raise LdsfFormatError(f"unknown length encoding 0xFF in field 0x{tag:02X}")
        if pos + length > len(data):
            raise LdsfFormatError(f"field 0x{tag:02X} runs past the end of its section")
        fields.append((tag, data[pos:pos + length]))
        pos += length
    return fields


def _all(fields, tag: int) -> List[bytes]:
    return [value for field_tag, value in fields if field_tag == tag]


def _one(fields, tag: int, where: str) -> bytes:
    values = _all(fields, tag)
    if len(values) != 1:
        raise LdsfFormatError(f"expected one field 0x{tag:02X} in the {where}, found {len(values)}")
    return values[0]


def _uint(value: bytes) -> int:
    return int.from_bytes(value, "little")


def _text(value: bytes) -> str:
    return value.rstrip(b"\0").decode("utf-8", errors="replace")


def _read_section(f, offset: int, marker: bytes, what: str) -> bytes:
    f.seek(offset)
    head = f.read(len(marker) + 5)
    if len(head) < len(marker) + 5 or head[:len(marker)] != marker or head[len(marker)] != _LENGTH_U32:
        raise LdsfFormatError(f"no {what} at offset 0x{offset:X}")
    length = struct.unpack_from("<I", head, len(marker) + 1)[0]
    body = f.read(length)
    if len(body) != length:
        raise LdsfFormatError(f"the {what} at offset 0x{offset:X} is cut short")
    return body


def _read_time_step(storage: List[Tuple[int, bytes]]) -> float:
    """
    The time step, stored as a fraction of two length-prefixed integers:
    `01 01 02 00 32` is 1 / 12800 s. Any rate is read the same way; a result
    outside 1 Hz .. 10 MHz means the bytes were not such a fraction and is
    refused rather than handed on as a timebase.
    """
    tags = sorted({tag for tag, _ in storage})
    if tags != sorted({_TAG_STORAGE_TYPE, _TAG_TIME_STEP}):
        raise LdsfFormatError(f"unknown time axis fields {[f'0x{t:02X}' for t in tags]}")
    encoded = _one(storage, _TAG_TIME_STEP, "time axis")
    numbers, pos = [], 0
    while pos < len(encoded):
        size = encoded[pos]
        if size == 0 or pos + 1 + size > len(encoded):
            raise LdsfFormatError(f"unknown time step encoding {encoded.hex(' ')}")
        numbers.append(_uint(encoded[pos + 1:pos + 1 + size]))
        pos += 1 + size
    if len(numbers) != 2 or 0 in numbers:
        raise LdsfFormatError(f"unknown time step encoding {encoded.hex(' ')}")
    time_step = numbers[0] / numbers[1]
    if not _MIN_TIME_STEP <= time_step <= _MAX_TIME_STEP:
        raise LdsfFormatError(f"time step {time_step:g} s ({encoded.hex(' ')}) is not a plausible sampling rate")
    return time_step


def _read_layout(file_path: str) -> _Layout:
    """Header and index of the file: everything needed to find any channel's samples."""
    with open(file_path, "rb") as f:
        magic = f.read(_HEADER_OFFSET).split(b"\0", 1)[0]
        if magic != _MAGIC:
            if not magic.startswith(_MAGIC_PREFIX):
                raise LdsfFormatError("not an LMS Data Streaming Format file")
            found = magic.decode("ascii", errors="replace")
            raise LdsfFormatError(f"unsupported '{found}'; only '{_MAGIC.decode('ascii')}' is known")

        header = _read_fields(_read_section(f, _HEADER_OFFSET, _HEADER_MARKER, "header"))
        index_offset = _uint(_one(header, _TAG_INDEX_OFFSET, "header"))
        if index_offset == 0:
            raise LdsfFormatError("the file has no index; the recording was probably not closed")
        index = _read_fields(_read_section(f, index_offset, _HEADER_MARKER, "index"))

    streams = _all(header, _TAG_STREAM)
    if len(streams) != 1:
        raise LdsfFormatError(f"{len(streams)} streams in the header; only one is known")
    stream = _read_fields(streams[0])
    if _uint(_one(stream, _TAG_STREAM_ID, "stream")) != _RAW_STREAM_ID:
        raise LdsfFormatError("the header stream is not the raw time stream")
    record_capacity = _uint(_one(stream, _TAG_RECORD_CAPACITY, "stream"))

    index_streams = [_read_fields(s) for s in _all(index, _TAG_STREAM)]
    index_streams = [s for s in index_streams if _uint(_one(s, _TAG_STREAM_ID, "index")) == _RAW_STREAM_ID]
    if len(index_streams) != 1:
        raise LdsfFormatError("the index does not describe the raw time stream")
    index_stream = index_streams[0]
    offsets = _one(index_stream, _TAG_RECORD_OFFSETS, "index")
    if len(offsets) % 8:
        raise LdsfFormatError("record offsets in the index are not whole u64 values")
    record_offsets = tuple(int(o) for o in np.frombuffer(offsets, dtype="<u8"))
    sample_counts = {}
    for axis in (_read_fields(a) for a in _all(index_stream, _TAG_AXIS)):
        sample_counts[_uint(_one(axis, _TAG_AXIS_ID, "index axis"))] = _uint(
            _one(axis, _TAG_SAMPLE_COUNT, "index axis"))

    time_step = None
    channels: Dict[int, _Channel] = {}
    for axis in (_read_fields(a) for a in _all(stream, _TAG_AXIS)):
        axis_id = _uint(_one(axis, _TAG_AXIS_ID, "axis"))
        storage = _read_fields(_one(axis, _TAG_STORAGE, "axis"))
        storage_type = _uint(_one(storage, _TAG_STORAGE_TYPE, "axis storage"))
        if axis_id == 0:
            if storage_type != _STORAGE_IMPLICIT:
                raise LdsfFormatError(f"time axis stored as type {storage_type}; only an implicit one is known")
            time_step = _read_time_step(storage)
            continue
        if storage_type != _STORAGE_FLOAT32:
            raise LdsfFormatError(f"channel axis {axis_id} stored as type {storage_type}; only float32 (7) is known")
        if axis_id not in sample_counts:
            raise LdsfFormatError(f"the index has no sample count for channel axis {axis_id}")
        quantity = _read_fields(_one(axis, _TAG_QUANTITY, "axis"))
        channels[axis_id] = _Channel(
            name=_text(_one(axis, _TAG_CHANNEL_NAME, "axis")),
            unit=_text(_one(quantity, _TAG_UNIT, "quantity")),
            num_pts=sample_counts[axis_id],
        )

    if time_step is None:
        raise LdsfFormatError("the stream has no time axis")
    if not channels:
        raise LdsfFormatError("the stream has no channels")
    layout = _Layout(
        time_step=time_step,
        record_capacity=record_capacity,
        record_offsets=record_offsets,
        channels=tuple(channels[axis_id] for axis_id in sorted(channels)),
    )
    for channel in layout.channels:
        if not (len(record_offsets) - 1) * record_capacity < channel.num_pts <= len(record_offsets) * record_capacity:
            raise LdsfFormatError(
                f"{channel.num_pts} samples of '{channel.name}' do not fill "
                f"{len(record_offsets)} records of {record_capacity}"
            )
    return layout


def _check_sample_record(f, offset: int, record: int, record_bytes: int) -> None:
    """
    The index points at samples; the record header in front of them must agree.

    The header is a fixed 0x40 bytes: marker, fields, zero padding and the
    sample-start marker. Its length field does not count the same way as the
    header and index sections do, so the fields are read up to the padding.
    """
    f.seek(offset - _SAMPLE_RECORD_HEADER_SIZE)
    head = f.read(_SAMPLE_RECORD_HEADER_SIZE)
    if (len(head) != _SAMPLE_RECORD_HEADER_SIZE
            or not head.startswith(_SAMPLE_RECORD_MARKER)
            or not head.endswith(_SAMPLE_START_MARKER)):
        raise LdsfFormatError(f"no sample record {record} in front of offset 0x{offset:X}")
    fields = _read_fields(head[len(_SAMPLE_RECORD_MARKER) + 5:-len(_SAMPLE_START_MARKER)], padded=True)
    if (_uint(_one(fields, _TAG_STREAM_ID, "sample record")) != _RAW_STREAM_ID
            or _uint(_one(fields, _TAG_RECORD_INDEX, "sample record")) != record
            or _uint(_one(fields, _TAG_RECORD_BYTES, "sample record")) != record_bytes):
        raise LdsfFormatError(f"sample record {record} does not match the index")


def _read_samples(file_path: str, layout: _Layout, position: int) -> np.ndarray:
    """
    One channel's samples, gathered record by record. Inside a record every
    channel fills `record_capacity` samples, one channel after another; the last
    record is only partly written.
    """
    channel = layout.channels[position]
    capacity = layout.record_capacity
    record_bytes = capacity * len(layout.channels) * 4
    samples = np.empty(channel.num_pts, dtype="<f4")
    with open(file_path, "rb") as f:
        for record, offset in enumerate(layout.record_offsets):
            _check_sample_record(f, offset, record, record_bytes)
            start = record * capacity
            count = min(capacity, channel.num_pts - start)
            f.seek(offset + position * capacity * 4)
            if f.readinto(memoryview(samples[start:start + count]).cast("B")) != count * 4:
                raise LdsfFormatError(f"sample record {record} is cut short")
    return samples


class AccReaderLdsf:
    """
    Parser for Simcenter Testlab .ldsf raw time recordings.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path

    def _layout(self) -> _Layout:
        try:
            return _read_layout(self.file_path)
        except LdsfFormatError as exc:
            raise LdsfFormatError(f"{os.path.basename(self.file_path)}: {exc}") from None

    def scan_file_structure(self) -> MeasurementRunIndex:
        """Registers the file envelope inside the workspace."""
        file_name = os.path.basename(self.file_path)
        return MeasurementRunIndex(file_name, self.file_path)

    def load_channels_on_demand(self, run_index: MeasurementRunIndex):
        if run_index.available_channels:
            return

        layout = self._layout()
        for position, channel in enumerate(layout.channels):
            channel_type = determine_channel_type(channel.unit, channel.name)
            meta = ChannelMetadata(index=position, name=channel.name, channel_type=channel_type, unit=channel.unit)
            meta.func_type = FUNC_TYPE_TIME_RESPONSE
            meta.abscissa_inc = layout.time_step
            meta.abscissa_min = 0.0
            meta.num_pts = channel.num_pts
            meta.sampling_rate = 1.0 / layout.time_step
            meta.ordinate_axis_units_lab = channel.unit
            # Two channels may share a name (Testlab allows it), the key may not.
            # "Set #N: " is the label channel identity already strips, as for UNV.
            run_index.add_channel_metadata(f"Set #{position + 1}: {channel.name}", meta)

    def read_single_channel_data(self, dataset_index: int) -> RawChannel:
        layout = self._layout()
        if not 0 <= dataset_index < len(layout.channels):
            raise IndexError(
                f"Channel index {dataset_index} is not a channel of {os.path.basename(self.file_path)}."
            )
        try:
            samples = _read_samples(self.file_path, layout, dataset_index)
        except LdsfFormatError as exc:
            raise LdsfFormatError(f"{os.path.basename(self.file_path)}: {exc}") from None

        channel = layout.channels[dataset_index]
        return RawChannel(
            name=channel.name,
            values=samples.astype(np.float64),
            times=np.arange(channel.num_pts, dtype=np.float64) * layout.time_step,
            acquisition=Acquisition(
                dt=layout.time_step,
                abscissa_min=0.0,
                num_pts=channel.num_pts,
                recorded_unit=channel.unit,
            ),
        )
