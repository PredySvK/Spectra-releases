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

from core.source_amplitude import VALID_SOURCE_AMPLITUDES

FORMAT_VERSION = 1

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

# Where a TextPick takes its text from.
PICK_HEADER = "header"
PICK_SHEET = "sheet"
PICK_FILE_NAME = "file_name"
PICK_FOLDER = "folder"
PICK_SOURCES = (PICK_HEADER, PICK_SHEET, PICK_FILE_NAME, PICK_FOLDER)


@dataclass(frozen=True)
class TextPick:
    """
    A piece of text around a channel.

    `source` is where the text is: a header cell of the channel's column
    (`header`; `row_above` counts rows up from the heading row, 0 = the heading
    row itself), the sheet name, the file name without its extension, or the
    name of the file's folder. The text is then optionally split (`split`,
    taking piece number `piece`), cut to what follows `after` and to what
    precedes `before`, and stripped -- in that order.
    """

    row_above: int = 0
    split: str = ""
    piece: int = 0
    after: str = ""
    before: str = ""
    source: str = PICK_HEADER

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "row_above": self.row_above, "split": self.split,
                "piece": self.piece, "after": self.after, "before": self.before}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TextPick":
        source = data.get("source", PICK_HEADER)
        if source not in PICK_SOURCES:
            raise ValueError(f"Unknown text source {source!r}; expected one of {PICK_SOURCES}.")
        return cls(row_above=int(data.get("row_above", 0)), split=data.get("split", ""),
                   piece=int(data.get("piece", 0)), after=data.get("after", ""),
                   before=data.get("before", ""), source=source)


# A channel name is these parts joined: a literal string or a pick.
NamePart = Union[str, TextPick]

# The characters a metadata source text is split at, unless the template says others.
DEFAULT_DELIMITERS = "_,:\\-;"
# The kinds a metadata field can be; a template piece's blank kind is
# detected from its values, as for any Raw metadata field.
FIELD_KINDS = ("str", "int", "float", "date")


@dataclass(frozen=True)
class MetadataPiece:
    """
    What one piece of a metadata source text becomes.

    `position` counts the pieces from 0, or from the end when negative (-1 =
    the last), so -- in a source that drops the pieces no rule names -- a text
    with one piece more in the middle still finds them.
    A blank `field` drops the piece: it is never stored. `key`, when set, is
    the key of a "key = value" or "key value" piece; the field then takes the
    value, and a piece with another key does not fit. `split_unit` reads the
    value as a number followed by `unit` ("-70Nm"); another unit does not fit.
    `kind` overrides the field kind detected from the values.
    """

    position: int
    field: str = ""
    key: str = ""
    split_unit: bool = False
    unit: str = ""
    kind: str = ""

    @property
    def is_dropped(self) -> bool:
        return not self.field.strip()

    def to_dict(self) -> Dict[str, Any]:
        return {"position": self.position, "field": self.field, "key": self.key,
                "split_unit": self.split_unit, "unit": self.unit, "kind": self.kind}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetadataPiece":
        kind = data.get("kind", "")
        if kind and kind not in FIELD_KINDS:
            raise ValueError(f"Unknown field kind {kind!r}; expected one of {FIELD_KINDS}.")
        return cls(position=int(data["position"]), field=str(data.get("field", "")),
                   key=str(data.get("key", "")), split_unit=bool(data.get("split_unit", False)),
                   unit=str(data.get("unit", "")), kind=kind)


@dataclass(frozen=True)
class MetadataSource:
    """
    A text around a channel that metadata is taken from: the file name, the
    folder, the sheet name or a column header row (`row_above` as in
    TextPick). The text is split at every character of `delimiters` into
    pieces (blank pieces left out; a "-" that is a number's sign, "-70Nm",
    does not split), and each piece is what one of `pieces`
    says. A piece no rule names does not fit the template -- unless
    `drop_unknown`, when it is dropped like a named one.
    """

    source: str
    row_above: int = 0
    delimiters: str = DEFAULT_DELIMITERS
    pieces: Tuple[MetadataPiece, ...] = ()
    drop_unknown: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"source": self.source, "row_above": self.row_above, "delimiters": self.delimiters,
                "pieces": [piece.to_dict() for piece in self.pieces], "drop_unknown": self.drop_unknown}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetadataSource":
        source = data.get("source")
        if source not in PICK_SOURCES:
            raise ValueError(f"Unknown text source {source!r}; expected one of {PICK_SOURCES}.")
        return cls(source=source, row_above=int(data.get("row_above", 0)),
                   delimiters=str(data.get("delimiters", DEFAULT_DELIMITERS)),
                   pieces=tuple(MetadataPiece.from_dict(piece) for piece in data.get("pieces", ())),
                   drop_unknown=bool(data.get("drop_unknown", False)))


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
    fixed number or a pick, and only an order cut has one: the other data kinds
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
    in Hz or a pick of a header text such as "Sample rate: 25.6 kHz", gives the
    rate); `speed_channel`, when set, is the name of the channel that is the
    speed (rpm, or the tacho's own unit), read as a tacho. `metadata` are the texts metadata fields are taken from; a
    field has one source only. `skipped_columns` are the channels of the read
    sheets that are not read, each as (sheet name, amplitude column number from
    0): what the wizard's duplicate check writes when the user keeps one copy,
    so later files are not checked again. `decimal_separator`, `delimiter` and
    `encoding` are how a text file (.txt, .csv) is parsed; blank is detected
    from each file and a value here wins over the detection.
    """

    name: str
    file_pattern: str
    anchor_text: str
    channel_name: Tuple[NamePart, ...]
    order: Union[float, TextPick]
    layout: str = LAYOUT_XY_PAIRS
    data_kind: str = DATA_KIND_ORDER_CUT
    simulated: bool = True
    source_amplitude: str = "peak"
    fixed_source_amplitude: str = ""
    values_in_db: bool = False
    db_reference: float = 0.0
    time_column: bool = True
    sample_rate: Union[float, TextPick] = 0.0
    speed_channel: str = ""
    sheets: Tuple[str, ...] = ()
    sheet_rule: str = SHEETS_LISTED
    sheet_count: int = 1
    heading_row: int = 0
    data_offset: int = 1
    x_unit: str = ""
    amplitude_unit: str = ""
    channel_type: str = ""
    axis: Optional[TextPick] = None
    metadata: Tuple[MetadataSource, ...] = ()
    skipped_columns: Tuple[Tuple[str, int], ...] = ()
    decimal_separator: str = ""
    delimiter: str = ""
    encoding: str = ""
    format_version: int = FORMAT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
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
            "channel_name": [part.to_dict() if isinstance(part, TextPick) else part
                             for part in self.channel_name],
            "axis": self.axis.to_dict() if self.axis is not None else None,
            "order": self.order.to_dict() if isinstance(self.order, TextPick) else self.order,
            "simulated": self.simulated,
            "source_amplitude": self.source_amplitude,
            "fixed_source_amplitude": self.fixed_source_amplitude,
            "values_in_db": self.values_in_db,
            "db_reference": self.db_reference,
            "time_column": self.time_column,
            "sample_rate": self.sample_rate.to_dict() if isinstance(self.sample_rate, TextPick) else self.sample_rate,
            "speed_channel": self.speed_channel,
            "metadata": [source.to_dict() for source in self.metadata],
            "skipped_columns": [[sheet, column] for sheet, column in self.skipped_columns],
            "decimal_separator": self.decimal_separator,
            "delimiter": self.delimiter,
            "encoding": self.encoding,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImportTemplate":
        """The template a dict describes; ValueError for a shape this build cannot read."""
        version = data.get("format_version")
        if version != FORMAT_VERSION:
            raise ValueError(f"Import template format version {version!r} is not readable; "
                             f"this build reads version {FORMAT_VERSION}.")
        layout, data_kind = data.get("layout"), data.get("data_kind")
        if layout not in LAYOUTS:
            raise ValueError(f"Unknown column layout {layout!r}; expected one of {LAYOUTS}.")
        if data_kind not in DATA_KINDS:
            raise ValueError(f"Unknown data kind {data_kind!r}; expected one of {DATA_KINDS}.")
        source_amplitude = data.get("source_amplitude")
        if source_amplitude not in VALID_SOURCE_AMPLITUDES:
            raise ValueError(f"Unknown source amplitude {source_amplitude!r}.")
        fixed = data.get("fixed_source_amplitude", "")
        if fixed and fixed not in VALID_SOURCE_AMPLITUDES:
            raise ValueError(f"Unknown source amplitude {fixed!r}.")
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
        time_column = bool(data.get("time_column", True))
        sample_rate = data.get("sample_rate", 0.0)
        sample_rate = TextPick.from_dict(sample_rate) if isinstance(sample_rate, dict) else float(sample_rate)
        if not isinstance(sample_rate, TextPick) and sample_rate < 0:
            raise ValueError(f"A sample rate cannot be {sample_rate}.")
        if data_kind == DATA_KIND_TIME_SIGNAL and not time_column:
            if layout == LAYOUT_XY_PAIRS:
                raise ValueError("A time signal without a time column has one column per signal, "
                                 "not pairs of columns.")
            if not isinstance(sample_rate, TextPick) and sample_rate <= 0:
                raise ValueError("A time signal without a time column needs its sample rate.")
        order, axis = data["order"], data.get("axis")
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
        return cls(
            name=data["name"], file_pattern=data["file_pattern"], anchor_text=anchor_text,
            sheets=tuple(str(sheet) for sheet in data.get("sheets", ())),
            sheet_rule=sheet_rule, sheet_count=sheet_count,
            heading_row=heading_row, data_offset=data_offset,
            layout=layout, data_kind=data_kind,
            x_unit=data.get("x_unit", ""), amplitude_unit=data.get("amplitude_unit", ""),
            channel_type=data.get("channel_type", ""),
            channel_name=tuple(TextPick.from_dict(part) if isinstance(part, dict) else str(part)
                               for part in data["channel_name"]),
            axis=TextPick.from_dict(axis) if isinstance(axis, dict) else None,
            order=TextPick.from_dict(order) if isinstance(order, dict) else float(order),
            simulated=bool(data.get("simulated", True)), source_amplitude=source_amplitude,
            fixed_source_amplitude=fixed, values_in_db=bool(data.get("values_in_db", False)),
            db_reference=db_reference, time_column=time_column, sample_rate=sample_rate,
            speed_channel=str(data.get("speed_channel", "")),
            metadata=tuple(MetadataSource.from_dict(source) for source in data.get("metadata", ())),
            skipped_columns=tuple((str(sheet), int(column))
                                  for sheet, column in data.get("skipped_columns", ())),
            decimal_separator=decimal, delimiter=delimiter, encoding=encoding,
        )
