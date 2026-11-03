"""
A text table file (.txt, .csv) as the rows of cells a workbook sheet would give.

Encoding, column delimiter and decimal separator are detected from the file and
any of them can be set instead (`TextFormat`, blank = detect). Nothing is
dropped silently: a byte sequence that is not UTF-8 is read as Windows-1252
(ANSYS writes `m/s²` as one byte), and a line the csv parser refuses becomes one
text cell, which the number reading then counts as a lost row (§1.177).
"""

import csv
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

# The delimiters tried, in the order a tie between them is decided.
_DELIMITER_CANDIDATES = ("\t", ";", "|", ",")
_DETECT_LINES = 200
_NUMBER_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_DECIMAL_COMMA_RE = re.compile(r"^[+-]?\d+,\d+([eE][+-]?\d+)?$")
_DECIMAL_POINT_RE = re.compile(r"^[+-]?\d+\.\d+([eE][+-]?\d+)?$")
_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))


@dataclass(frozen=True)
class TextFormat:
    """How a text file is parsed; a blank field is detected from the file."""

    encoding: str = ""
    delimiter: str = ""
    decimal: str = ""


def is_text_table(path: str) -> bool:
    return path.lower().endswith((".txt", ".csv"))


def _is_utf16(raw: bytes) -> bool:
    return raw[:2] in (b"\xff\xfe", b"\xfe\xff")


def _read_bytes(path: str, max_row: Optional[int]) -> bytes:
    """The whole file, or only its first `max_row` lines (a UTF-16 file is read whole: its lines are not bytes)."""
    with open(path, "rb") as stream:
        head = stream.read(2)
        stream.seek(0)
        if max_row is None or _is_utf16(head):
            return stream.read()
        return b"".join(stream.readline() for _ in range(max_row))


def _detect_encoding(raw: bytes) -> str:
    for bom, name in _BOMS:
        if raw.startswith(bom):
            return name
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def _decode(raw: bytes, encoding: str) -> str:
    """The text; a byte the encoding does not define is read as the same byte in Latin-1, never dropped."""
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _detect_delimiter(lines: List[str]) -> str:
    """The candidate that splits most lines into the same number of cells (more than one cell), a tab on a tie."""
    best, best_score = "\t", 0
    for candidate in _DELIMITER_CANDIDATES:
        counts = [line.count(candidate) for line in lines if line.strip()]
        counts = [count for count in counts if count]
        if not counts:
            continue
        score = max(counts.count(count) for count in set(counts))
        if score > best_score:
            best, best_score = candidate, score
    return best


def _detect_decimal(rows: List[List[str]]) -> str:
    comma = point = 0
    for row in rows:
        for cell in row:
            cell = cell.strip()
            if _DECIMAL_COMMA_RE.match(cell):
                comma += 1
            elif _DECIMAL_POINT_RE.match(cell):
                point += 1
    return "," if comma > point else "."


def _split_lines(text: str, delimiter: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for line in text.splitlines():
        try:
            cells = next(csv.reader([line], delimiter=delimiter))
        except (csv.Error, StopIteration):
            cells = [line] if line else []
        if len(cells) == 1 and delimiter in cells[0]:
            cells = cells[0].split(delimiter)   # A line wrapped whole in quotes.
        rows.append(cells)
    return rows


def _detect(raw: bytes, overrides: TextFormat) -> Tuple[TextFormat, str]:
    """The format of the file (an override wins per field) and its decoded text."""
    encoding = overrides.encoding or _detect_encoding(raw)
    text = _decode(raw, encoding)
    if text.startswith("﻿"):
        text = text[1:]
    delimiter = overrides.delimiter or _detect_delimiter(text.splitlines()[:_DETECT_LINES])
    decimal = overrides.decimal
    if not decimal:
        decimal = "." if delimiter == "," else _detect_decimal(_split_lines(
            "\n".join(text.splitlines()[:_DETECT_LINES]), delimiter))
    return TextFormat(encoding, delimiter, decimal), text


def _convert_cell(cell: str, decimal: str):
    """A number when the cell is one in this decimal separator, None when blank, else the text itself."""
    stripped = cell.strip()
    if not stripped:
        return None
    candidate = stripped.replace(",", ".") if decimal == "," else stripped
    return float(candidate) if _NUMBER_RE.match(candidate) else cell


def resolve_text_format(path: str, overrides: TextFormat = TextFormat()) -> TextFormat:
    """What the file is parsed with: each field of `overrides` that is set, else detected from the head of the file."""
    return _detect(_read_bytes(path, _DETECT_LINES), overrides)[0]


def read_text_rows(path: str, overrides: TextFormat = TextFormat(),
                   max_row: Optional[int] = None) -> Tuple[Tuple[tuple, ...], TextFormat, TextFormat]:
    """
    The rows of cells of the file (numbers as floats, blank cells None), the
    format it was parsed with and the format detected from it. Reads only the
    first `max_row` lines when given.
    """
    raw = _read_bytes(path, max_row)
    used, text = _detect(raw, overrides)
    detected = used if not any((overrides.encoding, overrides.delimiter, overrides.decimal)) else (
        _detect(raw, TextFormat())[0])
    rows = tuple(tuple(_convert_cell(cell, used.decimal) for cell in cells)
                 for cells in _split_lines(text, used.delimiter))
    return rows, used, detected
