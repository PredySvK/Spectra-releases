"""Whether a tab with a warning takes a new curve."""

from __future__ import annotations

from typing import Optional

from session.data_pool import DeadLink

_DEAD_LINK_REFUSAL = (
    "ERROR: Cannot add curves to a Missing tab -- it keeps waiting for its own source. "
    "Once that source is available, open the project again, or open the channel in a new tab."
)
_FAILED_REFUSAL = (
    "ERROR: Cannot add curves to a Failed tab -- it keeps waiting for its own curve. "
    "Change the settings and Refresh, or open the channel in a new tab."
)


def resolve_curve_refusal(*, dead_link: Optional[DeadLink], compute_failed: bool,
                          is_graph: bool) -> Optional[str]:
    """The log line that refuses a new curve on this tab; None when the tab takes it.

    A tab with a warning holds a saved recipe it could not bring back, and a new
    curve would take the place of its base curve. A spectrogram whose compute
    failed still takes a channel: a drop there replaces its channel and computes.
    """
    if dead_link is not None:
        return _DEAD_LINK_REFUSAL
    if compute_failed and is_graph:
        return _FAILED_REFUSAL
    return None
