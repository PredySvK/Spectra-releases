# =====================================================================
# FILE: gui/jobs/qt_job_runner.py
# =====================================================================
"""
One visible queue for everything that runs in the background (ADR 1.13).

Before this, six controllers each hand-rolled the same four things around
AsynchronousComputeWorker: a thread pool reference, a dict holding workers
alive until they report back, a generation counter answering "is this result
still the one I asked for", and their own error logging. None of them could
be cancelled and only one of them showed progress, because doing either
meant writing it a seventh time.

Three ideas do the work here:

* A job is a queue of steps, not one call. "Calculate & Save Data" over forty
  measurements is one job with forty steps, so 12/40 is a number that exists,
  and Cancel means "stop dispatching the remaining twenty-eight" rather than
  "hope the one call notices".

* max_parallel belongs to the job, not to the manager. Order cuts over forty
  files want every core; a Data Pool ingest wants one folder at a time so the
  tree fills in progressively and the disk is not thrashed. Both are correct,
  and neither is a property of "background work" in general.

* slot_key replaces the generation counters. Submitting a job with a slot_key
  cancels the live job holding that slot, so the "am I still current?"
  arithmetic happens once, here, instead of in every caller -- per-dock reads
  included, whose slot is the dock and the task's purpose (ADR §1.84).

Ownership: one QtJobRunner per MainWindowFrame, passed to controllers by
constructor. Not on AppContext, which the view-only second window shares --
a job queue spanning both windows would let the read-only one enqueue work
that writes.

Callbacks (on_step / on_error / on_done) are invoked on the GUI thread, from
slots connected to the runners' signals, and may touch widgets and log.

All internal documentation strings and variable labels are standardly written
in English.
"""

import time
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, QThread, QThreadPool, Signal

from core.jobs import JobRecord, JobState
from orchestration.jobs import JobLifecycle
from gui.jobs.job_step_runnable import JobStepRunner

# How many terminal jobs the Jobs dock can still show. Bounded because a
# session that watches a folder can finish hundreds of quiet ingests, and
# their records would otherwise accumulate for the lifetime of the window.
HISTORY_LIMIT = 100


class _Job(JobLifecycle):
    """
    The manager's private bookkeeping for one job: everything the views must
    not see. The part they do see is `record`.

    `runners` is the keep-alive set. Dropping the last Python reference to a
    running QRunnable takes its `signals` QObject with it and the result never
    arrives -- the trap every controller in this codebase had its own comment
    about. Now there is one.
    """
    def __init__(self, record: JobRecord, steps: List[tuple], max_parallel: int,
                 token_keyword, progress_keyword, on_step, on_error, on_done,
                 on_diagnostic, step_sizes=None):
        super().__init__(record, on_step=on_step, on_error=on_error,
                         on_done=on_done, on_diagnostic=on_diagnostic,
                         step_sizes=step_sizes)
        self.steps = steps
        self.next_index = 0
        self.max_parallel = max_parallel
        self.token_keyword = token_keyword
        self.progress_keyword = progress_keyword
        self.runners = set()


class QtJobRunner(QObject):
    """
    Owns the pools, the live jobs and the finished-job history.

    Two lanes rather than QThreadPool.globalInstance(): a forty-file batch
    submitted into the same pool the docks read through will occupy every
    thread in it, and the next channel the user clicks then waits behind
    thirty-nine order-cut computations. The window is not frozen, but it
    behaves exactly as if it were, which for the user is the same complaint.
    """

    job_added = Signal(int)      # job_id
    job_changed = Signal(int)    # job_id -- progress, step label or state moved
    job_finished = Signal(int)   # job_id -- state is terminal

    def __init__(self, app_context=None, parent=None):
        super().__init__(parent)
        self.app_context = app_context

        ideal = max(2, QThread.idealThreadCount())
        self._pools = {
            "interactive": self._make_pool(max(2, ideal // 2)),
            "batch": self._make_pool(max(1, ideal - 1)),
        }

        self._jobs = {}          # job_id -> _Job (live only)
        self._records = {}       # job_id -> JobRecord (live and historical)
        self._order: List[int] = []
        self._next_id = 0

    @staticmethod
    def _make_pool(max_threads: int) -> QThreadPool:
        pool = QThreadPool()
        pool.setMaxThreadCount(max_threads)
        return pool

    # ---- submission ---------------------------------------------------

    def submit(self, label: str, steps: Optional[List[tuple]] = None, *,
               fn: Optional[Callable] = None, args=(), kwargs=None,
               lane: str = "batch", slot_key: Optional[str] = None,
               max_parallel: Optional[int] = None, quiet: bool = False,
               cancel_token_keyword: Optional[str] = None,
               progress_keyword: Optional[str] = None,
               step_sizes: Optional[List[int]] = None,
               on_step=None, on_error=None, on_done=None) -> int:
        """
        Queues a job and returns its id.

        `steps` is a list of (step_label, fn, args, kwargs) -- build them with
        job_step(). A single-call job can pass `fn`/`args`/`kwargs` instead.

        `max_parallel` defaults to the lane's width; pass 1 for work whose
        order, or whose one-at-a-time progress, is the point.

        `cancel_token_keyword` names the keyword each step's function receives
        the CancelToken under, for work that can stop mid-step. Left None, the
        token still stops further steps from being dispatched.

        `progress_keyword` names the keyword each step's function receives a
        `progress_fn(done, total)` callback under, for a step long enough that
        the user needs to see it move between its start and its end.

        `step_sizes` counts the job in units (channels) rather than steps --
        see JobRunner.submit.

        `slot_key` makes this job supersede the live job holding that key.
        """
        if steps is None:
            steps = [(label, fn, args, kwargs or {})]

        if slot_key is not None:
            self.cancel_slot(slot_key)

        self._next_id += 1
        job_id = self._next_id
        record = JobRecord(job_id=job_id, label=label, total=len(steps), lane=lane,
                           slot_key=slot_key, quiet=quiet)
        pool = self._pools.get(lane) or self._pools["batch"]
        width = max_parallel if max_parallel is not None else pool.maxThreadCount()

        job = _Job(record, steps, max(1, width), cancel_token_keyword,
                   progress_keyword, on_step, on_error, on_done,
                   lambda message: self._log_error(record, message),
                   step_sizes=step_sizes)
        self._jobs[job_id] = job
        self._records[job_id] = record
        self._order.append(job_id)
        self._trim_history()

        record.started_at = time.monotonic()
        self.job_added.emit(job_id)

        # An empty job is finished the moment it is submitted -- "nothing
        # matched the selection" is a real outcome, and the caller should get
        # its on_done rather than a job sitting at 0/0 forever.
        if not steps:
            self._finish(job, JobState.DONE)
            return job_id

        record.state = JobState.RUNNING
        self._dispatch(job)
        return job_id

    def _dispatch(self, job: _Job) -> None:
        """Fills the job's parallel slots from its remaining steps."""
        pool = self._pools.get(job.record.lane) or self._pools["batch"]
        while (not job.cancel_token.is_cancelled
               and job.in_flight < job.max_parallel
               and job.next_index < len(job.steps)):
            index = job.next_index
            job.next_index += 1
            step_label, fn, args, kwargs = job.steps[index]

            runner = JobStepRunner(job.record.job_id, index, step_label, fn, args,
                                   kwargs or {}, job.cancel_token, job.token_keyword,
                                   job.progress_keyword)
            runner.signals.started.connect(self._on_step_started)
            runner.signals.finished.connect(self._on_step_finished)
            runner.signals.failed.connect(self._on_step_failed)
            runner.signals.cancelled.connect(self._on_step_cancelled)
            runner.signals.progress.connect(self._on_step_progress)
            job.runners.add(runner)
            job.in_flight += 1
            pool.start(runner)

    # ---- worker callbacks (GUI thread) --------------------------------

    def _on_step_started(self, job_id: int, step_index: int) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.start_step(job.steps[step_index][0])
        self.job_changed.emit(job_id)

    def _on_step_progress(self, job_id: int, step_index: int, done: int, total: int) -> None:
        job = self._jobs.get(job_id)
        if job is not None and job.report_progress(step_index, done, total):
            self.job_changed.emit(job_id)

    def _on_step_finished(self, job_id: int, step_index: int, payload) -> None:
        job = self._release(job_id, step_index)
        if job is not None:
            job.deliver_result(payload, step_index)
            self._advance(job)

    def _on_step_failed(self, job_id: int, step_index: int, message: str) -> None:
        job = self._release(job_id, step_index)
        if job is not None:
            job.deliver_error(message, step_index)
            self._advance(job)

    def _on_step_cancelled(self, job_id: int, step_index: int) -> None:
        job = self._release(job_id, step_index)
        if job is not None:
            self._advance(job)

    def _release(self, job_id: int, step_index: int) -> Optional[_Job]:
        """
        Drops the keep-alive reference and counts the step as done.

        Runs for cancelled and superseded steps too: the runner has reported
        back, so the reference has done its job either way.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return None
        for runner in list(job.runners):
            if runner.step_index == step_index:
                job.runners.discard(runner)
                break
        job.release_step(step_index)
        return job

    def _advance(self, job: _Job) -> None:
        self.job_changed.emit(job.record.job_id)
        self._dispatch(job)
        if job.in_flight == 0 and (job.cancel_token.is_cancelled
                                   or job.next_index >= len(job.steps)):
            state = (job.stopped_state if job.cancel_token.is_cancelled
                     else JobState.DONE)
            self._finish(job, state)

    def _finish(self, job: _Job, state: JobState) -> None:
        if not job.finish(state):
            return
        job.record.finished_at = time.monotonic()
        self._jobs.pop(job.record.job_id, None)
        job.notify_done()
        self.job_finished.emit(job.record.job_id)
        self.job_changed.emit(job.record.job_id)

    def _log_error(self, record: JobRecord, message: str) -> None:
        if self.app_context is not None:
            self.app_context.log(f"ERROR: {record.label} -- {message}")

    # ---- cancellation and queries -------------------------------------

    def cancel(self, job_id: int) -> None:
        """
        Abandons a job. Steps already in flight are allowed to finish (their
        results are dropped); nothing further is dispatched. A step that takes
        a CancelToken can also stop mid-way.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.cancel()
        self.job_changed.emit(job_id)
        if job.in_flight == 0:
            self._finish(job, job.stopped_state)

    def cancel_slot(self, slot_key: str) -> None:
        for job_id, job in list(self._jobs.items()):
            if job.record.slot_key == slot_key:
                job.cancel(superseded=True)
                self.cancel(job_id)

    def cancel_all(self) -> None:
        for job_id in list(self._jobs):
            self.cancel(job_id)

    def record(self, job_id: int) -> Optional[JobRecord]:
        return self._records.get(job_id)

    def running_jobs(self) -> List[JobRecord]:
        return [self._records[i] for i in self._order
                if i in self._records and self._records[i].is_running]

    def all_records(self) -> List[JobRecord]:
        """Oldest first, live and historical."""
        return [self._records[i] for i in self._order if i in self._records]

    def clear_history(self) -> None:
        """Forgets every finished job; jobs still queued or running stay."""
        self._order = [i for i in self._order if i in self._jobs]
        self._records = {i: self._records[i] for i in self._order if i in self._records}

    def _trim_history(self) -> None:
        # Drop the oldest *terminal* records past the limit, stepping over any
        # job still running rather than stopping at the first one: a long batch
        # sits at the head of _order for many minutes while the watcher finishes
        # hundreds of quiet ingests behind it, and stopping there let the
        # history grow unbounded in exactly that case (audit 02, finding S3/3.10).
        excess = len(self._order) - HISTORY_LIMIT
        if excess <= 0:
            return
        kept = []
        for job_id in self._order:
            if excess > 0 and job_id not in self._jobs:
                self._records.pop(job_id, None)
                excess -= 1
            else:
                kept.append(job_id)
        self._order = kept

    def wait_for_done(self, msecs: int = 30000) -> bool:
        """
        Blocks until every pool is idle. For tests and for shutdown only --
        never call this from a GUI path, that is the freeze this whole module
        exists to prevent.
        """
        idle = True
        for pool in self._pools.values():
            idle = pool.waitForDone(msecs) and idle
        return idle
