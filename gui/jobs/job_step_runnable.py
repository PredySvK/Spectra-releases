# =====================================================================
# FILE: gui/jobs/job_step_runnable.py
# =====================================================================
"""
The QRunnable that carries one step of one job across the thread boundary.

Kept separate from qt_job_runner.py: this is the only place that runs on a
worker thread, and having it in its own file makes that boundary something
you can see rather than something you have to remember.

Besides the function and its result it carries the two things a queue needs
that a single request does not: a step index, so a result can be placed in a
job of many, and a start signal, so progress is reported when work begins
rather than only when it ends.

All internal documentation strings and variable labels are standardly written
in English.
"""

from PySide6.QtCore import QObject, QRunnable, Signal

from orchestration.jobs import StepOutcomeKind, run_job_step


class JobStepSignals(QObject):
    """
    Emitted from the worker thread; every connection lands queued on the GUI
    thread because the QtJobRunner that receives them lives there.
    """
    started = Signal(int, int)              # job_id, step_index
    finished = Signal(int, int, object)     # job_id, step_index, payload
    failed = Signal(int, int, str)          # job_id, step_index, message
    cancelled = Signal(int, int)            # job_id, step_index
    progress = Signal(int, int, int, int)   # job_id, step_index, done, total


class JobStepRunner(QRunnable):
    """
    Runs one step's function and reports back exactly once.

    The cancel token is checked here too, immediately before the call: a step
    can sit in the pool's queue for a long time behind other work, and running
    it after the user pressed Cancel would be pure waste even though its
    result would be discarded on arrival.
    """

    def __init__(self, job_id: int, step_index: int, step_label: str, fn,
                 args, kwargs, cancel_token, token_keyword=None,
                 progress_keyword=None):
        super().__init__()
        self.job_id = job_id
        self.step_index = step_index
        self.step_label = step_label
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.cancel_token = cancel_token
        self.token_keyword = token_keyword
        self.progress_keyword = progress_keyword
        self.signals = JobStepSignals()

    def run(self):
        outcome = run_job_step(
            self.step_label, self.fn, self.args, self.kwargs, self.cancel_token,
            token_keyword=self.token_keyword,
            progress_keyword=self.progress_keyword,
            # Fired from the worker thread; the connection lands queued on the
            # GUI thread like every other signal here.
            report_progress=lambda done, total: self.signals.progress.emit(
                self.job_id, self.step_index, done, total
            ),
            on_start=lambda: self.signals.started.emit(
                self.job_id, self.step_index),
        )

        if outcome.kind is StepOutcomeKind.CANCELLED:
            self.signals.cancelled.emit(self.job_id, self.step_index)
        elif outcome.kind is StepOutcomeKind.FAILED:
            self.signals.failed.emit(self.job_id, self.step_index,
                                     outcome.message)
        else:
            try:
                self.signals.finished.emit(self.job_id, self.step_index,
                                           outcome.payload)
            except RuntimeError as error:
                # If the window or application was torn down while this worker
                # step was finishing, emitting to a deleted Qt object raises
                # RuntimeError: Signal source has been deleted (#414).
                if "deleted" in str(error).lower():
                    pass
                else:
                    raise
