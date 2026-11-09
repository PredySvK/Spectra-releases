"""
view_models.evaluation -- Evaluation table presentation and data shaping.

Architecture:
- View-model floor (Floor 3): How should an evaluation table be shown, without Qt?
- Table shaping: build_table_view gives one EvaluationTableView -- screen headers
  and RowCells plus export headers and rows -- so the screen, Copy and Export XLSX
  cannot disagree. active_metadata_columns, COLUMNS.
- Export: to_clipboard_string, build_xlsx_bytes write an EvaluationTableView in the
  row order the screen shows.
- Curve collection: curve_identities_for_traces turns already-selected traces
  into the (block, identity) pairs Evaluation runs over, without a dock.
  synthetic_trace_for_block wraps a single-block dock's content (a
  spectrogram) as a Trace so it can go through the same path.
- Typed orders parameter parsing: parse_orders_text turns user input into float orders.
- Card state: EvaluationCardState decides what the Evaluation card shows -- the
  focused dock's EvaluationConfig, staleness, the table or a message -- and
  when an EvaluationRun must start.

What does NOT belong here: Qt widgets or drawing calls (gui/), deciding what
runs (orchestration/), what project is currently open (session/), which
curves are relevant (selection/), or signal processing computation (signal_processing/).
"""

from ._evaluation_card_state import (
    NO_DOCK_MESSAGE,
    EvaluationCardState,
    EvaluationRun,
)
from ._evaluation_adapter import curve_identities_for_traces, synthetic_trace_for_block
from ._evaluation_table_view import (
    COLUMNS,
    EvaluationTableView,
    RowCells,
    active_metadata_columns,
    build_table_view,
    build_xlsx_bytes,
    to_clipboard_string,
)
from ._orders import parse_orders_text

__all__ = [
    "COLUMNS",
    "EvaluationCardState",
    "EvaluationRun",
    "NO_DOCK_MESSAGE",
    "EvaluationTableView",
    "RowCells",
    "active_metadata_columns",
    "curve_identities_for_traces",
    "build_table_view",
    "build_xlsx_bytes",
    "parse_orders_text",
    "synthetic_trace_for_block",
    "to_clipboard_string",
]
