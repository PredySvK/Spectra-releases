"""
Live compute orchestration: background payload execution for interactive
analysis and overlays (what runs, in what order, when an analysis or overlay
tab is requested).

Plain worker functions (no Qt, no AppContext) that coordinate reading raw
channels from disk and running DSP pipelines for live workspace tabs.
`run_live_compute` is a dock's whole compute for one channel -- a restored
curve's Tab cache file, cache lookup, read, DSP -- in one worker task; `plan_compute_failure` is the one
table of what a failure does to the tab, by `ComputeOrigin`.
`resolve_restore_config` is the config a restored tab computes with: its
saved recipe over the ribbon's.

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
    read_order_channels,
    read_overall_level_channels,
)
from orchestration.live_compute._compute_origin import (
    FAILURE_CLOSE_TAB,
    FAILURE_KEEP_PLOT,
    FAILURE_MARK_FAILED,
    FAILURE_MARK_MISSING,
    PHASE_COMPUTE,
    PHASE_READ,
    ComputeOrigin,
    plan_compute_failure,
)
from orchestration.live_compute._cache_hit import (
    build_cache_hit_line,
    build_curve_subject,
    resolve_cache_finder,
)
from orchestration.live_compute._restore_config import (
    RestoreConfig,
    build_restore_config_line,
    resolve_restore_config,
)
from orchestration.live_compute._live_result import (
    LiveFailure,
    LiveRequest,
    LiveResult,
    run_live_compute,
)
from orchestration.live_compute._drop_workers import (
    DropRestore,
    run_overall_level_drops,
    run_order_drops,
    read_simple_drops,
)
from orchestration.live_compute._file_tracking import FileTracking
from orchestration.live_compute._live_order_memo import (
    RESULT_MEMO_LIMIT,
    LiveOrderMemo,
)

__all__ = [
    "ComputeOrigin",
    "DropRestore",
    "FAILURE_CLOSE_TAB",
    "FAILURE_KEEP_PLOT",
    "FAILURE_MARK_FAILED",
    "FAILURE_MARK_MISSING",
    "FileTracking",
    "LiveFailure",
    "LiveRequest",
    "LiveResult",
    "LiveOrderMemo",
    "PHASE_COMPUTE",
    "PHASE_READ",
    "RESULT_MEMO_LIMIT",
    "RestoreConfig",
    "build_cache_hit_line",
    "build_curve_subject",
    "build_restore_config_line",
    "run_overall_level_drops",
    "run_live_compute",
    "run_order_drops",
    "plan_compute_failure",
    "read_order_channels",
    "read_simple_drops",
    "resolve_cache_finder",
    "resolve_restore_config",
    "read_overall_level_channels",
    "read_spectrogram_channels",
    "read_two_channels",
]
