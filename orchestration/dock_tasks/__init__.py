"""
Background work for one open dock, and the one rule for whether its result
is still wanted when it lands (ADR §1.84).

A dock task is keyed by the dock *and* what it is for: a newer task with the
same purpose on the same dock supersedes the older one, a task with another
purpose does not -- a channel drop or an Evaluation recompute leaves a Refresh
in flight alone. Drops never supersede each other at all, since each one adds
curves. A result for a dock that has since closed is dropped.

What does not belong here: the threads and the queue (gui/jobs/, behind the
`JobRunner` port), what a task reads or computes (live_compute and friends),
and drawing the result (gui/).
"""

from orchestration.dock_tasks._dock_tasks import (
    PURPOSE_COMPUTE,
    PURPOSE_DROP,
    PURPOSE_EVALUATION,
    DockTasks,
)

__all__ = [
    "DockTasks",
    "PURPOSE_COMPUTE",
    "PURPOSE_DROP",
    "PURPOSE_EVALUATION",
]
