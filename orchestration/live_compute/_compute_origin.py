"""Why a dock is computing its base curve, and what a failure does to its tab."""

import enum
from typing import Optional

# Which half of a dock's compute failed: reaching the channel on disk, or
# turning it into a curve (DSP, or a precondition such as a missing tacho).
PHASE_READ = "read"
PHASE_COMPUTE = "compute"

# What a failed compute does to the tab that asked for it.
FAILURE_CLOSE_TAB = "close_tab"
FAILURE_MARK_MISSING = "mark_missing"
FAILURE_MARK_FAILED = "mark_failed"
FAILURE_KEEP_PLOT = "keep_plot"


class ComputeOrigin(enum.Enum):
    """
    Why a dock is computing its base curve. A restore is not a fresh open even
    though both start from an empty dock: a tab the user just opened can be
    closed again, a tab a project reopened must survive the next Save (#385).
    """
    FRESH_OPEN = "fresh_open"
    RESTORE = "restore"
    REFRESH = "refresh"


def plan_compute_failure(origin: Optional[ComputeOrigin], phase: str) -> str:
    """
    The one table of what a failed compute does to its tab, the same for
    every Analysis kind:

    - a fresh open has nothing on screen yet: the tab goes;
    - a restore whose file cannot be read becomes the "Missing" placeholder a
      dead link gets; one that read but failed to compute stays a live tab,
      so Save keeps it and a Refresh with other settings can still fix it;
    - a refresh -- or a compute nobody stamped an origin on -- keeps the plot
      already on screen.
    """
    if origin is ComputeOrigin.FRESH_OPEN:
        return FAILURE_CLOSE_TAB
    if origin is ComputeOrigin.RESTORE:
        return FAILURE_MARK_MISSING if phase == PHASE_READ else FAILURE_MARK_FAILED
    return FAILURE_KEEP_PLOT
