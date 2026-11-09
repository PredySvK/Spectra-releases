"""
view_models.analysis_kinds -- one register entry per Analysis kind.

Architecture:
- View-model floor (Floor 3): What does an open dock of a given Analysis kind
  ("time", "spectrum", "spectrogram", "orders", "overall_level") mean for how
  it is shown -- its name on a tab, the Block kind it computes, which of that
  Block kind's parameters are display-only, what its Refresh and a missing
  tacho say -- and which Analysis kind and settings does the active ribbon tab
  (the Analysis mode) open?
- Register: AnalysisKind, ANALYSIS_KINDS, resolve_analysis_kind and the
  ANALYSIS_* name constants; AnalysisMode, ANALYSIS_MODES,
  resolve_analysis_mode, resolve_analysis_mode_of_kind and the
  ANALYSIS_MODE_* name constants (ANALYSIS_MODE_WORKFLOW / _TOOLS name the
  two ribbon tabs that open no Analysis kind and are not in ANALYSIS_MODES).
- Open plan: resolve_open_plan decides, from channels and an Analysis mode,
  which kind opens, as one tab or a comparison tab, and which channels are
  skipped. An Imported result opens in the Analysis kind that shows its Block
  kind (resolve_imported_analysis_kind, resolve_channel_analysis_kind).
- DSP choices: resolve_dsp_choices (by Analysis kind) and
  resolve_dsp_choices_of_config (by DSP config DTO class) give a DSP kind's
  DspChoices -- every DSP parameter's ParameterChoices as ordered (label,
  value) pairs with label <-> value translation and the default (the DTO's
  field default), and its tracking StepRule per tracking mode. An editor of
  DSP parameters reads its lists from here instead of carrying a copy
 .
- Ribbon DSP fields: resolve_ribbon_dsp_fields gives the saved controls of a
  DSP ribbon tab as RibbonDspField -- parameter, QSettings key, kind (choice /
  flag / number / text) and default in the form QSettings keeps -- so the tab
  loads, saves and resets them from one list. Kept apart from
  DspChoices: the Workflow block form shares the choices but has no ribbon
  keys. The Tacho Tracking group keeps its own keys per tracking mode.

Analysis kind is not Block kind (CONTEXT.md "Kind"): an entry *points at* its
Block kind and reads `display_only_params` from `core.block_kinds`, it never
stands in for it.

What does NOT belong here: Qt widgets or drawing calls, or how a kind is read
and computed -- that is `orchestration.live_compute`.
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
    resolve_imported_analysis_kind,
)
from ._analysis_mode import (
    ANALYSIS_MODES,
    ANALYSIS_MODE_ACC_ORDER_TRACKING,
    ANALYSIS_MODE_ACC_OVERALL_LEVEL,
    ANALYSIS_MODE_ACC_SPECTROGRAM,
    ANALYSIS_MODE_ACC_SPECTRUM,
    ANALYSIS_MODE_PROJECT,
    ANALYSIS_MODE_TOOLS,
    ANALYSIS_MODE_WORKFLOW,
    AnalysisMode,
    resolve_analysis_mode,
    resolve_analysis_mode_of_kind,
)
from ._dsp_choices import (
    DspChoices,
    ParameterChoices,
    StepRule,
    resolve_dsp_choices,
    resolve_dsp_choices_of_config,
)
from ._ribbon_dsp_fields import (
    FIELD_CHOICE,
    FIELD_FLAG,
    FIELD_NUMBER,
    FIELD_TEXT,
    RibbonDspField,
    resolve_ribbon_dsp_fields,
)
from ._open_plan import (
    SKIP_CAPACITY, SKIP_IMPORTED, OpenPlan, resolve_channel_analysis_kind, resolve_open_plan,
)

__all__ = [
    "DspChoices",
    "ParameterChoices",
    "StepRule",
    "resolve_dsp_choices",
    "resolve_dsp_choices_of_config",
    "FIELD_CHOICE",
    "FIELD_FLAG",
    "FIELD_NUMBER",
    "FIELD_TEXT",
    "RibbonDspField",
    "resolve_ribbon_dsp_fields",
    "ANALYSIS_MODES",
    "AnalysisMode",
    "ANALYSIS_MODE_ACC_ORDER_TRACKING",
    "ANALYSIS_MODE_ACC_OVERALL_LEVEL",
    "ANALYSIS_MODE_ACC_SPECTROGRAM",
    "ANALYSIS_MODE_ACC_SPECTRUM",
    "ANALYSIS_MODE_PROJECT",
    "ANALYSIS_MODE_TOOLS",
    "ANALYSIS_MODE_WORKFLOW",
    "OpenPlan",
    "SKIP_CAPACITY",
    "SKIP_IMPORTED",
    "resolve_open_plan",
    "resolve_channel_analysis_kind",
    "resolve_imported_analysis_kind",
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
