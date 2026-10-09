"""
view_models.analysis_kinds -- one register entry per Analysis kind.

Architecture:
- View-model floor (Floor 3): What does an open dock of a given Analysis kind
  ("time", "spectrum", "spectrogram", "orders", "overall_level") mean for how
  it is shown -- its name on a tab, the Block kind it computes and which of
  that Block kind's parameters are display-only -- and which Analysis kind and
  settings does the active ribbon tab (the Analysis mode) open?
- Register: AnalysisKind, ANALYSIS_KINDS, resolve_analysis_kind and the
  ANALYSIS_* name constants; AnalysisMode, ANALYSIS_MODES,
  resolve_analysis_mode, resolve_analysis_mode_of_kind and the
  ANALYSIS_MODE_* name constants.
- Open plan: resolve_open_plan decides, from channels and an Analysis mode,
  which kind opens, as one tab or a comparison tab, and which channels are
  skipped.

Analysis kind is not Block kind (CONTEXT.md "Kind"): an entry *points at* its
Block kind and reads `display_only_params` from `core.block_kinds`, it never
stands in for it.

What does NOT belong here: Qt widgets or drawing calls, or how a kind is read
and computed -- that dispatch reaches into the workspace and stays in gui/
(analysis_tabs._DISPATCH_SPECS), keyed by these names.
"""

from ._analysis_kind import (
    ANALYSIS_KINDS,
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTROGRAM,
    ANALYSIS_SPECTRUM,
    ANALYSIS_TIME,
    AnalysisKind,
    resolve_analysis_kind,
)
from ._analysis_mode import (
    ANALYSIS_MODES,
    ANALYSIS_MODE_ACC_ORDER_TRACKING,
    ANALYSIS_MODE_ACC_OVERALL_LEVEL,
    ANALYSIS_MODE_ACC_SPECTROGRAM,
    ANALYSIS_MODE_ACC_SPECTRUM,
    ANALYSIS_MODE_PROJECT,
    AnalysisMode,
    resolve_analysis_mode,
    resolve_analysis_mode_of_kind,
)
from ._open_plan import SKIP_CAPACITY, SKIP_IMPORTED, OpenPlan, resolve_open_plan

__all__ = [
    "ANALYSIS_MODES",
    "AnalysisMode",
    "ANALYSIS_MODE_ACC_ORDER_TRACKING",
    "ANALYSIS_MODE_ACC_OVERALL_LEVEL",
    "ANALYSIS_MODE_ACC_SPECTROGRAM",
    "ANALYSIS_MODE_ACC_SPECTRUM",
    "ANALYSIS_MODE_PROJECT",
    "OpenPlan",
    "SKIP_CAPACITY",
    "SKIP_IMPORTED",
    "resolve_open_plan",
    "resolve_analysis_mode",
    "resolve_analysis_mode_of_kind",
    "ANALYSIS_KINDS",
    "ANALYSIS_ORDERS",
    "ANALYSIS_OVERALL_LEVEL",
    "ANALYSIS_SPECTROGRAM",
    "ANALYSIS_SPECTRUM",
    "ANALYSIS_TIME",
    "AnalysisKind",
    "resolve_analysis_kind",
]
