# =====================================================================
# FILE: view_models/evaluation/_evaluation_table_view.py
# =====================================================================
"""
Qt-free formatting for the Evaluation card's table (ADR §1.64 point 11):
turns an EvaluationTable into row cell text/sort-key data and computes the
table's headers. EvaluationPanel (gui/bottom_panels/evaluation_panel.py)
does the Qt wiring -- building QTableWidgetItem, enabling widgets -- and
calls into this module for everything that doesn't need Qt.

rows_for_table's richer RowCells is the reuse point for future consumers
that need to know what's in a row, not just how it prints (pivot, trend
chart, PPTX report -- ADR §1.64's "not yet built" list, B10).
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from core.axis_projections import X_AXIS_NATIVE, resolve_x_axis_display
from core.data_block import KIND_SPECTRUM
from core.evaluation import EvaluationTable, SingleValue
from core.filter_card_config import (
    BUILTIN_COLUMN_KEYS, BUILTIN_COLUMN_LABELS,
    COLUMN_CHANNEL, COLUMN_DIRECTION, COLUMN_FILE_NAME,
    COLUMN_ORDER, COLUMN_PARAMETER_SET, COLUMN_RESULT_SET,
)
from core.units import UnitPreferences
from io_modules.metadata_schema import parse_value

COLUMNS = ("Channel", "Measurement", "Source", "Order / Band", "Value (RMS)", "at X", "Edge", "Parameter Set")

_EM_DASH = "—"


@dataclass(frozen=True)
class RowCells:
    """One Evaluation table row's cell texts and sort keys, in column order."""
    texts: Tuple[str, ...]
    sort_keys: Tuple[Any, ...]
    is_dash: bool


def _header_label_for_column(col_key: str, schema: Mapping[str, Mapping[str, Any]]) -> str:
    """Returns human-readable column label for a built-in or schema metadata field."""
    if col_key in BUILTIN_COLUMN_LABELS:
        return BUILTIN_COLUMN_LABELS[col_key]
    if col_key in schema:
        cfg = schema[col_key]
        return cfg.get("custom_label") or cfg.get("field_name") or col_key
    return col_key


def active_metadata_columns(
    selected_cols: Sequence[str], schema: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    """Filters a dock's selected metadata columns down to the active ones
    (BUGS.md M1 / ADR §1.64 point 10) -- a schema field the user deactivated
    stays selected in EvaluationConfig but drops out of the table."""
    active: List[str] = []
    for col_key in selected_cols:
        if col_key in BUILTIN_COLUMN_KEYS:
            active.append(col_key)
        elif col_key in schema:
            if schema[col_key].get("is_active", True) is not False:
                active.append(col_key)
    return active


def table_headers(
    table: EvaluationTable,
    selected_cols: Sequence[str],
    schema: Mapping[str, Mapping[str, Any]],
    spec_format: str,
    amp_mode: str,
    prefs: Optional[UnitPreferences],
) -> Tuple[List[str], List[str]]:
    """Returns (headers, active_meta_cols). active_meta_cols is the
    schema-filtered subset of selected_cols that rows_for_table must be
    called with for the row cells to line up with these headers."""
    units = set()
    x_units = set()
    for row in table.rows:
        if not row.is_empty:
            _, u = row.display_value(spec_format, amp_mode, prefs)
            if u:
                units.add(u)
            x_units.add(_x_display(row, prefs)[1])

    amp_label = "Peak" if amp_mode == "peak" else "RMS"
    if len(units) == 1:
        col4_header = f"Value ({next(iter(units))})"
    elif len(units) > 1:
        col4_header = f"Value ({amp_label})"
    else:
        acc_unit = getattr(prefs, "acceleration", "g") if prefs else "g"
        if spec_format == "power":
            col4_header = f"Value (({acc_unit})^2)"
        elif spec_format == "psd":
            col4_header = f"Value (({acc_unit})^2/Hz)"
        else:
            col4_header = f"Value ({acc_unit} {amp_label})"

    active_meta_cols = active_metadata_columns(selected_cols, schema)

    headers = list(COLUMNS)
    headers[4] = col4_header
    # Named in the header too, so an exported CSV says what its X column is in.
    if len(x_units) == 1:
        headers[5] = f"{headers[5]} ({next(iter(x_units))})"
    for col_key in active_meta_cols:
        headers.append(_header_label_for_column(col_key, schema))
    return headers, active_meta_cols


def has_spectra(table: EvaluationTable) -> bool:
    """Whether the table has any spectrum-kind rows -- the Format switcher
    (Linear/Power/PSD) only applies to those."""
    return any(row.block.kind == KIND_SPECTRUM for row in table.rows)


_BAND_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*(?:hz)?\s*[-–—]\s*(?:([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\s*(?:hz)?|full(?:\s+bandwidth)?)\s*$",
    re.IGNORECASE,
)


class _BandSortKey(tuple):
    """Sort key for frequency bands: (f_start, f_stop), interoperable with scalar orders."""

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return super().__lt__((float(other),))
        return super().__lt__(other)

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return super().__gt__((float(other),))
        return super().__gt__(other)

    def __le__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return super().__le__((float(other),))
        return super().__le__(other)

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, (int, float)):
            return super().__ge__((float(other),))
        return super().__ge__(other)


def _parse_numeric_sort_key(text: str) -> Any:
    if not text or text == _EM_DASH:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    if text.startswith("Order "):
        # "Order 4.79" or "Order 4.79 (±0.2)" -- the number is the first token.
        try:
            return float(text[6:].split()[0])
        except (ValueError, IndexError):
            pass
    band_match = _BAND_RE.match(text)
    if band_match:
        f_start = float(band_match.group(1))
        stop_grp = band_match.group(2)
        f_stop = float(stop_grp) if stop_grp is not None else math.inf
        return _BandSortKey((f_start, f_stop))
    parts = text.split()
    if parts:
        try:
            return float(parts[0])
        except ValueError:
            pass
    return text.casefold()


def _extract_column_value(
    single: SingleValue,
    col_key: str,
    schema: Optional[Mapping[str, Mapping[str, Any]]],
) -> Tuple[str, Any]:
    """
    Extracts (text, sort_key) for a metadata or built-in column from single.identity.

    Strictly uses typed values or io_modules.metadata_schema.parse_value.
    Missing / empty values return ("", None).
    """
    val = single.identity.metadata.get(col_key) if single.identity.metadata else None
    if val is None or val == "":
        if col_key == COLUMN_CHANNEL:
            val = single.identity.channel
        elif col_key == COLUMN_DIRECTION:
            val = single.identity.direction
        elif col_key == COLUMN_FILE_NAME:
            val = single.identity.measurement
        elif col_key == COLUMN_RESULT_SET:
            val = single.identity.source
        elif col_key == COLUMN_PARAMETER_SET:
            val = single.identity.parameter_set
        elif col_key == COLUMN_ORDER:
            val = _parse_numeric_sort_key(single.identity.order_or_band)

    if val is None or val == "":
        return "", None

    if isinstance(val, bool):
        return str(val), str(val).casefold()

    if isinstance(val, (int, float)):
        text = f"{val:g}" if isinstance(val, float) else str(val)
        return text, float(val)

    if schema and col_key in schema:
        kind = schema[col_key].get("kind", "str")
        if kind in ("int", "float"):
            parsed = parse_value(val, kind)
            if parsed is not None:
                text = f"{parsed:g}" if isinstance(parsed, float) else str(parsed)
                return text, float(parsed)

    return str(val), str(val).casefold()


def _x_display(single: SingleValue, prefs: Optional[UnitPreferences]) -> Tuple[float, str]:
    """Where a non-empty Single value sits on X, in the global X axis unit
    (issue #459) -- the same rescale the graph draws its X axis with."""
    x_axis_unit = prefs.x_axis_unit if prefs is not None else X_AXIS_NATIVE
    display = resolve_x_axis_display(single.x_quantity, x_axis_unit)
    if display.scale == 1.0:
        return single.x_value, single.x_unit
    return single.x_value * display.scale, display.unit


def _row_cells(
    single: SingleValue,
    spectrum_format: str,
    amplitude_mode: str,
    prefs: Optional[UnitPreferences],
    active_meta_cols: Sequence[str],
    schema: Optional[Mapping[str, Mapping[str, Any]]],
) -> RowCells:
    identity = single.identity
    if single.is_empty:
        value_text = _EM_DASH
        value_sort = None
        x_text = _EM_DASH
        x_sort = None
        is_dash = True
    else:
        value, unit = single.display_value(spectrum_format, amplitude_mode, prefs)
        value_text = f"{value:.4g} {unit}"
        value_sort = float(value) if value is not None else None
        x_value, x_unit = _x_display(single, prefs)
        x_text = f"{x_value:.4g} {x_unit}"
        x_sort = float(x_value)
        is_dash = False

    channel_text = f"{identity.channel} {identity.direction}".strip()
    order_text = identity.order_or_band
    order_sort = _parse_numeric_sort_key(order_text)
    edge_text = "Yes" if (single.is_edge and not is_dash) else ""

    texts: List[str] = [
        channel_text,
        identity.measurement,
        identity.source,
        order_text,
        value_text,
        x_text,
        edge_text,
        identity.parameter_set,
    ]
    sort_keys: List[Any] = [
        channel_text.casefold(),
        identity.measurement.casefold(),
        identity.source.casefold(),
        order_sort,
        value_sort,
        x_sort,
        edge_text.casefold() if edge_text else None,
        identity.parameter_set.casefold(),
    ]

    for col_key in active_meta_cols:
        c_text, c_sort = _extract_column_value(single, col_key, schema)
        texts.append(c_text)
        sort_keys.append(c_sort)

    return RowCells(texts=tuple(texts), sort_keys=tuple(sort_keys), is_dash=is_dash)


def rows_for_table(
    table: EvaluationTable,
    spectrum_format: str,
    amplitude_mode: str,
    prefs: Optional[UnitPreferences],
    active_meta_cols: Sequence[str] = (),
    schema: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> List[RowCells]:
    """Computes one RowCells per row of table, in table.rows order."""
    return [
        _row_cells(single, spectrum_format, amplitude_mode, prefs, active_meta_cols, schema)
        for single in table.rows
    ]


def to_clipboard_string(headers: Sequence[str], grid: Sequence[Sequence[str]]) -> str:
    """Tab-separated headers + grid, for pasting into Excel. Pure string
    join -- headers/grid come from whatever's currently visible in the
    table (including sort order and a row selection), which is
    EvaluationPanel's job to gather, not this module's."""
    lines = ["\t".join(headers)]
    for row in grid:
        lines.append("\t".join(row))
    return "\n".join(lines)


def to_csv_string(headers: Sequence[str], grid: Sequence[Sequence[str]]) -> str:
    """CSV-escaped headers + grid, same input contract as to_clipboard_string."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    for row in grid:
        writer.writerow(row)
    return output.getvalue()
