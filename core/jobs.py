# =====================================================================
# FILE: core/jobs.py
# =====================================================================
"""
The vocabulary of background work: what a job is, what state it is in, and
how it is asked to stop.

Lives in core/ rather than beside the QtJobRunner that runs jobs because
CancelToken travels *inward*: a long DSP loop in signal_processing/ or a
multi-file read in io_modules/ has to be able to check "should I stop?"
between items, and neither layer may import Qt or gui/. Keeping the token
here is what lets cancellation reach the code that actually takes the time,
instead of only being able to drop results after the fact.

Nothing here knows about threads. A CancelToken is a flag two threads read
and write; JobRecord is a description of one unit of work that the GUI
renders. The machinery that dispatches, times and marshals lives in
gui/jobs/.

All internal documentation strings and variable labels are standardly written
in English.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


def job_step(label: str, fn: Callable, *args, **kwargs) -> tuple:
    """Spelling helper so callers do not build the 4-tuples by hand."""
    return (label, fn, args, kwargs)


class JobCancelled(Exception):
    """
    Raised by CancelToken.raise_if_cancelled() to unwind a step that has been
    abandoned. Distinct from a real failure: the QtJobRunner treats it as a
    cancellation, not as an error to report to the user.
    """


class CancelToken:
    """
    A one-way flag: once cancelled, always cancelled.

    Deliberately not a threading.Event. An Event carries a lock and a wait()
    nobody here needs -- a step never blocks *on* cancellation, it only asks
    whether it should keep going. A plain bool assignment is atomic under the
    GIL, which is exactly and only what this needs to be correct.

    A step that never checks the token is still cancellable in the weaker
    sense every background result already is: the QtJobRunner stops dispatching
    further steps and drops what a cancelled step eventually returns. Checking
    the token is what turns "the answer is thrown away" into "the work stops".
    """
    __slots__ = ("_cancelled",)

    def __init__(self):
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def raise_if_cancelled(self) -> None:
        """For loops deep enough that returning a partial result is awkward."""
        if self._cancelled:
            raise JobCancelled()


class JobState(Enum):
    """
    QUEUED and RUNNING are live; the other four are terminal.

    FAILED means the job as a whole could not produce its result. A job whose
    individual steps failed but which still wrote what it could -- the shape
    "Calculate & Save Data" has, where one unreadable file must not lose the
    other thirty-nine -- finishes DONE and carries those failures in
    `errors`.

    CANCELLED is the user stopping a job. SUPERSEDED is the QtJobRunner stopping
    it because a newer job claimed its slot_key -- the folder watcher re-scanning
    a folder whose first ingest was still running, say. Same mechanism, but the
    user never asked for it and it is not a failure, so it reads differently in
    the Jobs dock.
    """
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"

    @property
    def is_terminal(self) -> bool:
        return self in (JobState.DONE, JobState.FAILED,
                        JobState.CANCELLED, JobState.SUPERSEDED)


@dataclass
class JobRecord:
    """
    What the status bar and the Jobs dock render, and the only thing they read.

    Mutable on purpose, and mutated only on the GUI thread by the QtJobRunner:
    the views hold the same instance and re-read it when told to, rather than
    each keeping its own copy of a number that then has to be kept in step.

    Times are floats from a monotonic clock, stamped by the QtJobRunner (this
    module deliberately imports no clock -- it describes work, it does not
    measure it). They are None until the job starts and finishes respectively.
    """
    job_id: int
    label: str
    total: int
    lane: str = "batch"
    slot_key: Optional[str] = None
    quiet: bool = False
    state: JobState = JobState.QUEUED
    done: int = 0
    # Progress *within* the step currently in flight, for a job whose steps are
    # themselves long (a single Data Pool folder of hundred-megabyte files).
    # Both zero when the running step does not report sub-progress; reset to
    # zero by the QtJobRunner as each step finishes.
    sub_done: int = 0
    sub_total: int = 0
    step_label: str = ""
    errors: list = field(default_factory=list)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    @property
    def is_running(self) -> bool:
        return self.state in (JobState.QUEUED, JobState.RUNNING)

    @property
    def duration(self) -> Optional[float]:
        if self.started_at is None or self.finished_at is None:
            return None
        return self.finished_at - self.started_at

    @property
    def percent(self) -> int:
        """0..100, and 0 rather than a ZeroDivisionError for an empty job."""
        if self.total <= 0:
            return 0
        fraction = self.done / self.total
        if self.sub_total > 0 and self.done < self.total:
            fraction += (self.sub_done / self.sub_total) / self.total
        return int(100 * fraction)

    @property
    def progress_text(self) -> str:
        """`done/total`, the one spelling the Jobs dock and the status strip show."""
        return f"{self.done}/{self.total}"
