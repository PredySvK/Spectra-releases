# =====================================================================
# FILE: io_modules/reader_hdf.py
# =====================================================================
"""
HEAD acoustics datafile (.hdf) reader for raw time recordings.

Despite the suffix this is not HDF5: a HEAD acoustics file is a text header
(`key: value` lines, CRLF) padded with tabs up to `start of data`, followed by
the samples as one binary block. Two versions are known: 2.2, a Simcenter Tecware
export checked against the UNV export of the same recording (39 channels,
3 735 552 samples each), and 4.6, a HEADlab recording with channels at different
rates. docs/hdf_format.md describes both.

The reader is deliberately strict, like the .ldsf one: anything those samples did
not show (another format version, byte order, sample type, data organisation,
a non-linear mapping, a second abscissa) is refused with the file name and the
reason, never read on a guess.

Returns RawChannel parts; DataAccessor assembles the finished NVHDataBlock,
because classifying a channel needs the unit/name knowledge one layer up.
"""

import codecs
import math
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from core.models import FUNC_TYPE_TIME_RESPONSE, ChannelMetadata, LostPart, MeasurementRunIndex
from core.data_block import Acquisition, RawChannel
from core.units import determine_channel_type


_MAGIC = re.compile(rb"; Copyright \d{4} HEAD acoustics GmbH")
_HEADER_PROBE_BYTES = 4096                       # enough to reach `start of data`
_MAX_HEADER_BYTES = 16 * 1024 * 1024             # a header larger than this is not a header
_MIN_TIME_STEP = 1e-7                            # 10 MHz
_MAX_TIME_STEP = 1.0                             # 1 Hz
_READ_STEP = 1 << 20                             # blocks converted at a time, so the strided read stays in cache
_HEADER_BLANKS = " \t\r\n"                        # not str.strip(): header bytes are held as latin-1, where a
                                                 # code page's 0x85 and 0xA0 would count as whitespace

# Sample types of `implementation type`: numpy type, bytes per sample.
_IMPLEMENTATIONS = {
    "INT16": ("<i2", 2),
    "FLOAT32": ("<f4", 4),
    "UINT32": ("<u4", 4),
}

# What the known layouts say; every other value is refused.
_EXPECTED_ABSCISSA = {
    "absc sort": "calc",
    "distribution func": "linear",
}


@dataclass(frozen=True)
class _Format:
    """One known (version, release) of the file format."""
    scalars: Dict[str, str]
    channel: Dict[str, str]
    implementations: Tuple[str, ...]     # sample types seen in this version
    scaled: bool                         # True: INT16 counts x `map factor`; False: values already in the unit
    period_from_elements: bool           # True: `delta value` is the step of one stored element, not of one scan


_COMMON_SCALARS = {
    "byte order": "Intel",
    "kind": "Time data",
    "nbr of abscissa": "1",
    "nbr of extra fields": "0",
    "idx order": "1",
    "data org": "a1b1 a2b2",                     # sample by sample, all channels of one block together
}
_FORMATS = {
    # Simcenter Tecware export: INT16 counts, every channel at one rate.
    ("2", "2"): _Format(
        scalars={**_COMMON_SCALARS, "channel attributes": "common", "scan mode": "simultaneous"},
        channel={"quantisation func": "linear", "composition": "sample",
                 "map d trns func": "linear", "map w trns func": "linear"},
        implementations=("INT16",), scaled=True, period_from_elements=False),
    # HEADlab recording: FLOAT32 in the unit, channels at different rates (`ch order` says how many
    # samples of each channel one block holds), raw CAN frames as UINT32.
    ("4", "6"): _Format(
        scalars={**_COMMON_SCALARS, "channel attributes": "private", "scan mode": "synchronised multiple"},
        channel={"quantisation func": "linear", "composition": "sample"},
        implementations=("FLOAT32", "UINT32"), scaled=False, period_from_elements=True),
}


class HdfFormatError(ValueError):
    """The file is not a HEAD acoustics time recording this reader understands."""


@dataclass(frozen=True)
class _Channel:
    name: str
    unit: str
    factor: float            # raw samples -> `unit` (1.0 when the file already holds the unit)
    dtype: str               # numpy type of the stored samples
    per_block: int           # samples of this channel in one block
    offset: int              # position of its first sample within a block, in samples
    readable: bool           # False: not a measured signal (raw CAN frames), not read
    position: int            # index in the file


@dataclass(frozen=True)
class _Layout:
    block_period: float      # time covered by one block
    start_time: float
    num_blocks: int
    block_samples: int       # samples of all channels in one block
    sample_width: int        # bytes per stored sample
    data_offset: int         # absolute offset of the first sample
    trailing_bytes: int      # what the file holds after the last sample
    channels: Tuple[_Channel, ...]

    def time_step(self, channel: _Channel) -> float:
        return self.block_period / channel.per_block

    def num_pts(self, channel: _Channel) -> int:
        return self.num_blocks * channel.per_block


def _read_header_text(f) -> Tuple[str, int]:
    """The header as text and the offset where the samples begin."""
    f.seek(0)
    probe = f.read(_HEADER_PROBE_BYTES)
    if _MAGIC.search(probe[:256]) is None:
        raise HdfFormatError("not a HEAD acoustics datafile")
    found = re.search(rb"^start of data:\s*(\d+)\s*$", probe, re.MULTILINE)
    if found is None:
        raise HdfFormatError("the header has no 'start of data'")
    data_offset = int(found.group(1))
    if not 0 < data_offset <= _MAX_HEADER_BYTES:
        raise HdfFormatError(f"'start of data' {data_offset} is not plausible")
    f.seek(0)
    header = f.read(data_offset)
    if len(header) != data_offset:
        raise HdfFormatError("the header is cut short")
    return header.decode("latin-1"), data_offset


def _parse_header(text: str) -> Tuple[Dict[str, str], Dict[str, str], List[Dict[str, str]], int]:
    """
    (global fields, abscissa fields, channel fields per channel, data bytes announced by the tail).

    Lines starting with `;` are comments. A `channel definition` or
    `abscissa definition` line opens a block of `key: value` lines.
    """
    scalars: Dict[str, str] = {}
    abscissa: Dict[str, str] = {}
    channels: List[Dict[str, str]] = []
    target = scalars
    # `comment <n> :` announces n bytes of free text (a different syntax, not `key: value`).
    note = re.search(r"^comment\s+(\d+)\s*:", text, re.MULTILINE)
    if note:
        text = text[:note.start()] + text[note.end() + int(note.group(1)):]
    for raw_line in text.replace("\t", "").split("\r\n"):
        line = raw_line.strip(_HEADER_BLANKS)
        if not line or line.startswith(";"):
            continue
        tail = re.fullmatch(r"data1\s+(\d+)\s*:", line)
        if tail:
            return scalars, abscissa, channels, int(tail.group(1))
        key, separator, value = line.partition(":")
        if not separator:
            raise HdfFormatError(f"header line '{line[:60]}' is not 'key: value'")
        key, value = key.strip(_HEADER_BLANKS), value.strip(_HEADER_BLANKS)
        if key == "abscissa definition":
            if abscissa:
                raise HdfFormatError("the header defines more than one abscissa")
            target = abscissa
        elif key == "channel definition":
            target = {}
            channels.append(target)
        else:
            target[key] = value
    raise HdfFormatError("the header does not end with the 'data1 <bytes> :' line")


def _require(fields: Dict[str, str], key: str, where: str) -> str:
    if key not in fields:
        raise HdfFormatError(f"the {where} has no '{key}'")
    return fields[key]


def _number(value: str, what: str) -> float:
    try:
        return float(value)
    except ValueError:
        raise HdfFormatError(f"{what} '{value}' is not a number") from None


def _count(value: str, what: str) -> int:
    number = _number(value, what)
    if not number.is_integer():
        raise HdfFormatError(f"{what} '{value}' is not a whole number")
    return int(number)


def _read_layout(file_path: str) -> _Layout:
    """Header of the file: everything needed to find any channel's samples."""
    with open(file_path, "rb") as f:
        text, data_offset = _read_header_text(f)
        file_size = os.fstat(f.fileno()).st_size
    scalars, abscissa, channel_fields, data_bytes = _parse_header(text)

    version = (scalars.get("version"), scalars.get("release"))
    fmt = _FORMATS.get(version)
    if fmt is None:
        known = " or ".join(f"{v} release {r}" for v, r in _FORMATS)
        raise HdfFormatError(f"unsupported version {version[0]!r} release {version[1]!r}; "
                             f"only version {known} is known")
    for key, expected in fmt.scalars.items():
        if scalars.get(key) != expected:
            raise HdfFormatError(f"'{key}' is {scalars.get(key)!r}; only {expected!r} is known")
    for key, expected in _EXPECTED_ABSCISSA.items():
        if abscissa.get(key) != expected:
            raise HdfFormatError(f"abscissa '{key}' is {abscissa.get(key)!r}; only {expected!r} is known")
    if abscissa.get("physical unit") != "s":
        raise HdfFormatError(f"the abscissa is in {abscissa.get('physical unit')!r}, not seconds")

    count = _count(_require(scalars, "nbr of channel", "header"), "'nbr of channel'")
    if count < 1 or len(channel_fields) != count:
        raise HdfFormatError(f"{len(channel_fields)} channel definitions for 'nbr of channel' {count}")
    per_block = _parse_channel_order(scalars.get("ch order", ""), count)

    time_step = _number(_require(abscissa, "delta value", "abscissa"), "time step")
    if not _MIN_TIME_STEP <= time_step <= _MAX_TIME_STEP:
        raise HdfFormatError(f"time step {time_step:g} s is not a plausible sampling rate")
    start_time = _number(_require(abscissa, "first value", "abscissa"), "start time")
    if not 0.0 <= start_time < 1e6:
        raise HdfFormatError(f"start time {start_time:g} s is not plausible")
    num_blocks = _count(_require(abscissa, "nbr of scans", "abscissa"), "'nbr of scans'")
    if num_blocks < 1:
        raise HdfFormatError("the file holds no samples")
    block_samples = sum(per_block)
    block_period = time_step * block_samples if fmt.period_from_elements else time_step

    codec = _text_codec(text)
    channels = []
    offset = 0
    for position, fields in enumerate(channel_fields):
        where = f"channel {position + 1}"
        for key, expected in fmt.channel.items():
            if fields.get(key) != expected:
                raise HdfFormatError(f"{where}: '{key}' is {fields.get(key)!r}; only {expected!r} is known")
        implementation = fields.get("implementation type")
        if implementation not in fmt.implementations:
            only = " or ".join(repr(name) for name in fmt.implementations)
            raise HdfFormatError(f"{where}: 'implementation type' is {implementation!r}; only {only} is known")
        factor = 1.0
        if fmt.scaled:
            if _number(_require(fields, "map offset", where), f"{where}: map offset") != 0.0:
                raise HdfFormatError(f"{where}: a non-zero 'map offset' is not known")
            factor = _number(_require(fields, "map factor", where), f"{where}: map factor")
            if not (factor > 0.0 and math.isfinite(factor)):
                raise HdfFormatError(f"{where}: 'map factor' {factor:g} is not positive and finite")
        dtype, _ = _IMPLEMENTATIONS[implementation]
        channels.append(_Channel(
            name=_decode(_require(fields, "name str", where), codec),
            unit=_decode(_require(fields, "physical unit", where), codec),
            factor=factor,
            dtype=dtype,
            per_block=per_block[position],
            offset=offset,
            readable=implementation != "UINT32",          # raw CAN frames, not a measured signal
            position=position,
        ))
        offset += per_block[position]

    widths = {_IMPLEMENTATIONS[fields["implementation type"]][1] for fields in channel_fields}
    if len(widths) != 1:
        raise HdfFormatError("the channels do not store samples of one width")
    sample_width = widths.pop()
    expected_bytes = num_blocks * block_samples * sample_width
    if data_bytes != expected_bytes:
        raise HdfFormatError(f"the header announces {data_bytes} bytes of samples, "
                             f"{num_blocks} scans of {block_samples} samples take {expected_bytes}")
    if file_size < data_offset + expected_bytes:
        raise HdfFormatError(f"the file is cut short: {file_size - data_offset} of {expected_bytes} bytes of samples")
    return _Layout(block_period=block_period, start_time=start_time, num_blocks=num_blocks,
                   block_samples=block_samples, sample_width=sample_width, data_offset=data_offset,
                   trailing_bytes=file_size - data_offset - expected_bytes, channels=tuple(channels))


def _parse_channel_order(text: str, count: int) -> List[int]:
    """
    Samples per block of channels 1..count from `ch order`: "1, 2, 3" is one sample of each,
    "50*1, 25*2, 3" is 50 of channel 1, 25 of channel 2 and one of channel 3, in that order.
    """
    per_block = []
    for number, token in enumerate(text.split(","), start=1):
        found = re.fullmatch(r"\s*(?:(\d+)\s*\*\s*)?(\d+)\s*", token)
        if found is None or int(found.group(2)) != number or int(found.group(1) or 1) < 1:
            raise HdfFormatError("channels are not stored in their defined order")
        per_block.append(int(found.group(1) or 1))
    if len(per_block) != count:
        raise HdfFormatError("channels are not stored in their defined order")
    return per_block


def _text_codec(text: str) -> str:
    """The header names its code page (`;#code page: 936`); names and units are in it."""
    found = re.search(r"^;#code page:\s*(\d+)", text, re.MULTILINE)
    if found:
        try:
            codecs.lookup(f"cp{found.group(1)}")
            return f"cp{found.group(1)}"
        except LookupError:
            pass
    return "latin-1"


def _decode(value: str, codec: str) -> str:
    """`value` was decoded as latin-1, byte for byte; read it again in the header's code page."""
    return value.encode("latin-1").decode(codec, errors="replace")


def _read_samples(file_path: str, layout: _Layout, position: int) -> np.ndarray:
    """
    One channel's samples as float64 in the channel's unit. The file stores
    all channels of one block together, so a channel is a run of values within every block.
    """
    channel = layout.channels[position]
    n = channel.per_block
    samples = np.empty(layout.num_blocks * n, dtype=np.float64)
    raw = np.memmap(file_path, dtype=channel.dtype, mode="r", offset=layout.data_offset,
                    shape=(layout.num_blocks, layout.block_samples))
    try:
        for start in range(0, layout.num_blocks, _READ_STEP):
            stop = min(start + _READ_STEP, layout.num_blocks)
            samples[start * n:stop * n] = raw[start:stop, channel.offset:channel.offset + n].reshape(-1)
    finally:
        del raw
    if channel.factor != 1.0:
        samples *= channel.factor
    return samples


_DIRECTIONS = {"X": 1, "Y": 2, "Z": 3}
_DIRECTION_IN_NAME = re.compile(r"^(?P<point>.*?)(?::|\s+)[+-](?P<axis>[XYZ])$")


def _split_point_and_direction(name: str) -> Tuple[str, int]:
    """
    "Acc_bolt_1:+X" or "LFMAS -Y" -> (point, direction); a name without a direction is (name, 0).
    Direction is X/Y/Z = 1/2/3; the sign is ignored (+Y and -Y are both 2). The sensor axes the
    header lists under `DOF` (always +x, +y, +z in cable order) are not used: they are the
    sensor's own axes, while the name carries the direction the sensor was mounted to measure.
    """
    found = _DIRECTION_IN_NAME.match(name.strip())
    if found is None:
        return name, 0
    return found.group("point").strip(), _DIRECTIONS[found.group("axis")]


def _response_dofs(channels: Tuple[_Channel, ...]) -> Dict[int, Tuple[int, int]]:
    """
    Response node and direction of every measured channel, keyed by position in the file.

    The file stores no node numbers; its channel name is "<point>:<direction>" ("Acc_bolt_1:+X")
    or "<point> <direction>" ("LFMAS +Y"). The UNV export numbers the points 1.. in plain sorted
    order of the point name (checked on a 39-channel recording). A name without a direction has
    direction 0, but still a point and a node.
    """
    split = {c.position: _split_point_and_direction(c.name) for c in channels if c.readable}
    node_of = {point: rank for rank, point in enumerate(sorted({p for p, _ in split.values()}), start=1)}
    return {position: (node_of[point], direction) for position, (point, direction) in split.items()}


class AccReaderHdf:
    """
    Parser for HEAD acoustics .hdf raw time recordings.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path

    def _layout(self) -> _Layout:
        try:
            return _read_layout(self.file_path)
        except HdfFormatError as exc:
            raise HdfFormatError(f"{os.path.basename(self.file_path)}: {exc}") from None

    def read_run_index(self) -> MeasurementRunIndex:
        """The file's channels and Lost parts, read from its header (MeasurementReader)."""
        run_index = MeasurementRunIndex(os.path.basename(self.file_path), self.file_path)
        self._read_channels(run_index)
        return run_index

    def _read_channels(self, run_index: MeasurementRunIndex) -> None:
        layout = self._layout()
        if layout.trailing_bytes:
            run_index.lost_parts.append(LostPart(None, f"{layout.trailing_bytes} bytes after the samples were not read"))
        dofs = _response_dofs(layout.channels)
        for channel in layout.channels:
            position = channel.position
            if not channel.readable:
                run_index.lost_parts.append(LostPart(None, f"channel '{channel.name}' holds raw CAN frames, not read"))
                continue
            channel_type = determine_channel_type(channel.unit, channel.name)
            meta = ChannelMetadata(index=position, name=channel.name, channel_type=channel_type, unit=channel.unit)
            meta.func_type = FUNC_TYPE_TIME_RESPONSE
            meta.rsp_node, meta.rsp_dir = dofs[position]
            meta.abscissa_inc = layout.time_step(channel)
            meta.abscissa_min = layout.start_time
            meta.num_pts = layout.num_pts(channel)
            meta.sampling_rate = 1.0 / layout.time_step(channel)
            meta.ordinate_axis_units_lab = channel.unit
            # Two channels may share a name, the key may not. "Set #N: " is the
            # label channel identity already strips, as for UNV.
            run_index.add_channel_metadata(f"Set #{position + 1}: {channel.name}", meta)

    def read_single_channel_data(self, dataset_index: int) -> RawChannel:
        layout = self._layout()
        if not 0 <= dataset_index < len(layout.channels):
            raise IndexError(
                f"Channel index {dataset_index} is not a channel of {os.path.basename(self.file_path)}."
            )
        channel = layout.channels[dataset_index]
        if not channel.readable:
            raise HdfFormatError(f"{os.path.basename(self.file_path)}: channel '{channel.name}' "
                                 f"holds raw CAN frames, not a measured signal")
        samples = _read_samples(self.file_path, layout, dataset_index)

        rsp_node, rsp_dir = _response_dofs(layout.channels)[dataset_index]
        dt = layout.time_step(channel)
        num_pts = layout.num_pts(channel)
        return RawChannel(
            name=channel.name,
            values=samples,
            times=layout.start_time + np.arange(num_pts, dtype=np.float64) * dt,
            acquisition=Acquisition(
                dt=dt,
                abscissa_min=layout.start_time,
                num_pts=num_pts,
                recorded_unit=channel.unit,
                rsp_node=rsp_node,
                rsp_dir=rsp_dir,
            ),
        )
