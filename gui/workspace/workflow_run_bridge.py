# =====================================================================
# FILE: gui/workspace/workflow_run_bridge.py
# =====================================================================
"""
The window's handle on a batch run (ARCHITECTURE_DECISIONS §1.6, §1.21).

The run itself -- validation, resolving the selection, the drafts, the job and
everything it has to say -- is `orchestration/batch` and needs no window. What
is left here is the part that only a window has: the `app_context` to read the
session, the schema and the compression setting from, the log to write the
returned messages to, and the `run_finished` signal the rest of the GUI is
already connected to (`gui/main_window.py`, `gui/handlers/batch_run.py`).

`run_finished` used to be a Qt signal; both of its consumers
(`gui/main_window.py`, `gui/handlers/batch_run.py`) are covered by tests now,
so it is a plain callback list instead (ADR §1.73).

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Callable, List, Mapping, Optional

from core.measurement_selection import MeasurementSelection
from core.workflow_graph import Workflow
from orchestration.batch import (
    BatchOutcome, plan_batch, run_batch, supersede_running_batch,
)


class _FinishedCallback:
    """Stands in for the removed `run_finished` Qt signal (ADR §1.73).

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
    """One job with one step per source file (ADR §1.13, §1.6 phases 5 / 7B)."""

    def __init__(self, app_context, job_manager):
        self.app_context = app_context
        self.job_manager = job_manager
        # (label, was_anything_written)
        self.run_finished = _FinishedCallback()

    def start(self, workflow: Workflow, selection: MeasurementSelection,
              label: str, overwrite_by_node: Optional[Mapping[str, str]] = None,
              what: str = "Run workflow") -> None:
        """
        Plan the run, log what the plan has to say, and -- if it can happen at
        all -- hand it to the job queue.

        `overwrite_by_node` and `what` are `plan_batch`'s; see it for what they
        decide.
        """
        context = self.app_context
        session = context.project_session

        # Before the plan, not after it: pressing Run ends the live batch even
        # when this run turns out to be refused (that is what it always did).
        supersede_running_batch(self.job_manager)

        plan = plan_batch(
            workflow, selection,
            sources=session.project.sources,
            schema=context.pool.schema().master,
            project_path=session.path,
            data_roots=session.project.data_roots,
            label=label, what=what, overwrite_by_node=overwrite_by_node,
        )
        for message in plan.messages:
            context.log(message)
        if not plan.runnable:
            self.run_finished.emit(label, False)
            return

        run_batch(
            plan, workflow, session, self.job_manager,
            compression=getattr(context, "result_cache_compression", None),
            on_message=context.log, on_finished=self._on_finished,
        )

    def _on_finished(self, outcome: BatchOutcome) -> None:
        for message in outcome.messages:
            self.app_context.log(message)
        self.run_finished.emit(outcome.label, outcome.written)
