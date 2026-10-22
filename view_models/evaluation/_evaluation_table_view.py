# =====================================================================
# FILE: view_models/evaluation/_evaluation_table_view.py
# =====================================================================
"""
Qt-free formatting for the Evaluation card's table:
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
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from core.axis_projections import X_AXIS_NATIVE, resolve_x_axis_display
from core.data_block import KIND_SPECTRUM
from core.evaluation import CurveBand, CurveOrder, CurveResidual, EvaluationTable, OrderOrBand, SingleValue
from core.units import UnitPreferences
from view_models.display_prefix import resolve_number_format

from ._evaluation_columns import build_column_descriptor

COLUMNS = ("Channel", "Measurement", "Source", "Order / Band", "Value (RMS)", "at X", "Edge", "Parameter Set")

_EM_DASH = "—"


@dataclass(frozen=True)
class RowCells:
    """One Evaluation table row's cell texts and sort keys, in column order."""
    texts: Tuple[str, ...]
    sort_keys: Tuple[Any, ...]
    is_dash: bool
    raw_values: Optional[Tuple[Any, ...]] = None
    number_formats: Optional[Tuple[Optional[str], ...]] = None


def _header_label_for_column(col_key: str, schema: Mapping[str, Mapping[str, Any]]) -> str:
    """Returns human-readable column label for a built-in or schema metadata field."""
    return build_column_descriptor(col_key, schema).label


def active_metadata_columns(
    selected_cols: Sequence[str], schema: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    """Filters a dock's selected metadata columns down to the active ones
    -- a schema field the user deactivated
    stays selected in EvaluationConfig but drops out of the table."""
    active: List[str] = []
    for col_key in selected_cols:
        if build_column_descriptor(col_key, schema).is_active:
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
    for row in table.rows_in(amp_mode):
        if not row.is_empty:
            _, u = row.display_value(spec_format, amp_mode, prefs)
            if u:
                shown_u = resolve_number_format(u, prefs).shown_unit
                if shown_u:
                    units.add(shown_u)
            x_val, x_u = _x_display(row, prefs)
            if x_u:
                shown_x_u = resolve_number_format(x_u, prefs, quantity=row.x_quantity).shown_unit
                if shown_x_u:
                    x_units.add(shown_x_u)

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
            shown_acc = resolve_number_format(acc_unit, prefs).shown_unit
            col4_header = f"Value ({shown_acc} {amp_label})"

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


# Orders sort before bands, bands before a Residual: an order and a band
# edge are not on one axis, so neither is compared with the other (#793).
_ORDER_GROUP, _BAND_GROUP, _RESIDUAL_GROUP = 0, 1, 2


def _order_or_band_cell(order_or_band: OrderOrBand) -> Tuple[str, Any]:
    """The one place the Order / Band column's (text, sort_key) is made from
    the typed value a curve carries. A curve with neither gives ("", None)."""
    if isinstance(order_or_band, CurveOrder):
        text = f"Order {order_or_band.order:g}"
        if order_or_band.width is not None:
            text += f" (±{order_or_band.width:g})"
        width_key = order_or_band.width if order_or_band.width is not None else 0.0
        return text, (_ORDER_GROUP, order_or_band.order, width_key)
    if isinstance(order_or_band, CurveBand):
        if order_or_band.f_stop is None:
            stop_text, stop_key = "Full Bandwidth", math.inf
        else:
            stop_text, stop_key = f"{order_or_band.f_stop:g} Hz", order_or_band.f_stop
        return f"{order_or_band.f_start:g}-{stop_text}", (_BAND_GROUP, order_or_band.f_start, stop_key)
    if isinstance(order_or_band, CurveResidual):
        return "Residual", (_RESIDUAL_GROUP, 0.0, 0.0)
    return "", None


def _extract_column_value(single: SingleValue, col_key: str) -> Tuple[str, Any]:
    """
    Formats (text, sort_key) for a metadata or built-in column from the typed
    Curve metadata record in single.identity.curve_metadata: numbers
    sort numerically, ISO dates chronologically as text. Missing / empty
    values return ("", None).
    """
    val = single.identity.curve_metadata.get(col_key) if single.identity.curve_metadata else None
    if val is None or val == "":
        return "", None
    if isinstance(val, bool):
        return str(val), str(val).casefold()
    if isinstance(val, (int, float)):
        text = f"{val:g}" if isinstance(val, float) else str(val)
        return text, float(val)
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
) -> RowCells:
    identity = single.identity
    if single.is_empty:
        value_text = _EM_DASH
        value_sort = None
        raw_val = None
        val_fmt = None
        x_text = _EM_DASH
        x_sort = None
        raw_x = None
        x_fmt = None
        is_dash = True
    else:
        value, unit = single.display_value(spectrum_format, amplitude_mode, prefs)
        value_format = resolve_number_format(unit, prefs)
        value_text = value_format.format_with_unit(value)
        val_fmt = value_format.cell_format
        value_sort = raw_val = float(value_format.scale(value))

        x_value, x_unit = _x_display(single, prefs)
        x_format = resolve_number_format(x_unit, prefs, quantity=single.x_quantity)
        x_text = x_format.format_with_unit(x_value)
        x_fmt = x_format.cell_format
        x_sort = raw_x = float(x_format.scale(x_value))

        is_dash = False

    channel_text = f"{identity.channel} {identity.direction}".strip()
    order_text, order_sort = _order_or_band_cell(identity.order_or_band)
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
    raw_values: List[Any] = [
        channel_text,
        identity.measurement,
        identity.source,
        order_text,
        raw_val,
        raw_x,
        edge_text,
        identity.parameter_set,
    ]
    number_formats: List[Optional[str]] = [
        None,
        None,
        None,
        None,
        val_fmt,
        x_fmt,
        None,
        None,
    ]

    for col_key in active_meta_cols:
        c_text, c_sort = _extract_column_value(single, col_key)
        texts.append(c_text)
        sort_keys.append(c_sort)
        raw_val_meta = single.identity.curve_metadata.get(col_key) if single.identity.curve_metadata else None
        raw_values.append(raw_val_meta if raw_val_meta is not None else "")
        number_formats.append("General" if isinstance(raw_val_meta, (int, float)) else None)

    return RowCells(
        texts=tuple(texts),
        sort_keys=tuple(sort_keys),
        is_dash=is_dash,
        raw_values=tuple(raw_values),
        number_formats=tuple(number_formats),
    )


def rows_for_table(
    table: EvaluationTable,
    spectrum_format: str,
    amplitude_mode: str,
    prefs: Optional[UnitPreferences],
    active_meta_cols: Sequence[str] = (),
) -> List[RowCells]:
    """Computes one RowCells per row the table holds for `amplitude_mode`
    (EvaluationTable.rows_in), in that order."""
    return [
        _row_cells(single, spectrum_format, amplitude_mode, prefs, active_meta_cols)
        for single in table.rows_in(amplitude_mode)
    ]


def _build_clipboard_string(headers: Sequence[str], grid: Sequence[Sequence[str]]) -> str:
    lines = ["\t".join(headers)]
    for row in grid:
        lines.append("\t".join(row))
    return "\n".join(lines)


def to_clipboard_string(
    headers_or_table: Sequence[str] | EvaluationTable,
    grid: Optional[Sequence[Sequence[str]]] = None,
    *,
    spectrum_format: str = "linear",
    amplitude_mode: str = "rms",
    prefs: Optional[UnitPreferences] = None,
    selected_cols: Sequence[str] = (),
    schema: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> str:
    """Tab-separated headers + grid, for pasting into Excel."""
    if isinstance(headers_or_table, EvaluationTable):
        table = headers_or_table
        headers, active_cols = table_headers(table, selected_cols, schema or {}, spectrum_format, amplitude_mode, prefs)
        rows = rows_for_table(table, spectrum_format, amplitude_mode, prefs, active_cols)
        grid_data = [r.texts for r in rows]
        return _build_clipboard_string(headers, grid_data)
    else:
        return _build_clipboard_string(headers_or_table, grid or ())


def _build_csv_string(headers: Sequence[str], grid: Sequence[Sequence[str]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    for row in grid:
        writer.writerow(row)
    return output.getvalue()


def to_csv_string(
    headers_or_table: Sequence[str] | EvaluationTable,
    grid: Optional[Sequence[Sequence[str]]] = None,
    *,
    spectrum_format: str = "linear",
    amplitude_mode: str = "rms",
    prefs: Optional[UnitPreferences] = None,
    selected_cols: Sequence[str] = (),
    schema: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> str:
    """CSV-escaped headers + grid (or EvaluationTable)."""
    if isinstance(headers_or_table, EvaluationTable):
        table = headers_or_table
        headers, active_cols = table_headers(table, selected_cols, schema or {}, spectrum_format, amplitude_mode, prefs)
        rows = rows_for_table(table, spectrum_format, amplitude_mode, prefs, active_cols)
        grid_data = [r.texts for r in rows]
        return _build_csv_string(headers, grid_data)
    else:
        return _build_csv_string(headers_or_table, grid or ())


def build_xlsx_bytes(
    headers_or_table: Sequence[str] | EvaluationTable,
    grid: Optional[Sequence[Sequence[Any]]] = None,
    number_formats: Optional[Sequence[Optional[str]] | Sequence[Sequence[Optional[str]]]] = None,
    *,
    spectrum_format: str = "linear",
    amplitude_mode: str = "rms",
    prefs: Optional[UnitPreferences] = None,
    selected_cols: Sequence[str] = (),
    schema: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> bytes:
    """Exports headers and grid (or EvaluationTable) to XLSX format in memory as bytes."""
    if isinstance(headers_or_table, EvaluationTable):
        table = headers_or_table
        headers, active_cols = table_headers(table, selected_cols, schema or {}, spectrum_format, amplitude_mode, prefs)
        rows = rows_for_table(table, spectrum_format, amplitude_mode, prefs, active_cols)
        grid_data = [r.raw_values if r.raw_values is not None else r.texts for r in rows]
        formats = [r.number_formats for r in rows]
        return _build_xlsx_bytes(headers, grid_data, formats)
    else:
        return _build_xlsx_bytes(headers_or_table, grid or (), number_formats)


def _build_xlsx_bytes(
    headers: Sequence[str],
    grid: Sequence[Sequence[Any]],
    number_formats: Optional[Sequence[Optional[str]] | Sequence[Sequence[Optional[str]]]] = None,
) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Evaluation"
    ws.append(list(headers))

    is_2d_formats = False
    if number_formats and len(number_formats) > 0 and isinstance(number_formats[0], (list, tuple)):
        is_2d_formats = True

    for r_idx, row in enumerate(grid, start=2):
        for c_idx, val in enumerate(row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx)
            if val is None or val == _EM_DASH:
                cell.value = _EM_DASH
            elif isinstance(val, (int, float)):
                cell.value = val
                fmt = None
                if number_formats:
                    if is_2d_formats and (r_idx - 2) < len(number_formats):
                        row_fmts = number_formats[r_idx - 2]
                        if (c_idx - 1) < len(row_fmts):
                            fmt = row_fmts[c_idx - 1]
                    elif not is_2d_formats and (c_idx - 1) < len(number_formats):
                        fmt = number_formats[c_idx - 1]
                if fmt:
                    cell.number_format = fmt
                else:
                    cell.number_format = "General"
            else:
                cell.value = str(val)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


to_xlsx_bytes = build_xlsx_bytes
