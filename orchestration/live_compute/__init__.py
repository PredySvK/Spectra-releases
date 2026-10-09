"""
Live compute orchestration: background payload execution for interactive
analysis and overlays (what runs, in what order, when an analysis or overlay
tab is requested).

Plain worker functions (no Qt, no AppContext) that coordinate reading raw
channels from disk and running DSP pipelines for live workspace tabs.

What does not belong here: Qt widgets or dock manipulation (gui/), plot
models or curve formatting (view_models/), active project state (session/),
or core DSP algorithms (signal_processing/) -- orchestration coordinates
them, it does not implement them.
"""

from orchestration.live_compute._payloads import (
    read_spectrogram_channels,
    read_two_channels,
)
from orchestration.live_compute._dock_reads import (
    lookup_or_read_for_dock,
    read_order_channels,
    read_overall_level_channels,
)
from orchestration.live_compute._drop_workers import (
    build_overall_level_drop_payloads,
    lookup_or_compute_order_drops,
    read_simple_drops,
)
from orchestration.live_compute._compare_workers import (
    lookup_or_compute_order_cuts,
)
from orchestration.live_compute._file_tracking import FileTracking
from orchestration.live_compute._live_order_memo import (
    RESULT_MEMO_LIMIT,
    LiveOrderMemo,
)

__all__ = [
    "FileTracking",
    "LiveOrderMemo",
    "RESULT_MEMO_LIMIT",
    "build_overall_level_drop_payloads",
    "lookup_or_read_for_dock",
    "lookup_or_compute_order_cuts",
    "lookup_or_compute_order_drops",
    "read_order_channels",
    "read_simple_drops",
    "read_overall_level_channels",
    "read_spectrogram_channels",
    "read_two_channels",
]
