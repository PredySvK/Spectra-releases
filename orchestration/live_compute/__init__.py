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
saved Curve recipe, the ribbon's only without one.
`BaseCurveCompute` owns the whole life of a tab's Base curve compute -- start,
landing, failure, what the tab gets back and what the Tab cache keeps -- with
the tab behind `BaseCurveTarget`; `plan_last_n_refresh` decides
which curves a Refresh Last N recomputes.

What does not belong here: Qt widgets or dock manipulation (gui/), plot
models or curve formatting (view_models/), active project state (session/),
or core DSP algorithms (signal_processing/) -- orchestration coordinates
them, it does not implement them.
"""

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
from orchestration.live_compute._base_curve_compute import BaseCurveCompute, BaseCurveTarget
from orchestration.live_compute._last_n_refresh import plan_last_n_refresh

__all__ = [
    "BaseCurveCompute",
    "BaseCurveTarget",
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
    "PHASE_COMPUTE",
    "PHASE_READ",
    "RestoreConfig",
    "build_cache_hit_line",
    "build_curve_subject",
    "build_restore_config_line",
    "run_overall_level_drops",
    "run_live_compute",
    "run_order_drops",
    "plan_compute_failure",
    "plan_last_n_refresh",
    "read_simple_drops",
    "resolve_cache_finder",
    "resolve_restore_config",
]
