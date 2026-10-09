"""Which tab a set of Data Pool channels opens -- pure, no dock, no disk, no Qt."""

import dataclasses
from typing import Iterable, Tuple

from core.block_kinds import KIND_ORDER_CUT
from core.models import resolve_channel_block_kind
from view_models.analysis_kinds._analysis_kind import ANALYSIS_ORDERS, resolve_analysis_kind
from view_models.analysis_kinds._analysis_mode import ANALYSIS_MODE_ACC_ORDER_TRACKING, AnalysisMode

SKIP_IMPORTED = "imported"  # imported order cuts mixed with other channels outside Order Tracking (#509)
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


def resolve_open_plan(rows: Iterable[tuple], analysis_mode: AnalysisMode) -> OpenPlan:
    """
    Decide which Analysis kind `rows` open in `analysis_mode`, as one tab or a comparison tab.

    Imported order cuts alone open in Order Tracking whatever the mode; mixed
    with other channels they are skipped outside Order Tracking, so the
    active mode is never switched under the user (#509). Channels beyond the
    kind's `max_channels` are skipped. The plan does not check tacho: that is
    a fact about files, found by the background worker.
    """
    rows = list(rows)
    imported = [resolve_channel_block_kind(meta) == KIND_ORDER_CUT for _, meta, _ in rows]
    skipped = []
    if analysis_mode.name != ANALYSIS_MODE_ACC_ORDER_TRACKING and any(imported) and not all(imported):
        skipped = [(row, SKIP_IMPORTED) for row, is_imported in zip(rows, imported) if is_imported]
        rows = [row for row, is_imported in zip(rows, imported) if not is_imported]
        imported = [False] * len(rows)
    kind = ANALYSIS_ORDERS if any(imported) else analysis_mode.analysis_kind
    capacity = resolve_analysis_kind(kind).max_channels
    if capacity is not None:
        skipped += [(row, SKIP_CAPACITY) for row in rows[capacity:]]
        rows = rows[:capacity]
    return OpenPlan(kind, len(rows) > 1, tuple(rows), tuple(skipped))
