"""The Analysis kind register -- see the component facade."""

import dataclasses
from typing import Dict, Optional, Tuple

from core.block_kinds import (
    KIND_ORDER_CUT,
    KIND_ORDER_RESIDUAL,
    KIND_OVERALL_LEVEL,
    KIND_SPECTROGRAM,
    KIND_SPECTRUM,
    KIND_TIME_RESPONSE,
    spec_for,
)

ANALYSIS_TIME = "time"
ANALYSIS_SPECTRUM = "spectrum"
ANALYSIS_SPECTROGRAM = "spectrogram"
ANALYSIS_ORDERS = "orders"
ANALYSIS_OVERALL_LEVEL = "overall_level"


@dataclasses.dataclass(frozen=True)
class AnalysisKind:
    """
    What one Analysis kind means everywhere outside its compute dispatch.

    `name` is the one value on `dock.analysis_kind` and `TabSpec.analysis_kind`.
    `max_channels` is how many channels one dock of the kind holds (None: no
    limit) -- a property of the dock, not of the Analysis mode that opens it.

    `refresh_action` names the ribbon action that recomputes a tab of the kind
    in a refusal, `refresh_title` is what the graph says meanwhile; a kind
    that is only read (time) has neither. `cache_hit_settings` is what a
    cache hit's log line says matched. `tacho_missing_message` is the refusal,
    with a `{file_name}` slot, of a kind that cannot go without a tacho (empty:
    it can); `tacho_only_in_rpm_mode` limits that to rpm tracking.
    """
    name: str
    display_name: str
    title_prefix: str
    block_kind: str
    icon: str = ""
    max_channels: Optional[int] = None
    refresh_action: str = ""
    refresh_title: str = ""
    cache_hit_settings: str = "FFT settings"
    tacho_missing_message: str = ""
    tacho_only_in_rpm_mode: bool = False

    @property
    def display_only_params(self) -> Tuple[str, ...]:
        """The Block kind's display-only parameters, never a copy."""
        return spec_for(self.block_kind).display_only_params


ANALYSIS_KINDS: Tuple[AnalysisKind, ...] = (
    AnalysisKind(
        name=ANALYSIS_TIME, display_name="Time", title_prefix="",
        block_kind=KIND_TIME_RESPONSE, icon="⏱",
    ),
    AnalysisKind(
        name=ANALYSIS_SPECTRUM, display_name="Spectrum", title_prefix="📈 1D: ",
        block_kind=KIND_SPECTRUM, icon="📈",
        refresh_action="Refresh Spectrum", refresh_title="⏳ Recalculating 1D Spectrum...",
    ),
    AnalysisKind(
        name=ANALYSIS_SPECTROGRAM, display_name="Spectrogram", title_prefix="📦 Spec: ",
        block_kind=KIND_SPECTROGRAM, icon="📦", max_channels=1,
        refresh_action="Refresh Spectrogram", refresh_title="⏳ Recalculating...",
    ),
    AnalysisKind(
        name=ANALYSIS_ORDERS, display_name="Order tracking", title_prefix="⚡ Orders: ",
        block_kind=KIND_ORDER_CUT, icon="⚡",
        refresh_action="Extract Order Cuts", refresh_title="⏳ Reading channel...",
        tacho_missing_message="ERROR: Order Tracking strictly requires a Tacho channel in '{file_name}'.",
    ),
    AnalysisKind(
        name=ANALYSIS_OVERALL_LEVEL, display_name="Overall Level", title_prefix="📶 Overall Level: ",
        block_kind=KIND_OVERALL_LEVEL, icon="📶",
        refresh_action="Refresh Overall Level", refresh_title="⏳ Reading channel...",
        cache_hit_settings="settings",
        tacho_missing_message=(
            "ERROR: Overall Level tracked against RPM needs a Tacho channel in '{file_name}'. "
            "Switch Tracking Mode to 'Free Run (Time)' to view this channel."),
        tacho_only_in_rpm_mode=True,
    ),
)

_BY_NAME: Dict[str, AnalysisKind] = {kind.name: kind for kind in ANALYSIS_KINDS}


def resolve_analysis_kind(name: str) -> AnalysisKind:
    """The register entry for `name`, or ValueError naming what is registered."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise ValueError(
            f"unknown analysis kind {name!r}; registered: {', '.join(_BY_NAME)}"
        ) from None


# The Analysis kind whose graph shows an Imported result of a Block kind: the
# graph that shows the computed kind (§1.134). A Residual lives in an Order
# tracking graph, where a computed one is drawn beside the order cuts.
_SHOWN_BY: Dict[str, str] = {
    KIND_ORDER_CUT: ANALYSIS_ORDERS,
    KIND_ORDER_RESIDUAL: ANALYSIS_ORDERS,
    KIND_OVERALL_LEVEL: ANALYSIS_OVERALL_LEVEL,
    KIND_SPECTRUM: ANALYSIS_SPECTRUM,
}


def resolve_imported_analysis_kind(block_kind: Optional[str]) -> Optional[str]:
    """The Analysis kind that shows an Imported result of this Block kind, None for a kind no graph shows it in."""
    return _SHOWN_BY.get(block_kind or "")
