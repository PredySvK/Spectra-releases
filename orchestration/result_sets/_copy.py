# =====================================================================
# FILE: orchestration/result_sets/_copy.py
# =====================================================================
"""
Save As into another folder: copy the result sets on a background job, then
commit the save -- all or nothing.

The order is the point. The copy can be gigabytes, so it runs first and off
the GUI thread; only once every copy exists is the project file written and
the session switched. A cancel, a failed copy or a failed save removes what
was copied and leaves the session on the project it started from.

All internal documentation strings and variable labels are standardly written
in English.
"""

from dataclasses import dataclass
from typing import Callable, List

from core.jobs import JobRecord, JobState, job_step
from io_modules.result_cache import cache_folders
from orchestration.jobs import JobRunner
from session.project import ProjectSession
from session.result_sets import ResultSetCopyPlan


@dataclass(frozen=True)
class ResultSetCopyOutcome:
    """How a Save As with a result-set copy ended. `error` is empty unless it failed."""
    saved: bool
    cancelled: bool = False
    error: str = ""


def run_result_set_copy(job_runner: JobRunner, session: ProjectSession,
                        plan: ResultSetCopyPlan, *,
                        on_done: Callable[[ResultSetCopyOutcome], None]) -> int:
    """
    Copies `plan.copies` on a background job, then saves the session to
    `plan.project_path`; returns the job id (for a Cancel button).

    `on_done` runs on the thread that called this, after the session has been
    saved -- or, on cancel or failure, after the copies have been removed
    again and with the session untouched. It may run before this returns
    (JobRunner contract).
    """
    created: List[str] = []
    copied_all = []

    def copied(payload, _index):
        created.extend(payload)
        copied_all.append(True)

    def finished(record: JobRecord):
        if record.state is JobState.DONE and not record.errors and copied_all:
            try:
                session.save_as(plan.project_path, result_set_copy=plan)
            except (OSError, ValueError) as error:
                cache_folders.remove_result_sets(created)
                on_done(ResultSetCopyOutcome(saved=False, error=str(error)))
                return
            on_done(ResultSetCopyOutcome(saved=True))
            return
        # A copy that failed or was cancelled mid-way has already removed its
        # own partial output; this catches a cancel that landed just after the
        # copy finished.
        cache_folders.remove_result_sets(created)
        on_done(ResultSetCopyOutcome(
            saved=False,
            cancelled=record.state in (JobState.CANCELLED, JobState.SUPERSEDED),
            error="; ".join(str(error) for error in record.errors),
        ))

    return job_runner.submit(
        "Save As: copy results",
        [job_step("Copying results", cache_folders.copy_result_sets, list(plan.copies))],
        max_parallel=1,
        cancel_token_keyword="cancel_token",
        progress_keyword="progress_fn",
        on_step=copied,
        on_done=finished,
    )
