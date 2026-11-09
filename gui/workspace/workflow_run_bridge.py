# =====================================================================
# FILE: gui/workspace/workflow_run_bridge.py
# =====================================================================
"""
The window's handle on a batch run.

The run itself -- validation, resolving the selection, the drafts, the job and
everything it has to say -- is `orchestration/batch` and needs no window. What
is left here is the part that only a window has: the `app_context` to read the
session, the schema and the compression setting from, the log to write the
returned messages to, and the `run_finished` signal the rest of the GUI is
already connected to (`gui/main_window.py`, `gui/handlers/batch_run.py`).

`run_finished` used to be a Qt signal; both of its consumers
(`gui/main_window.py`, `gui/handlers/batch_run.py`) are covered by tests now,
so it is a plain callback list instead.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Callable, List, Optional, Sequence

from orchestration.batch import (
    BatchOutcome, BatchRuns, CalculateAndSavePlan, UpcomingResultSet, WaitingBatchRun,
    WorkflowChainPlan, WorkflowChainBatch, plan_chain_batches, plan_result_set_batches,
    run_chain_batches,
)


class _FinishedCallback:
    """Stands in for the removed `run_finished` Qt signal.

    Plain callback list rather than a single slot: `gui/main_window.py` keeps
    a permanent listener for the whole app's lifetime while
    `BatchRunHandler` (gui/handlers/batch_run.py) connects and disconnects
    one listener per run to drive a single ribbon tab's status line -- both
    need to be able to listen at once.
    """

    def __init__(self):
        self._listeners: List[Callable[[str, bool], None]] = []

    def connect(self, listener: Callable[[str, bool], None]) -> None:
        self._listeners.append(listener)

    def disconnect(self, listener: Callable[[str, bool], None]) -> None:
        self._listeners.remove(listener)

    def emit(self, label: str, written: bool) -> None:
        for listener in list(self._listeners):
            listener(label, written)


class WorkflowRunBridge:
    """One job with one step per source file."""

    def __init__(self, app_context, job_runner):
        self.app_context = app_context
        self.job_runner = job_runner
        # (label, was_anything_written)
        self.run_finished = _FinishedCallback()
        self._waiting_listeners: List[Callable[[], None]] = []
        self._batch_runs = BatchRuns(job_runner, on_message=self._log, on_finished=self._on_finished,
                                     on_waiting_changed=self._on_waiting_changed)

    def build_chain_batches(self, chains: tuple[WorkflowChainPlan, ...]) -> tuple[WorkflowChainBatch, ...]:
        """Plan every chain of a Workflow run in full against the pool snapshot."""
        context = self.app_context
        session = context.project_session
        return plan_chain_batches(
            chains, sources=session.project.sources, schema=context.pool.schema().master,
            project_path=session.path, data_roots=session.project.data_roots,
        )

    def build_result_set_batches(self, plans: Sequence[CalculateAndSavePlan]) -> tuple[WorkflowChainBatch, ...]:
        """Plan every runnable result set of a Compute Result Set in full, in the same shape."""
        context = self.app_context
        session = context.project_session
        return plan_result_set_batches(
            plans, sources=session.project.sources, schema=context.pool.schema().master,
            project_path=session.path, data_roots=session.project.data_roots,
        )

    @property
    def busy(self) -> bool:
        """Whether a Batch run computes or waits: a new one has to ask Wait / Interrupt."""
        return self._batch_runs.busy

    @property
    def waiting(self) -> tuple[WaitingBatchRun, ...]:
        """The waiting Batch runs, the next to start first -- the Jobs panel's waiting rows (#966)."""
        return self._batch_runs.waiting

    @property
    def upcoming_result_sets(self) -> tuple[UpcomingResultSet, ...]:
        """The result sets the running and waiting Batch runs will write -- for the Overwrite question (#967)."""
        return self._batch_runs.upcoming_result_sets

    def cancel_waiting(self, key: int) -> bool:
        """Drop one waiting Batch run; its runs report "not started", the others keep their place."""
        return self._batch_runs.cancel_waiting(key)

    def run_when_idle(self, name: str, action: Callable[[], None]) -> None:
        """Run `action` once no Batch run computes or waits -- Wait on New / Open / Save As / close (#968)."""
        self._batch_runs.run_when_idle(name, action)

    def interrupt(self) -> None:
        """Stop the running Batch run and drop the waiting ones -- Interrupt on New / Open / Save As / close (#968)."""
        self._batch_runs.interrupt()

    def connect_waiting_changed(self, listener: Callable[[], None]) -> None:
        """`listener` hears every change of `waiting`."""
        self._waiting_listeners.append(listener)

    def start_chains(self, chains: tuple[WorkflowChainBatch, ...], *, wait: bool = False,
                     on_started: Optional[Callable[[], None]] = None,
                     on_finished: Optional[Callable[[str, bool], None]] = None) -> None:
        """
        Start a planned Batch run -- a series of runs, one after another. Every
        run reports `run_finished` once, a refused one included
        (`run_chain_batches`, §1.238).

        `wait` puts it behind the Batch runs that compute or wait; otherwise it
        interrupts them. A series with nothing runnable reports its runs and
        leaves them all alone (§1.264, §1.266). `on_started` hears the moment
        it is submitted -- now, or when its turn comes; `on_finished` hears
        `(label, written)` for each of this series' own runs only, a dropped
        one included.
        """
        context = self.app_context
        self._batch_runs.start(
            chains, context.project_session, wait=wait,
            compression=getattr(context, "result_cache_compression", None), on_started=on_started,
            on_finished=None if on_finished is None else (
                lambda outcome: on_finished(outcome.label, outcome.written)),
        )

    def _log(self, message: str) -> None:
        self.app_context.log(message)

    def _on_waiting_changed(self) -> None:
        for listener in list(self._waiting_listeners):
            listener()

    def _on_finished(self, outcome: BatchOutcome) -> None:
        for message in outcome.messages:
            self.app_context.log(message)
        self.run_finished.emit(outcome.label, outcome.written)
