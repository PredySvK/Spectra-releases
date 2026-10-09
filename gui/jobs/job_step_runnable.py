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

import traceback

from PySide6.QtCore import QObject, QRunnable, Signal

from core.jobs import JobCancelled


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
        if self.cancel_token.is_cancelled:
            self.signals.cancelled.emit(self.job_id, self.step_index)
            return

        self.signals.started.emit(self.job_id, self.step_index)

        kwargs = dict(self.kwargs)
        if self.token_keyword:
            kwargs[self.token_keyword] = self.cancel_token
        if self.progress_keyword:
            # Fired from the worker thread; the connection lands queued on the
            # GUI thread like every other signal here.
            kwargs[self.progress_keyword] = lambda done, total: self.signals.progress.emit(
                self.job_id, self.step_index, done, total
            )

        try:
            payload = self.fn(*self.args, **kwargs)
        except JobCancelled:
            # The step noticed the token mid-flight and unwound. Not a failure:
            # nothing went wrong, the user asked for it to stop.
            self.signals.cancelled.emit(self.job_id, self.step_index)
        except Exception as error:
            self.signals.failed.emit(
                self.job_id, self.step_index,
                f"{self.step_label or 'step'}: {error}\n{traceback.format_exc()}",
            )
        else:
            try:
                self.signals.finished.emit(self.job_id, self.step_index, payload)
            except RuntimeError as error:
                # If the window or application was torn down while this worker
                # step was finishing, emitting to a deleted Qt object raises
                # RuntimeError: Signal source has been deleted (#414).
                if "deleted" in str(error).lower():
                    pass
                else:
                    raise
