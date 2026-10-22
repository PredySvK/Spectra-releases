"""
view_models.evaluation -- Evaluation table presentation and data shaping.

Architecture:
- View-model floor (Floor 3): How should an evaluation table be shown, without Qt?
- Table formatting and headers: rows_for_table, table_headers, active_metadata_columns,
  has_spectra, COLUMNS, RowCells.
- Export formatting: to_clipboard_string, to_csv_string, build_xlsx_bytes, to_xlsx_bytes.
- Curve collection: curve_identities_for_traces turns already-selected traces
  into the (block, identity) pairs Evaluation runs over, without a dock.
  synthetic_trace_for_block wraps a single-block dock's content (a
  spectrogram) as a Trace so it can go through the same path.
- Column description: build_column_descriptor / build_schema_field_descriptor give one label and
  active flag per metadata column, shared by the table and the column dialog.
- Typed orders parameter parsing: parse_orders_text turns user input into float orders.

What does NOT belong here: Qt widgets or drawing calls (gui/), deciding what
runs (orchestration/), what project is currently open (session/), which
curves are relevant (selection/), or signal processing computation (signal_processing/).
"""

from ._evaluation_adapter import curve_identities_for_traces, synthetic_trace_for_block
from ._evaluation_columns import ColumnDescriptor, build_column_descriptor, build_schema_field_descriptor
from ._evaluation_table_view import (
    COLUMNS,
    RowCells,
    active_metadata_columns,
    build_xlsx_bytes,
    has_spectra,
    rows_for_table,
    table_headers,
    to_clipboard_string,
    to_csv_string,
    to_xlsx_bytes,
)
from ._orders import parse_orders_text

__all__ = [
    "ColumnDescriptor",
    "COLUMNS",
    "RowCells",
    "active_metadata_columns",
    "curve_identities_for_traces",
    "build_column_descriptor",
    "build_schema_field_descriptor",
    "build_xlsx_bytes",
    "has_spectra",
    "parse_orders_text",
    "rows_for_table",
    "synthetic_trace_for_block",
    "table_headers",
    "to_clipboard_string",
    "to_csv_string",
    "to_xlsx_bytes",
]
