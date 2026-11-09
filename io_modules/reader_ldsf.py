# =====================================================================
# FILE: io_modules/reader_ldsf.py
# =====================================================================
"""
Simcenter Testlab LDSF (.ldsf) reader for raw time recordings (#604).

The layout was worked out black-box from Testlab files paired with their UNV
exports; docs/ldsf_format.md describes it and names the sample pair
that proved each field. The reader is deliberately strict: anything those
samples did not show (another format version, a sample type other than
float32 or scaled int24, a second stream, an unknown time-axis field) is
refused with the file name and the reason, never read on a guess.

Returns RawChannel parts; DataAccessor assembles the finished NVHDataBlock,
because classifying a channel needs the unit/name knowledge one layer up.
"""

import os
import re
import struct
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from core.models import FUNC_TYPE_TIME_RESPONSE, ChannelMetadata, MeasurementRunIndex
from core.data_block import Acquisition, RawChannel
from core.units import determine_channel_type


# Version 13: Testlab formula signals (float32). Version 21: a real front-end
# recording (scaled int24, annotation streams). Both are read; see docs/ldsf_format.md.
_SUPPORTED_VERSIONS = (13, 21)
_MAGIC_PREFIX = b"LMS Data Streaming Format, version "
_MAGIC_PATTERN = re.compile(rb"LMS Data Streaming Format, version (\d+), byte order 4321")

# Every section starts with an 8-byte marker, then 0xFE and a u32 length.
_HEADER_OFFSET = 0x40
_HEADER_MARKER = b"\xff" * 8                      # header and index section
_SAMPLE_RECORD_MARKER = b"\xfd" + b"\xff" * 7     # one record of samples
_SAMPLE_START_MARKER = b"\xfc" + b"\xff" * 7      # last 8 bytes before a record's samples
_SAMPLE_RECORD_HEADER_WINDOW = 0x1000            # how far back from the samples the record marker is searched

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
_TAG_START_TIME = 0x19       # time axis storage (version 21): the first sample's time as a fraction
_TAG_SCALE = 0x1B            # int24 channel storage: f64 multiplier from raw counts to SI
_TAG_FACTOR = 0x33           # quantity: f64 multiplier from SI to the unit in 0x36
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
_STORAGE_INT24 = 4           # a channel: little-endian signed 24-bit counts times a scale
# The raw stream is the single `0x53` stream of the header (id 0 in version 13, 1 in
# version 21); other streams of the index are min/max previews.
_CHANNEL_ALIGNMENT = 4       # every channel starts on a 4-byte boundary inside a record
_MIN_TIME_STEP = 1e-7        # 10 MHz
_MAX_TIME_STEP = 1.0         # 1 Hz


class LdsfFormatError(ValueError):
    """The file is not an LDSF time recording this reader understands."""


@dataclass(frozen=True)
class _Channel:
    name: str
    unit: str
    num_pts: int
    storage_type: int
    multiplier: float        # int24: counts -> `unit`; unused for float32 (already in `unit`)

    @property
    def sample_width(self) -> int:
        return 3 if self.storage_type == _STORAGE_INT24 else 4


@dataclass(frozen=True)
class _Layout:
    stream_id: int
    time_step: float
    start_time: float
    record_capacity: int                 # samples per channel in one record
    record_offsets: Tuple[int, ...]      # absolute offset of each record's samples
    channels: Tuple[_Channel, ...]       # in storage order inside a record
    channel_offsets: Tuple[int, ...]     # byte offset of each channel inside a record
    min_record_bytes: int                # a record holds at least this many bytes


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


def _read_fraction(encoded: bytes, what: str) -> Tuple[int, int]:
    """
    A fraction stored as two length-prefixed little-endian integers:
    `01 01 02 00 32` is 1 / 12800.
    """
    numbers, pos = [], 0
    while pos < len(encoded):
        size = encoded[pos]
        if size == 0 or pos + 1 + size > len(encoded):
            raise LdsfFormatError(f"unknown {what} encoding {encoded.hex(' ')}")
        numbers.append(_uint(encoded[pos + 1:pos + 1 + size]))
        pos += 1 + size
    if len(numbers) != 2 or numbers[1] == 0:
        raise LdsfFormatError(f"unknown {what} encoding {encoded.hex(' ')}")
    return numbers[0], numbers[1]


def _read_time_axis(storage: List[Tuple[int, bytes]]) -> Tuple[float, float]:
    """
    (time step, start time) of the implicit time axis. The time step is a
    fraction; a result outside 1 Hz .. 10 MHz means the bytes were not such a
    fraction and is refused rather than handed on as a timebase. The start
    time (version 21 only; version 13 starts at 0 s) is a fraction as well.
    """
    tags = {tag for tag, _ in storage}
    required = {_TAG_STORAGE_TYPE, _TAG_TIME_STEP}
    if tags not in (required, required | {_TAG_START_TIME}):
        raise LdsfFormatError(f"unknown time axis fields {[f'0x{t:02X}' for t in sorted(tags)]}")
    numerator, denominator = _read_fraction(_one(storage, _TAG_TIME_STEP, "time axis"), "time step")
    if numerator == 0:
        raise LdsfFormatError(f"unknown time step encoding {_one(storage, _TAG_TIME_STEP, 'time axis').hex(' ')}")
    time_step = numerator / denominator
    if not _MIN_TIME_STEP <= time_step <= _MAX_TIME_STEP:
        raise LdsfFormatError(
            f"time step {time_step:g} s ({_one(storage, _TAG_TIME_STEP, 'time axis').hex(' ')}) "
            "is not a plausible sampling rate")
    start_time = 0.0
    if _TAG_START_TIME in tags:
        start_numerator, start_denominator = _read_fraction(_one(storage, _TAG_START_TIME, "time axis"), "start time")
        start_time = start_numerator / start_denominator
        if not 0.0 <= start_time < 1e6:
            raise LdsfFormatError(f"start time {start_time:g} s is not plausible")
    return time_step, start_time


def _read_layout(file_path: str) -> _Layout:
    """Header and index of the file: everything needed to find any channel's samples."""
    with open(file_path, "rb") as f:
        magic = f.read(_HEADER_OFFSET).split(b"\0", 1)[0]
        if not magic.startswith(_MAGIC_PREFIX):
            raise LdsfFormatError("not an LMS Data Streaming Format file")
        matched = _MAGIC_PATTERN.fullmatch(magic)
        if matched is None or int(matched.group(1)) not in _SUPPORTED_VERSIONS:
            found = magic.decode("ascii", errors="replace")
            known = ", ".join(str(v) for v in _SUPPORTED_VERSIONS)
            raise LdsfFormatError(f"unsupported '{found}'; only version {known} (byte order 4321) are known")

        header = _read_fields(_read_section(f, _HEADER_OFFSET, _HEADER_MARKER, "header"))
        index_offset = _uint(_one(header, _TAG_INDEX_OFFSET, "header"))
        if index_offset == 0:
            raise LdsfFormatError("the file has no index; the recording was probably not closed")
        index = _read_fields(_read_section(f, index_offset, _HEADER_MARKER, "index"))

    streams = _all(header, _TAG_STREAM)
    if len(streams) != 1:
        raise LdsfFormatError(f"{len(streams)} streams in the header; only one is known")
    stream = _read_fields(streams[0])
    stream_id = _uint(_one(stream, _TAG_STREAM_ID, "stream"))
    record_capacity = _uint(_one(stream, _TAG_RECORD_CAPACITY, "stream"))

    index_streams = [_read_fields(s) for s in _all(index, _TAG_STREAM)]
    index_streams = [s for s in index_streams if _uint(_one(s, _TAG_STREAM_ID, "index")) == stream_id]
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
    start_time = 0.0
    channels: Dict[int, _Channel] = {}
    for axis in (_read_fields(a) for a in _all(stream, _TAG_AXIS)):
        axis_id = _uint(_one(axis, _TAG_AXIS_ID, "axis"))
        storage = _read_fields(_one(axis, _TAG_STORAGE, "axis"))
        storage_type = _uint(_one(storage, _TAG_STORAGE_TYPE, "axis storage"))
        if axis_id == 0:
            if storage_type != _STORAGE_IMPLICIT:
                raise LdsfFormatError(f"time axis stored as type {storage_type}; only an implicit one is known")
            time_step, start_time = _read_time_axis(storage)
            continue
        if storage_type not in (_STORAGE_FLOAT32, _STORAGE_INT24):
            raise LdsfFormatError(
                f"channel axis {axis_id} stored as type {storage_type}; only float32 (7) and int24 (4) are known")
        if axis_id not in sample_counts:
            raise LdsfFormatError(f"the index has no sample count for channel axis {axis_id}")
        quantity = _read_fields(_one(axis, _TAG_QUANTITY, "axis"))
        multiplier = 1.0
        if storage_type == _STORAGE_INT24:
            if sorted(tag for tag, _ in storage) != sorted((_TAG_STORAGE_TYPE, _TAG_SCALE)):
                raise LdsfFormatError(f"unknown int24 storage fields in channel axis {axis_id}")
            scale = _one(storage, _TAG_SCALE, "int24 storage")
            if len(scale) != 8:
                raise LdsfFormatError(f"the scale of channel axis {axis_id} is not an f64")
            multiplier = struct.unpack("<d", scale)[0]
            factors = _all(quantity, _TAG_FACTOR)
            if len(factors) > 1 or any(len(v) != 8 for v in factors):
                raise LdsfFormatError(f"the unit factor of channel axis {axis_id} is not one f64")
            if factors:
                multiplier *= struct.unpack("<d", factors[0])[0]
        channels[axis_id] = _Channel(
            name=_text(_one(axis, _TAG_CHANNEL_NAME, "axis")),
            unit=_text(_one(quantity, _TAG_UNIT, "quantity")),
            num_pts=sample_counts[axis_id],
            storage_type=storage_type,
            multiplier=multiplier,
        )

    if time_step is None:
        raise LdsfFormatError("the stream has no time axis")
    if not channels:
        raise LdsfFormatError("the stream has no channels")
    ordered = tuple(channels[axis_id] for axis_id in sorted(channels))
    channel_offsets, position = [], 0
    for channel in ordered:
        channel_offsets.append(position)
        position += -(-record_capacity * channel.sample_width // _CHANNEL_ALIGNMENT) * _CHANNEL_ALIGNMENT
    layout = _Layout(
        stream_id=stream_id,
        time_step=time_step,
        start_time=start_time,
        record_capacity=record_capacity,
        record_offsets=record_offsets,
        channels=ordered,
        channel_offsets=tuple(channel_offsets),
        min_record_bytes=position,
    )
    for channel in layout.channels:
        if not (len(record_offsets) - 1) * record_capacity < channel.num_pts <= len(record_offsets) * record_capacity:
            raise LdsfFormatError(
                f"{channel.num_pts} samples of '{channel.name}' do not fill "
                f"{len(record_offsets)} records of {record_capacity}"
            )
    return layout


def _check_sample_record(f, offset: int, record: int, stream_id: int, min_record_bytes: int) -> None:
    """
    The index points at samples; the record header in front of them must agree.

    The header ends with the sample-start marker right before the samples and
    begins with the record marker. Its length is 0x40 bytes in version 13 and
    grows with the channel count in version 21 (an extra per-channel field), so
    it is found by searching back for the nearest record marker. The length
    field does not count the same way as in the header and index sections, so
    the fields are read up to the zero padding.
    """
    start = max(0, offset - _SAMPLE_RECORD_HEADER_WINDOW)
    f.seek(start)
    window = f.read(offset - start)
    if len(window) != offset - start or not window.endswith(_SAMPLE_START_MARKER):
        raise LdsfFormatError(f"no sample record {record} in front of offset 0x{offset:X}")
    begin = window.rfind(_SAMPLE_RECORD_MARKER + bytes([_LENGTH_U32]))
    fields_start = begin + len(_SAMPLE_RECORD_MARKER) + 5
    if begin < 0 or fields_start > len(window) - len(_SAMPLE_START_MARKER):
        raise LdsfFormatError(f"no sample record {record} in front of offset 0x{offset:X}")
    fields = _read_fields(window[fields_start:-len(_SAMPLE_START_MARKER)], padded=True)
    # The record may be longer than its channels need (version 21 pads the last
    # channel); it may not be shorter.
    if (_uint(_one(fields, _TAG_STREAM_ID, "sample record")) != stream_id
            or _uint(_one(fields, _TAG_RECORD_INDEX, "sample record")) != record
            or _uint(_one(fields, _TAG_RECORD_BYTES, "sample record")) < min_record_bytes):
        raise LdsfFormatError(f"sample record {record} does not match the index")


def _read_samples(file_path: str, layout: _Layout, position: int) -> np.ndarray:
    """
    One channel's samples as float64 in the channel's unit, gathered record by
    record. Inside a record every channel fills `record_capacity` samples, one
    channel after another, each on a 4-byte boundary; the last record is only
    partly written.
    """
    channel = layout.channels[position]
    capacity = layout.record_capacity
    samples = np.empty(channel.num_pts, dtype=np.float64)
    with open(file_path, "rb") as f:
        for record, offset in enumerate(layout.record_offsets):
            _check_sample_record(f, offset, record, layout.stream_id, layout.min_record_bytes)
            start = record * capacity
            count = min(capacity, channel.num_pts - start)
            f.seek(offset + layout.channel_offsets[position])
            if channel.storage_type == _STORAGE_FLOAT32:
                chunk = np.empty(count, dtype="<f4")
                if f.readinto(memoryview(chunk).cast("B")) != count * 4:
                    raise LdsfFormatError(f"sample record {record} is cut short")
                samples[start:start + count] = chunk
            else:
                raw = np.empty((count, 3), dtype=np.uint8)
                if f.readinto(memoryview(raw).cast("B")) != count * 3:
                    raise LdsfFormatError(f"sample record {record} is cut short")
                counts = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8)
                          | (raw[:, 2].astype(np.int32) << 16))
                counts -= (counts & 0x800000) << 1      # sign-extend 24 -> 32 bits
                samples[start:start + count] = counts * channel.multiplier
    return samples


_DIRECTIONS = {"+X": 1, "+Y": 2, "+Z": 3}


def _response_dofs(channels: Tuple[_Channel, ...]) -> List[Tuple[int, int]]:
    """
    Response node and direction of every channel, as the UNV export of the same file writes them.

    The .ldsf stores no node numbers; its channel name is "<point>:<direction>" ("B0 Y:+Y").
    The UNV export numbers the points 1.. in plain sorted order of the point name, and
    codes +X, +Y, +Z as 1, 2, 3 (checked on two real recordings, 17 and 39 channels). A name
    without a recognised direction suffix has direction 0, but still a point and a node.
    """
    points = [name.rpartition(":")[0] if ":" in name else name for name in (c.name for c in channels)]
    node_of = {point: rank for rank, point in enumerate(sorted(set(points)), start=1)}
    return [
        (node_of[point], _DIRECTIONS.get(channel.name.rpartition(":")[2], 0) if ":" in channel.name else 0)
        for point, channel in zip(points, channels)
    ]


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

    def read_run_index(self) -> MeasurementRunIndex:
        """The file's channels and Lost parts, read from its header (MeasurementReader)."""
        run_index = MeasurementRunIndex(os.path.basename(self.file_path), self.file_path)
        self._read_channels(run_index)
        return run_index

    def _read_channels(self, run_index: MeasurementRunIndex) -> None:
        layout = self._layout()
        dofs = _response_dofs(layout.channels)
        for position, channel in enumerate(layout.channels):
            channel_type = determine_channel_type(channel.unit, channel.name)
            meta = ChannelMetadata(index=position, name=channel.name, channel_type=channel_type, unit=channel.unit)
            meta.func_type = FUNC_TYPE_TIME_RESPONSE
            meta.rsp_node, meta.rsp_dir = dofs[position]
            meta.abscissa_inc = layout.time_step
            meta.abscissa_min = layout.start_time
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
        rsp_node, rsp_dir = _response_dofs(layout.channels)[dataset_index]
        return RawChannel(
            name=channel.name,
            values=samples,
            times=layout.start_time + np.arange(channel.num_pts, dtype=np.float64) * layout.time_step,
            acquisition=Acquisition(
                dt=layout.time_step,
                abscissa_min=layout.start_time,
                num_pts=channel.num_pts,
                recorded_unit=channel.unit,
                rsp_node=rsp_node,
                rsp_dir=rsp_dir,
            ),
        )
