# =====================================================================
# FILE: orchestration/jobs/_job_runner.py
# =====================================================================
"""
The port an orchestration use case submits background work through, and the
one implementation that needs no threads.

`JobRunner` is deliberately narrower than `QtJobRunner`: it is the part of the
queue an orchestration use case is allowed to reach for, not the whole queue.
`SynchronousJobRunner` runs the same submissions on the calling thread, which
is what lets a use case be tested -- and later driven from a CLI -- without a
QApplication.

All internal documentation strings and variable labels are standardly written
in English.
"""

import traceback
from typing import Callable, List, Optional, Protocol, runtime_checkable

from core.jobs import JobCancelled, JobRecord, JobState
from orchestration.jobs._job_lifecycle import JobLifecycle


@runtime_checkable
class JobRunner(Protocol):
    """
    "Run these steps in the background and tell me about each one."

    Structural on purpose (a Protocol, not an ABC): `QtJobRunner` is a QObject,
    and a class inheriting both a Shiboken metaclass and ABCMeta cannot be
    built (§1.70). QtJobRunner satisfies the protocol by keeping its signature.

    The contract both implementations honour:

    1. `on_step(payload, index)`, `on_error(message, index)` and
       `on_done(record)` run on the thread that called `submit`, and never
       concurrently. For QtJobRunner that is the GUI thread; for the
       synchronous runner it is whoever called.
    2. **`on_done` may arrive before `submit` returns** -- always for the
       synchronous runner, and for QtJobRunner whenever `steps` is empty.
       So a use case has to have the whole run state (its state dict, the
       identity of the run) ready *before* it calls `submit`, and `submit`
       has to be the last statement that touches that state.
    3. With `max_parallel > 1` steps may report out of order. Use `index`,
       never arrival order, to decide which step a payload belongs to.
    4. An exception raised *by* a result, error or completion callback does
       not interrupt the job. It is appended to `record.errors` and the queue drains. (Raising instead was
       rejected: a use case is written against both implementations, and a
       test on the synchronous runner would then be exercising behaviour the
       application does not have.)
    5. A step raising `JobCancelled` counts as cancelled, not as a failure --
       it adds nothing to `record.errors`. Terminal states are `DONE`,
       `FAILED`, `CANCELLED` and `SUPERSEDED`.
    6. Step bodies receive data only (§1.54): no Qt objects, no widgets, no
       AppContext. They may take a `CancelToken` and a `progress_fn` under the
       keyword names given to `submit`.

    `cancel(job_id)` is not here. Orchestration only ever cancels through a
    slot; a human pressing Cancel does it from gui/, straight on the
    QtJobRunner, using the id `submit` returned.
    """

    def submit(self, label: str, steps: List[tuple], *,
               lane: str = "batch", slot_key: Optional[str] = None,
               max_parallel: Optional[int] = None, quiet: bool = False,
               cancel_token_keyword: Optional[str] = None,
               progress_keyword: Optional[str] = None,
               step_sizes: Optional[List[int]] = None,
               on_step: Optional[Callable[[object, int], None]] = None,
               on_error: Optional[Callable[[str, int], None]] = None,
               on_done: Optional[Callable[[JobRecord], None]] = None) -> int:
        """
        Queues `steps` -- (step_label, fn, args, kwargs) 4-tuples, built with
        `job_step()` -- under one visible job and returns its id.

        `lane`, `quiet` and `max_parallel` are hints about the work, not about
        the GUI: an ingest wants one folder at a time and no status-bar noise,
        a batch wants the batch lane. An implementation without threads may
        ignore all three without changing the result.

        `step_sizes` makes the job count units instead of steps: step `i` is
        worth `step_sizes[i]` (its channels), and its `progress_fn(done, total)`
        reports how many of them are done. `record.total` is then the sum.
        """
        ...

    def cancel_slot(self, slot_key: str) -> None:
        """Stops the live job holding `slot_key`; its state becomes SUPERSEDED."""
        ...


class SynchronousJobRunner:
    """
    Runs every step in order on the calling thread, with no Qt and no threads.

    It fills `JobRecord` the way QtJobRunner does -- `done`, `sub_done` /
    `sub_total` from `progress_fn`, `errors`, `state` -- but leaves
    `started_at` and `finished_at` at None: a test that ran through here would
    otherwise depend on a clock, and nothing it is used for measures duration.

    Beyond the port it offers `cancel(job_id)`, so a test can simulate the user
    pressing Cancel halfway through a batch by calling it from `on_step`, and
    `callback_errors`, so it can assert that none of its callbacks blew up --
    under the port's contract those are only swallowed into `record.errors`,
    among the failures of the work itself.
    """

    def __init__(self):
        self._next_id = 0
        self._records = {}     # job_id -> JobRecord (live and finished)
        self._live = {}        # job_id -> JobLifecycle
        self.callback_errors: List[str] = []

    # ---- the port -----------------------------------------------------

    def submit(self, label: str, steps: List[tuple], *,
               lane: str = "batch", slot_key: Optional[str] = None,
               max_parallel: Optional[int] = None, quiet: bool = False,
               cancel_token_keyword: Optional[str] = None,
               progress_keyword: Optional[str] = None,
               step_sizes: Optional[List[int]] = None,
               on_step=None, on_error=None, on_done=None) -> int:
        if slot_key is not None:
            self.cancel_slot(slot_key)

        self._next_id += 1
        job_id = self._next_id
        record = JobRecord(job_id=job_id, label=label, total=len(steps),
                           lane=lane, slot_key=slot_key, quiet=quiet)
        job = JobLifecycle(record, on_step=on_step, on_error=on_error,
                           on_done=on_done, callback_errors=self.callback_errors,
                           step_sizes=step_sizes)
        self._records[job_id] = record
        self._live[job_id] = job

        # An empty job is finished the moment it is submitted, like QtJobRunner:
        # "nothing matched the selection" is a real outcome and the caller gets
        # its on_done rather than a job sitting at 0/0.
        if not steps:
            self._finish(job, JobState.DONE)
            return job_id

        record.state = JobState.RUNNING
        for index, step in enumerate(steps):
            if job.cancel_token.is_cancelled:
                break
            self._run_step(job, index, step, cancel_token_keyword,
                           progress_keyword)

        state = (job.stopped_state if job.cancel_token.is_cancelled
                 else JobState.DONE)
        self._finish(job, state)
        return job_id

    def cancel_slot(self, slot_key: str) -> None:
        for job_id, job in list(self._live.items()):
            if job.record.slot_key == slot_key:
                job.cancel(superseded=True)
                self.cancel(job_id)

    # ---- beyond the port ----------------------------------------------

    def cancel(self, job_id: int) -> None:
        """
        Abandons a job: no further step is started. Called re-entrantly from a
        callback -- the only moment a job of this runner is live -- it ends the
        job there and then, exactly as QtJobRunner does when nothing is in
        flight, and `submit` then leaves the loop with nothing left to do.
        """
        job = self._live.get(job_id)
        if job is None:
            return
        job.cancel()
        if job.in_flight == 0:
            self._finish(job, job.stopped_state)

    def record(self, job_id: int) -> Optional[JobRecord]:
        return self._records.get(job_id)

    # ---- internals ----------------------------------------------------

    def _run_step(self, job: JobLifecycle, index: int, step: tuple,
                  cancel_token_keyword, progress_keyword) -> None:
        step_label, fn, args, kwargs = step
        job.start_step(step_label)

        call_kwargs = dict(kwargs or {})
        if cancel_token_keyword:
            call_kwargs[cancel_token_keyword] = job.cancel_token
        if progress_keyword:
            call_kwargs[progress_keyword] = (
                lambda done, total: job.report_progress(index, done, total)
            )

        job.in_flight = 1
        failure = None
        cancelled = False
        payload = None
        try:
            payload = fn(*args, **call_kwargs)
        except JobCancelled:
            # The step noticed the token and unwound. Not a failure.
            cancelled = True
        except Exception as error:
            failure = (f"{step_label or 'step'}: {error}\n"
                       f"{traceback.format_exc()}")

        job.release_step(index)
        if cancelled:
            return
        if failure is not None:
            job.deliver_error(failure, index)
        else:
            job.deliver_result(payload, index)

    def _finish(self, job: JobLifecycle, state: JobState) -> None:
        if not job.finish(state):
            return
        self._live.pop(job.record.job_id, None)
        job.notify_done()
