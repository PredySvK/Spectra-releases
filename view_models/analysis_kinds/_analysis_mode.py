"""The Analysis mode register -- see the component facade."""

import dataclasses
from typing import Dict, Optional, Tuple

from view_models.analysis_kinds._analysis_kind import (
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTROGRAM,
    ANALYSIS_SPECTRUM,
    ANALYSIS_TIME,
)

ANALYSIS_MODE_PROJECT = "project"
ANALYSIS_MODE_ACC_OVERALL_LEVEL = "acc_overall_level"
ANALYSIS_MODE_ACC_ORDER_TRACKING = "acc_order_tracking"
ANALYSIS_MODE_ACC_SPECTROGRAM = "acc_spectrogram"
ANALYSIS_MODE_ACC_SPECTRUM = "acc_spectrum"


@dataclasses.dataclass(frozen=True)
class AnalysisMode:
    """
    What the active ribbon analysis tab means: which Analysis kind it opens.

    `name` is the value on `AppContext.current_analysis_mode`. `settings_name`
    is the attribute its ribbon settings live under on the application
    context -- data only, this floor never reads it -- and is None for the
    Project mode, which has no settings of its own.
    """
    name: str
    analysis_kind: str
    settings_name: Optional[str]


ANALYSIS_MODES: Tuple[AnalysisMode, ...] = (
    AnalysisMode(ANALYSIS_MODE_PROJECT, ANALYSIS_TIME, None),
    AnalysisMode(ANALYSIS_MODE_ACC_OVERALL_LEVEL, ANALYSIS_OVERALL_LEVEL, "overall_level_settings"),
    AnalysisMode(ANALYSIS_MODE_ACC_ORDER_TRACKING, ANALYSIS_ORDERS, "order_tracking_settings"),
    AnalysisMode(ANALYSIS_MODE_ACC_SPECTROGRAM, ANALYSIS_SPECTROGRAM, "spectrogram_settings"),
    AnalysisMode(ANALYSIS_MODE_ACC_SPECTRUM, ANALYSIS_SPECTRUM, "spectrum_settings"),
)

_BY_NAME: Dict[str, AnalysisMode] = {mode.name: mode for mode in ANALYSIS_MODES}
_BY_KIND: Dict[str, AnalysisMode] = {mode.analysis_kind: mode for mode in ANALYSIS_MODES}


def resolve_analysis_mode(name: str) -> AnalysisMode:
    """The register entry for `name`; an unknown or non-analysis name (Workflow, Settings, Tools) is Project."""
    return _BY_NAME.get(name, _BY_NAME[ANALYSIS_MODE_PROJECT])


def resolve_analysis_mode_of_kind(analysis_kind: str) -> AnalysisMode:
    """The mode that opens `analysis_kind` (ValueError when none does)."""
    try:
        return _BY_KIND[analysis_kind]
    except KeyError:
        raise ValueError(f"no analysis mode opens analysis kind {analysis_kind!r}") from None
