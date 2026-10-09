"""
The one port through which orchestration hands work to a background queue.

This floor decides *what* runs and in what order; it never owns threads. The
`JobRunner` protocol is the whole of what a use case may ask of a queue, and
`JobLifecycle` shares transitions and callback handling between the adapters.
`SynchronousJobRunner` is the implementation that satisfies it without Qt --
for tests today and a headless CLI later (#148).

What does not belong here: the queue itself, its thread pools and its Qt
signals (gui/jobs/), and the vocabulary of a job -- `CancelToken`,
`JobRecord`, `JobState`, `JobCancelled`, `job_step` -- which is data and lives
in core/jobs.py.
"""

from orchestration.jobs._job_lifecycle import JobLifecycle
from orchestration.jobs._job_runner import JobRunner, SynchronousJobRunner

__all__ = [
    "JobLifecycle",
    "JobRunner",
    "SynchronousJobRunner",
]
