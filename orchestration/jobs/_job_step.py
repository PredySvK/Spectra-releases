# =====================================================================
# FILE: orchestration/jobs/_job_step.py
# =====================================================================
"""
The one execution of a single job step, shared by every runner.

A step is called the same way whoever drives it: the cancel token and the
progress callback are injected under the keyword names the job was submitted
with, the function runs, and the outcome is exactly one of a payload, a
cancellation or a failure carrying its traceback. `SynchronousJobRunner` calls
this on the calling thread; the Qt `JobStepRunner` calls it on a worker thread
and turns the outcome into signals. Neither owns the classification, so a test
on the synchronous runner exercises the code the application runs.

No Qt, no threads: delivery, signals and lifecycle stay with the adapters.
"""

import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from core.jobs import CancelToken, JobCancelled


class StepOutcomeKind(Enum):
    RESULT = "result"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True)
class StepOutcome:
    """What happened to one step: a payload, a cancellation or a failure."""
    kind: StepOutcomeKind
    payload: object = None
    message: str = ""


def run_job_step(step_label: str, fn: Callable, args: tuple, kwargs: Optional[dict],
                 cancel_token: CancelToken, *,
                 token_keyword: Optional[str] = None,
                 progress_keyword: Optional[str] = None,
                 report_progress: Optional[Callable[[int, int], None]] = None,
                 on_start: Optional[Callable[[], None]] = None) -> StepOutcome:
    """
    Runs one step and classifies how it ended.

    A token already cancelled returns CANCELLED without `on_start` and without
    calling `fn` -- a step can wait in a queue long after the user pressed
    Cancel. Otherwise `on_start` fires, `fn` is called with the token and the
    progress callback injected under their keywords, and a `JobCancelled`
    raised by `fn` is CANCELLED (the user asked for it, not a failure), any
    other `Exception` is FAILED with "label: error" and the traceback.
    """
    if cancel_token.is_cancelled:
        return StepOutcome(StepOutcomeKind.CANCELLED)

    if on_start is not None:
        on_start()

    call_kwargs = dict(kwargs or {})
    if token_keyword:
        call_kwargs[token_keyword] = cancel_token
    if progress_keyword and report_progress is not None:
        call_kwargs[progress_keyword] = report_progress

    try:
        payload = fn(*args, **call_kwargs)
    except JobCancelled:
        return StepOutcome(StepOutcomeKind.CANCELLED)
    except Exception as error:
        return StepOutcome(
            StepOutcomeKind.FAILED,
            message=(f"{step_label or 'step'}: {error}\n"
                     f"{traceback.format_exc()}"))
    return StepOutcome(StepOutcomeKind.RESULT, payload=payload)
