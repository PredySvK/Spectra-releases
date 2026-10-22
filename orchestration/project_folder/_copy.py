# =====================================================================
# FILE: orchestration/project_folder/_copy.py
# =====================================================================
"""
Save As into another folder: copy the Project folder on a background job, then
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
from io_modules.result_cache import copy_result_sets, remove_result_sets
from orchestration.jobs import JobRunner
from session.project import ProjectSession
from session.project_folder import ProjectFolderCopy


@dataclass(frozen=True)
class ProjectFolderCopyOutcome:
    """How a Save As with a Project folder copy ended. `error` is empty unless it failed."""
    saved: bool
    cancelled: bool = False
    error: str = ""


def run_project_folder_copy(job_runner: JobRunner, session: ProjectSession,
                        plan: ProjectFolderCopy, *,
                        on_done: Callable[[ProjectFolderCopyOutcome], None]) -> int:
    """
    Copies `plan.copies` and then the workbooks on a background job, then
    saves the session to `plan.project_path`; returns the job id (for a
    Cancel button).

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
                session.save_as(plan.project_path, folder_copy=plan)
            except (OSError, ValueError) as error:
                remove_result_sets(created)
                on_done(ProjectFolderCopyOutcome(saved=False, error=str(error)))
                return
            on_done(ProjectFolderCopyOutcome(saved=True))
            return
        # A copy that failed or was cancelled mid-way has already removed its
        # own partial output; this catches a cancel that landed just after the
        # copy finished.
        remove_result_sets(created)
        on_done(ProjectFolderCopyOutcome(
            saved=False,
            cancelled=record.state in (JobState.CANCELLED, JobState.SUPERSEDED),
            error="; ".join(str(error) for error in record.errors),
        ))

    return job_runner.submit(
        "Save As: copy project folder",
        [job_step("Copying the project folder", copy_result_sets,
                  list(plan.copies) + list(plan.workbook_copies))],
        max_parallel=1,
        cancel_token_keyword="cancel_token",
        progress_keyword="progress_fn",
        on_step=copied,
        on_done=finished,
    )
