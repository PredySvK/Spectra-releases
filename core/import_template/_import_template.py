"""
The shape of the Import template (CONTEXT.md "Import template").

A template says which sheets of a table file are read, where their heading row
is (an anchor text in the first column, or a row number), how the columns form
channels, what they mean, and how the channel name, axis and order come out of
the text around them. It holds no user-written code: everything below is a
value the reader looks at.
"""

import codecs
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union

from core.import_template._text_source import ChipRef, MetadataField, TextSource
from core.source_amplitude import VALID_SOURCE_AMPLITUDES

# The texts around a channel are sources, chips and roles (_text_source.py).
FORMAT_VERSION = 2

# The one answer for the amplitude in the file: a Source amplitude, or
# "from the header", where a header that says only "Amplitude" does not fit.
AMPLITUDE_FROM_HEADER = "from_header"
FILE_AMPLITUDES = tuple(VALID_SOURCE_AMPLITUDES) + (AMPLITUDE_FROM_HEADER,)

# The roles a chip can have.
ROLE_NAME = "name"
ROLE_AXIS = "axis"
ROLE_ORDER = "order"
ROLE_SAMPLE_RATE = "sample_rate"
ROLE_FIELDS = "fields"
ROLES = (ROLE_NAME, ROLE_AXIS, ROLE_ORDER, ROLE_SAMPLE_RATE, ROLE_FIELDS)

# Column layout. xy_pairs: every channel is a pair of columns (X, amplitude) with
# its own X. shared_x: the first column is the X of every following column.
# single_curve: one curve per sheet, the first two columns.
LAYOUT_XY_PAIRS = "xy_pairs"
LAYOUT_SHARED_X = "shared_x"
LAYOUT_SINGLE_CURVE = "single_curve"
LAYOUTS = (LAYOUT_XY_PAIRS, LAYOUT_SHARED_X, LAYOUT_SINGLE_CURVE)

# Which sheets of a file a template reads. all: every sheet. first_n: the first
# `sheet_count`. without_last_n: all but the last `sheet_count`. listed: the
# sheets named in `sheets`, the first sheet when none is named.
SHEETS_ALL = "all"
SHEETS_FIRST_N = "first_n"
SHEETS_WITHOUT_LAST_N = "without_last_n"
SHEETS_LISTED = "listed"
SHEET_RULES = (SHEETS_ALL, SHEETS_FIRST_N, SHEETS_WITHOUT_LAST_N, SHEETS_LISTED)

# What the curves of a template are. order_cut: amplitude of one order against
# speed (the only kind that has an order); spectrum: amplitude against Hz;
# overall_level and order_residual: band energy against speed. Each opens in the
# graphs that show that block kind, like a computed one (§1.134). time_signal is
# no result but a measurement: samples against time, a waveform like a `.unv`
# one, so spectra, spectrograms and order cuts are computed from it.
DATA_KIND_ORDER_CUT = "order_cut"
DATA_KIND_SPECTRUM = "spectrum"
DATA_KIND_OVERALL_LEVEL = "overall_level"
DATA_KIND_ORDER_RESIDUAL = "order_residual"
DATA_KIND_TIME_SIGNAL = "time_signal"
DATA_KINDS = (DATA_KIND_ORDER_CUT, DATA_KIND_SPECTRUM, DATA_KIND_OVERALL_LEVEL, DATA_KIND_ORDER_RESIDUAL,
              DATA_KIND_TIME_SIGNAL)

# How a text file (.txt, .csv) is parsed; blank = detected from the sample.
DECIMAL_SEPARATORS = (".", ",")
COLUMN_DELIMITERS = ("\t", ";", ",", "|", " ")

# A text the template takes a number from: a fixed number or a chip.
StatedNumber = Union[float, ChipRef]


@dataclass(frozen=True)
class ImportTemplate:
    """
    One kind of table file.

    `sheet_rule` says which sheets are read (see SHEET_RULES); `sheets` are the
    sheet names read under the rule "listed", in order, and empty reads the first
    sheet; `sheet_count` is the N of "first_n" and "without_last_n".
    The heading row of each sheet is the row whose first cell is `anchor_text`
    or, when that is blank, row number `heading_row` (1 = the first row). The
    rows above it are the column header, data starts `data_offset` rows below
    it. `file_pattern` is the name pattern (fnmatch) of the files it reads.
    `x_unit` / `amplitude_unit` are taken from the trailing "(unit)" of the
    heading cells unless set here; `channel_type` blank is decided from the
    unit and name as for any reader. `axis`, when set, is appended to the
    channel name as ":X" so the channel's identity carries it. `order` is a
    fixed number or a text, and only an order cut has one: the other data kinds
    ignore it. `source_amplitude` is what a bare "Amplitude"
    header means (the header text "RMS Amplitude", "Peak Amplitude" or
    "Peak-to-Peak Amplitude" is recognised first); `fixed_source_amplitude`,
    when set, is the one value for the whole template and wins over
    recognition. A template-read file is never asked about its Source
    amplitude. `values_in_db` says the amplitude column is in dB re
    `db_reference` (in the amplitude unit; 0 = the usual reference of that unit);
    the reader turns it into linear amplitude. A time signal is read in the
    file's own amplitude (no Source amplitude): `time_column` says the first
    column is time (else every column is a signal and `sample_rate`, a number
    in Hz or a text such as "Sample rate: 25.6 kHz", gives the
    rate); `speed_channel`, when set, is the name of the channel that is the
    speed (rpm, or the tacho's own unit), read as a tacho. `skipped_columns` are the channels of the read
    sheets that are not read, each as (sheet name, amplitude column number from
    0): what the wizard's duplicate check writes when the user keeps one copy,
    so later files are not checked again. `decimal_separator`, `delimiter` and
    `encoding` are how a text file (.txt, .csv) is parsed; blank is detected
    from each file and a value here wins over the detection.

    The texts around a channel are `texts`, the TextSources split into chips,
    and every role names a chip by a ChipRef -- `channel_name` its chips in
    order (no literal text), `axis`, `order` and `sample_rate` one chip each
    (the last two or a fixed number), `metadata_fields` the fields. Its one
    amplitude answer is a Source amplitude (`fixed_source_amplitude` and
    `source_amplitude` both hold it) or "from the header" (both blank): a
    header that says only "Amplitude" then does not fit.
    """

    name: str
    file_pattern: str
    anchor_text: str
    channel_name: Tuple[ChipRef, ...]
    order: StatedNumber
    layout: str = LAYOUT_XY_PAIRS
    data_kind: str = DATA_KIND_ORDER_CUT
    simulated: bool = True
    source_amplitude: str = "peak"
    fixed_source_amplitude: str = ""
    values_in_db: bool = False
    db_reference: float = 0.0
    time_column: bool = True
    sample_rate: StatedNumber = 0.0
    speed_channel: str = ""
    sheets: Tuple[str, ...] = ()
    sheet_rule: str = SHEETS_LISTED
    sheet_count: int = 1
    heading_row: int = 0
    data_offset: int = 1
    x_unit: str = ""
    amplitude_unit: str = ""
    channel_type: str = ""
    axis: Optional[ChipRef] = None
    texts: Tuple[TextSource, ...] = ()
    metadata_fields: Tuple[MetadataField, ...] = ()
    skipped_columns: Tuple[Tuple[str, int], ...] = ()
    decimal_separator: str = ""
    delimiter: str = ""
    encoding: str = ""
    format_version: int = FORMAT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "format_version": self.format_version,
            "name": self.name,
            "file_pattern": self.file_pattern,
            "sheets": list(self.sheets),
            "sheet_rule": self.sheet_rule,
            "sheet_count": self.sheet_count,
            "anchor_text": self.anchor_text,
            "heading_row": self.heading_row,
            "data_offset": self.data_offset,
            "layout": self.layout,
            "data_kind": self.data_kind,
            "x_unit": self.x_unit,
            "amplitude_unit": self.amplitude_unit,
            "channel_type": self.channel_type,
            "simulated": self.simulated,
            "values_in_db": self.values_in_db,
            "db_reference": self.db_reference,
            "time_column": self.time_column,
            "speed_channel": self.speed_channel,
            "skipped_columns": [[sheet, column] for sheet, column in self.skipped_columns],
            "decimal_separator": self.decimal_separator,
            "delimiter": self.delimiter,
            "encoding": self.encoding,
        }
        data.update({
            "amplitude": self.fixed_source_amplitude or AMPLITUDE_FROM_HEADER,
            "texts": [source.to_dict() for source in self.texts],
            "roles": {
                ROLE_NAME: [part.to_dict() for part in self.channel_name],
                ROLE_AXIS: self.axis.to_dict() if self.axis is not None else None,
                ROLE_ORDER: _stated_to_dict(self.order),
                ROLE_SAMPLE_RATE: _stated_to_dict(self.sample_rate),
                ROLE_FIELDS: [field.to_dict() for field in self.metadata_fields],
            },
        })
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImportTemplate":
        """The template a dict describes; ValueError for a shape this build cannot read."""
        version = data.get("format_version")
        if version != FORMAT_VERSION:
            raise ValueError(f"Import template format version {version!r} is not readable; "
                             f"this build reads format {FORMAT_VERSION}.")
        shared = _parse_shared_fields(data)
        template = cls(format_version=version, **shared, **_parse_chip_texts(data, shared["data_kind"]))
        _check_time_signal(template)
        return template


def _stated_to_dict(stated: StatedNumber) -> Any:
    return stated if isinstance(stated, (int, float)) else stated.to_dict()


def _parse_shared_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """The fields that are not texts, checked."""
    layout, data_kind = data.get("layout"), data.get("data_kind")
    if layout not in LAYOUTS:
        raise ValueError(f"Unknown column layout {layout!r}; expected one of {LAYOUTS}.")
    if data_kind not in DATA_KINDS:
        raise ValueError(f"Unknown data kind {data_kind!r}; expected one of {DATA_KINDS}.")
    sheet_rule, sheet_count = data.get("sheet_rule", SHEETS_LISTED), int(data.get("sheet_count", 1))
    if sheet_rule not in SHEET_RULES:
        raise ValueError(f"Unknown sheet rule {sheet_rule!r}; expected one of {SHEET_RULES}.")
    if sheet_count < 1:
        raise ValueError(f"A sheet count cannot be {sheet_count}.")
    db_reference = float(data.get("db_reference", 0.0))
    if db_reference < 0:
        raise ValueError(f"A dB reference cannot be {db_reference}.")
    anchor_text, heading_row = data["anchor_text"], int(data.get("heading_row", 0))
    if not anchor_text.strip() and heading_row < 1:
        raise ValueError("An Import template needs an anchor text or a heading row number.")
    data_offset = int(data.get("data_offset", 1))
    if data_offset < 1:
        raise ValueError(f"Data cannot start {data_offset} rows below the heading row.")
    decimal, delimiter = data.get("decimal_separator", ""), data.get("delimiter", "")
    encoding = data.get("encoding", "")
    if decimal and decimal not in DECIMAL_SEPARATORS:
        raise ValueError(f"Unknown decimal separator {decimal!r}; expected one of {DECIMAL_SEPARATORS}.")
    if delimiter and delimiter not in COLUMN_DELIMITERS:
        raise ValueError(f"Unknown column delimiter {delimiter!r}; expected one of {COLUMN_DELIMITERS}.")
    if encoding:
        try:
            codecs.lookup(encoding)
        except LookupError:
            raise ValueError(f"Unknown text encoding {encoding!r}.") from None
    return dict(
        name=data["name"], file_pattern=data["file_pattern"], anchor_text=anchor_text,
        sheets=tuple(str(sheet) for sheet in data.get("sheets", ())),
        sheet_rule=sheet_rule, sheet_count=sheet_count,
        heading_row=heading_row, data_offset=data_offset,
        layout=layout, data_kind=data_kind,
        x_unit=data.get("x_unit", ""), amplitude_unit=data.get("amplitude_unit", ""),
        channel_type=data.get("channel_type", ""),
        simulated=bool(data.get("simulated", True)), values_in_db=bool(data.get("values_in_db", False)),
        db_reference=db_reference, time_column=bool(data.get("time_column", True)),
        speed_channel=str(data.get("speed_channel", "")),
        skipped_columns=tuple((str(sheet), int(column)) for sheet, column in data.get("skipped_columns", ())),
        decimal_separator=decimal, delimiter=delimiter, encoding=encoding,
    )


def _parse_chip_texts(data: Dict[str, Any], data_kind: str) -> Dict[str, Any]:
    """The texts of a template: sources, and the chips its roles take."""
    amplitude = data.get("amplitude")
    if amplitude not in FILE_AMPLITUDES:
        raise ValueError(f"Unknown amplitude in the file {amplitude!r}; expected one of {FILE_AMPLITUDES}.")
    texts = tuple(TextSource.from_dict(source) for source in data.get("texts", ()))
    keys = [source.key for source in texts]
    if len(set(keys)) != len(keys):
        raise ValueError("An Import template lists one text source twice.")
    roles = data.get("roles", {})
    unknown = sorted(set(roles) - set(ROLES))
    if unknown:
        raise ValueError(f"Unknown role {unknown[0]!r}; expected one of {ROLES}.")
    by_key = dict(zip(keys, texts))

    def chip(ref_data: Any, role: str) -> ChipRef:
        if not isinstance(ref_data, dict):
            raise ValueError(f"The role {role!r} takes a chip, not {ref_data!r}.")
        return checked(ChipRef.from_dict(ref_data), role)

    def checked(ref: ChipRef, role: str) -> ChipRef:
        source = by_key.get(ref.source_key)
        if source is None:
            raise ValueError(f"The role {role!r} takes a chip of the text source {ref.source!r} "
                             f"(row {ref.row_above} above the heading row), which the template does not list.")
        if ref.piece and all(cuts.chip != ref.chip for cuts in source.cut_chips):
            raise ValueError(f"The role {role!r} takes piece {ref.piece} of chip {ref.chip}, which has no own cuts.")
        return ref

    def stated(value: Any, role: str) -> StatedNumber:
        if isinstance(value, dict):
            return chip(value, role)
        number = float(value)
        if number < 0:
            raise ValueError(f"The {role.replace('_', ' ')} cannot be {number}.")
        return number

    name = tuple(chip(part, ROLE_NAME) for part in roles.get(ROLE_NAME, ()))
    if not name:
        raise ValueError("An Import template takes no chip for the channel name.")
    axis = roles.get(ROLE_AXIS)
    order = stated(roles.get(ROLE_ORDER, 0.0), ROLE_ORDER)
    if data_kind == DATA_KIND_ORDER_CUT and not isinstance(order, ChipRef) and order <= 0:
        raise ValueError("An order cut needs its order: a chip or a fixed number.")
    fields = tuple(MetadataField.from_dict(field) for field in roles.get(ROLE_FIELDS, ()))
    names = [field.field.casefold() for field in fields]
    if len(set(names)) != len(names):
        raise ValueError("A metadata field is taken from two chips; a field has one source only.")
    if data_kind == DATA_KIND_ORDER_CUT and "order" in names:
        raise ValueError("An order cut takes its order from the order role, not from a metadata field 'Order'.")
    for field in fields:
        checked(field.chip, ROLE_FIELDS)
    explicit = "" if amplitude == AMPLITUDE_FROM_HEADER else amplitude
    return dict(
        texts=texts, channel_name=name, axis=chip(axis, ROLE_AXIS) if axis is not None else None,
        order=order, sample_rate=stated(roles.get(ROLE_SAMPLE_RATE, 0.0), ROLE_SAMPLE_RATE),
        metadata_fields=fields, source_amplitude=explicit, fixed_source_amplitude=explicit,
    )


def _check_time_signal(template: ImportTemplate) -> None:
    if template.data_kind != DATA_KIND_TIME_SIGNAL or template.time_column:
        return
    if template.layout == LAYOUT_XY_PAIRS:
        raise ValueError("A time signal without a time column has one column per signal, not pairs of columns.")
    if isinstance(template.sample_rate, (int, float)) and template.sample_rate <= 0:
        raise ValueError("A time signal without a time column needs its sample rate.")

