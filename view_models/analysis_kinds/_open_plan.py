"""Which tab a set of Data Pool channels opens -- pure, no dock, no disk, no Qt."""

import dataclasses
from typing import Iterable, Optional, Tuple

from core.models import READING_IMPORTED_RESULT, resolve_channel_block_kind, resolve_channel_reading
from view_models.analysis_kinds._analysis_kind import resolve_analysis_kind, resolve_imported_analysis_kind
from view_models.analysis_kinds._analysis_mode import AnalysisMode

SKIP_IMPORTED = "imported"  # an imported result that the opened tab does not show (#509)
SKIP_CAPACITY = "capacity"  # beyond the Analysis kind's max_channels


@dataclasses.dataclass(frozen=True)
class OpenPlan:
    """
    The tab `resolve_open_plan` decided on.

    `rows` are the `(run_index, channel_meta, label)` rows to load, `skipped`
    the `(row, reason)` pairs left out. `is_comparison` is False for one
    channel, which opens the mode's own single tab; True for several, which
    open one comparison tab of `analysis_kind`.
    """
    analysis_kind: str
    is_comparison: bool
    rows: Tuple[tuple, ...]
    skipped: Tuple[Tuple[tuple, str], ...] = ()


def resolve_channel_analysis_kind(channel) -> Optional[str]:
    """The Analysis kind that shows `channel` when it is an Imported result, else None."""
    if resolve_channel_reading(channel) != READING_IMPORTED_RESULT:
        return None
    return resolve_imported_analysis_kind(resolve_channel_block_kind(channel))


def resolve_open_plan(rows: Iterable[tuple], analysis_mode: AnalysisMode) -> OpenPlan:
    """
    Decide which Analysis kind `rows` open in `analysis_mode`, as one tab or a comparison tab.

    Imported results alone open in the Analysis kind that shows their Block
    kind (order cuts in Order Tracking, a spectrum in a Spectrum graph, an
    Overall Level in an Overall Level graph) whatever the mode; of several
    kinds the first decides and the others are skipped. Mixed with other
    channels they open only when the active mode is their own kind and are
    skipped otherwise, so the active mode is never switched under the user
    (#509). Channels beyond the kind's `max_channels` are skipped. The plan
    does not check tacho: that is a fact about files, found by the
    background worker.
    """
    rows = list(rows)
    shown_by = [resolve_channel_analysis_kind(meta) for _, meta, _ in rows]
    kind = analysis_mode.analysis_kind
    skipped = []
    if any(shown_by):
        kind = next(shown for shown in shown_by if shown) if all(shown_by) else kind
        keep = [shown is None or shown == kind for shown in shown_by]
        skipped = [(row, SKIP_IMPORTED) for row, kept in zip(rows, keep) if not kept]
        rows = [row for row, kept in zip(rows, keep) if kept]
    capacity = resolve_analysis_kind(kind).max_channels
    if capacity is not None:
        skipped += [(row, SKIP_CAPACITY) for row in rows[capacity:]]
        rows = rows[:capacity]
    return OpenPlan(kind, len(rows) > 1, tuple(rows), tuple(skipped))
