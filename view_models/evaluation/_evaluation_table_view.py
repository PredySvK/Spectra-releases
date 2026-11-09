# =====================================================================
# FILE: view_models/evaluation/_evaluation_table_view.py
# =====================================================================
"""
Qt-free shaping of the Evaluation card's table:
one EvaluationTableView built from an EvaluationTable and the display
settings, holding both what the screen shows and what Copy and Export XLSX
write. EvaluationCard (gui/bottom_panels/evaluation_card.py) only puts
the screen rows into a QTableWidget and hands back which rows, in which
order, to export -- it never reads cell text back out of the widget.

The display settings come in as arguments, never from a panel, so a future
consumer (a workflow block, the report of B10) formats a table the same way
the card does.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from core.axis_projections import X_AXIS_NATIVE, resolve_x_axis_display
from core.data_block import KIND_SPECTRUM
from core.evaluation import CurveBand, CurveOrder, CurveResidual, EvaluationTable, OrderOrBand, SingleValue
from core.filter_card_config import BUILTIN_COLUMN_KEYS
from core.units import UnitPreferences
from selection.field_offer import is_active_field, resolve_field_label
from view_models.display_prefix import resolve_number_format

COLUMNS = ("Channel", "Measurement", "Source", "Order / Band", "Value (RMS)", "at X", "Edge", "Parameter Set")

_VALUE_COLUMN, _X_COLUMN = 4, 5
_VALUE_UNIT_HEADER, _X_UNIT_HEADER = "Value unit", "X unit"

# Where the unit columns sit in an export row (see _export_headers).
_VALUE_UNIT_EXPORT_COLUMN, _X_UNIT_EXPORT_COLUMN = _VALUE_COLUMN + 1, _X_COLUMN + 2

_EM_DASH = "—"


@dataclass(frozen=True)
class RowCells:
    """One row as the screen shows it: cell texts and sort keys, in column order."""
    texts: Tuple[str, ...]
    sort_keys: Tuple[Any, ...]
    is_dash: bool


@dataclass(frozen=True)
class ExportRow:
    """One row as Copy and Export XLSX write it, in export column order.

    Value and X are bare numbers -- their units sit in the Value unit and
    X unit columns next to them, filled even when the curve has no value.
    `texts` is what Copy writes (numbers rounded as on screen), `values`
    what XLSX writes (full-precision numbers, `number_formats` per cell).
    A missing value is "—" in both."""
    texts: Tuple[str, ...]
    values: Tuple[Any, ...]
    number_formats: Tuple[Optional[str], ...]


@dataclass(frozen=True)
class EvaluationTableView:
    """The Evaluation table shaped for display and export at once, so the
    screen, Copy and Export XLSX cannot disagree. `rows[i]` and
    `export_rows[i]` are the same Single value."""
    headers: Tuple[str, ...]
    rows: Tuple[RowCells, ...]
    export_headers: Tuple[str, ...]
    export_rows: Tuple[ExportRow, ...]
    metadata_columns: Tuple[str, ...]
    has_spectra: bool


def active_metadata_columns(
    selected_cols: Sequence[str], schema: Mapping[str, Mapping[str, Any]],
) -> List[str]:
    """Filters a dock's selected metadata columns down to the active ones
    -- a schema field the user deactivated
    stays selected in EvaluationConfig but drops out of the table."""
    active: List[str] = []
    for col_key in selected_cols:
        if col_key in BUILTIN_COLUMN_KEYS or (col_key in schema and is_active_field(schema[col_key])):
            active.append(col_key)
    return active


def build_table_view(
    table: EvaluationTable,
    spectrum_format: str,
    amplitude_mode: str,
    prefs: Optional[UnitPreferences],
    selected_cols: Sequence[str] = (),
    schema: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> EvaluationTableView:
    """The one shaping of `table` for the given display settings: screen
    headers and rows, export headers and rows, over the rows the table holds
    for `amplitude_mode` (EvaluationTable.rows_in), in that order."""
    schema = schema or {}
    meta_cols = active_metadata_columns(selected_cols, schema)
    singles = table.rows_in(amplitude_mode)
    meta_labels = [resolve_field_label(col_key, schema) for col_key in meta_cols]
    rows: List[RowCells] = []
    export_rows: List[ExportRow] = []
    for single in singles:
        row, export_row = _row_cells(single, spectrum_format, amplitude_mode, prefs, meta_cols)
        rows.append(row)
        export_rows.append(export_row)
    return EvaluationTableView(
        headers=tuple(_screen_headers(rows, export_rows, spectrum_format, amplitude_mode, prefs) + meta_labels),
        rows=tuple(rows),
        export_headers=tuple(_export_headers(amplitude_mode) + meta_labels),
        export_rows=tuple(export_rows),
        metadata_columns=tuple(meta_cols),
        has_spectra=_has_spectra(table),
    )


def _screen_headers(
    rows: Sequence[RowCells],
    export_rows: Sequence[ExportRow],
    spec_format: str,
    amp_mode: str,
    prefs: Optional[UnitPreferences],
) -> List[str]:
    """The fixed columns' headers: Value and at X name their unit when every
    row with a value shares one, Value always says RMS or Peak."""
    valued = [export_row for row, export_row in zip(rows, export_rows) if not row.is_dash]
    units = {export_row.values[_VALUE_UNIT_EXPORT_COLUMN] for export_row in valued}
    x_units = {export_row.values[_X_UNIT_EXPORT_COLUMN] for export_row in valued}
    units.discard("")
    x_units.discard("")

    amp_label = _amplitude_label(amp_mode)
    if len(units) == 1:
        value_header = f"Value ({next(iter(units))})"
    elif len(units) > 1:
        value_header = f"Value ({amp_label})"
    else:
        acc_unit = getattr(prefs, "acceleration", "g") if prefs else "g"
        if spec_format == "power":
            value_header = f"Value (({acc_unit})^2)"
        elif spec_format == "psd":
            value_header = f"Value (({acc_unit})^2/Hz)"
        else:
            shown_acc = resolve_number_format(acc_unit, prefs).shown_unit
            value_header = f"Value ({shown_acc} {amp_label})"

    headers = list(COLUMNS)
    headers[_VALUE_COLUMN] = value_header
    if len(x_units) == 1:
        headers[_X_COLUMN] = f"{headers[_X_COLUMN]} ({next(iter(x_units))})"
    return headers


def _export_headers(amp_mode: str) -> List[str]:
    """Export puts units in their own columns, so its headers never change
    with the data -- only Value's RMS / Peak."""
    headers = list(COLUMNS)
    headers[_VALUE_COLUMN] = f"Value ({_amplitude_label(amp_mode)})"
    headers.insert(_VALUE_COLUMN + 1, _VALUE_UNIT_HEADER)
    headers.insert(_X_COLUMN + 2, _X_UNIT_HEADER)
    return headers


def _amplitude_label(amp_mode: str) -> str:
    return "Peak" if amp_mode == "peak" else "RMS"


def _has_spectra(table: EvaluationTable) -> bool:
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


def _x_axis_unit(single: SingleValue, prefs: Optional[UnitPreferences]) -> Tuple[float, str]:
    """(scale, unit) of the global X axis unit for this curve's X (issue
    #459) -- the same rescale the graph draws its X axis with."""
    x_axis_unit = prefs.x_axis_unit if prefs is not None else X_AXIS_NATIVE
    display = resolve_x_axis_display(single.x_quantity, x_axis_unit)
    if display.scale == 1.0:
        return 1.0, single.x_unit
    return display.scale, display.unit


def _row_cells(
    single: SingleValue,
    spectrum_format: str,
    amplitude_mode: str,
    prefs: Optional[UnitPreferences],
    meta_cols: Sequence[str],
) -> Tuple[RowCells, ExportRow]:
    identity = single.identity
    # Units are known for a row without a value too: export writes them beside the "—".
    value, raw_value_unit = single.display_value(spectrum_format, amplitude_mode, prefs)
    value_format = resolve_number_format(raw_value_unit, prefs)
    value_unit = value_format.shown_unit
    scale, raw_x_unit = _x_axis_unit(single, prefs)
    x_format = resolve_number_format(raw_x_unit, prefs, quantity=single.x_quantity)
    x_unit = x_format.shown_unit
    if single.is_empty:
        value_text = value_copy = x_text = x_copy = _EM_DASH
        value_sort = x_sort = None
        value_cell: Any = _EM_DASH
        x_cell: Any = _EM_DASH
        value_fmt = x_fmt = None
    else:
        value_text = value_format.format_with_unit(value)
        value_copy = value_format.format(value)
        value_fmt = value_format.cell_format
        value_sort = value_cell = float(value_format.scale(value))

        x_value = single.x_value * scale
        x_text = x_format.format_with_unit(x_value)
        x_copy = x_format.format(x_value)
        x_fmt = x_format.cell_format
        x_sort = x_cell = float(x_format.scale(x_value))

    channel_text = f"{identity.channel} {identity.direction}".strip()
    order_text, order_sort = _order_or_band_cell(identity.order_or_band)
    edge_text = "Yes" if (single.is_edge and not single.is_empty) else ""

    texts: List[str] = [
        channel_text, identity.measurement, identity.source, order_text,
        value_text, x_text, edge_text, identity.parameter_set,
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
    export_texts: List[str] = [
        channel_text, identity.measurement, identity.source, order_text,
        value_copy, value_unit, x_copy, x_unit, edge_text, identity.parameter_set,
    ]
    export_values: List[Any] = [
        channel_text, identity.measurement, identity.source, order_text,
        value_cell, value_unit, x_cell, x_unit, edge_text, identity.parameter_set,
    ]
    export_formats: List[Optional[str]] = [None, None, None, None, value_fmt, None, x_fmt, None, None, None]

    for col_key in meta_cols:
        c_text, c_sort = _extract_column_value(single, col_key)
        texts.append(c_text)
        sort_keys.append(c_sort)
        export_texts.append(c_text)
        raw_meta = identity.curve_metadata.get(col_key) if identity.curve_metadata else None
        export_values.append(raw_meta if raw_meta is not None else "")
        export_formats.append("General" if isinstance(raw_meta, (int, float)) else None)

    return (
        RowCells(texts=tuple(texts), sort_keys=tuple(sort_keys), is_dash=single.is_empty),
        ExportRow(texts=tuple(export_texts), values=tuple(export_values), number_formats=tuple(export_formats)),
    )


def _export_rows(view: EvaluationTableView, row_order: Optional[Sequence[int]]) -> List[ExportRow]:
    """`row_order` indexes `view.rows` -- the order and subset the screen
    shows (sorted, selected); None means every row in the view's order."""
    if row_order is None:
        return list(view.export_rows)
    return [view.export_rows[index] for index in row_order]


def to_clipboard_string(view: EvaluationTableView, row_order: Optional[Sequence[int]] = None) -> str:
    """Tab-separated export headers + rows, for pasting into Excel: bare
    numbers rounded as on screen, units in their own columns."""
    lines = ["\t".join(view.export_headers)]
    for row in _export_rows(view, row_order):
        lines.append("\t".join(row.texts))
    return "\n".join(lines)


def build_xlsx_bytes(view: EvaluationTableView, row_order: Optional[Sequence[int]] = None) -> bytes:
    """The export headers + rows as an XLSX workbook in memory: numbers at
    full precision with the screen's number format, units in their own columns."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Evaluation"
    ws.append(list(view.export_headers))

    for r_idx, row in enumerate(_export_rows(view, row_order), start=2):
        for c_idx, (val, fmt) in enumerate(zip(row.values, row.number_formats), start=1):
            cell = ws.cell(row=r_idx, column=c_idx)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cell.value = val
                cell.number_format = fmt or "General"
            else:
                cell.value = str(val)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
