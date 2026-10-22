"""The one order of a Save As: settle, plan, ask, copy, save."""

from typing import Optional, Protocol

from io_modules.result_cache import copy_result_sets, remove_result_sets
from orchestration.jobs import JobRunner
from session.project import ProjectSession
from session.project_folder import ProjectFolderCopy

from ._copy import ProjectFolderCopyOutcome, run_project_folder_copy

_CANCELLED = "PROJECT: Save As cancelled; the project was not saved."


class SaveAsSteps(Protocol):
    """What a Save As needs from the window; the GUI handler implements it."""

    def finish_tab_cache_writes(self) -> None:
        """Lets Tab cache writes still running land, so the copy sees them."""

    def ask_keep_result_sets(self, copy: ProjectFolderCopy) -> Optional[bool]:
        """True to copy the result sets, False to leave them out, None to cancel."""

    def show_copy_progress(self, job_id: int) -> None:
        """Modal progress for a copy still running; its Cancel cancels `job_id`."""

    def close_copy_progress(self) -> None: ...

    def report_save_failure(self, error) -> None: ...

    def log(self, message: str) -> None: ...


def run_save_as(steps: SaveAsSteps, session: ProjectSession, job_runner: JobRunner,
                project_path: str) -> bool:
    """
    Saves the open project under `project_path`, taking its Project folder
    along when that is another folder. Returns True when the project was
    saved by the time this returns; a copy still running returns False and
    ends through the steps.

    All or nothing: a refused folder, a cancelled question, a failed or
    cancelled copy leave the session on the project it started from and no
    project file in the destination. Large copies (result sets, scan caches,
    Tab cache) run on a background job; with only the workbooks to copy they
    are copied here, on the calling thread -- two small files (§1.137).
    """
    steps.finish_tab_cache_writes()
    try:
        copy = session.build_project_folder_copy(project_path)
        if copy.relabels:
            keep = steps.ask_keep_result_sets(copy)
            if keep is None:
                return False
            if not keep:
                copy = session.build_project_folder_copy(project_path, keep_result_sets=False)
        if not copy.copies:
            _copy_workbooks_and_save(session, copy)
    except (OSError, ValueError) as error:
        steps.report_save_failure(error)
        return False

    if not copy.copies:
        _report_saved(steps, copy)
        return True

    outcome = []

    def done(result: ProjectFolderCopyOutcome):
        outcome.append(result)
        steps.close_copy_progress()
        if result.saved:
            _report_saved(steps, copy)
        elif result.cancelled:
            steps.log(_CANCELLED)
        else:
            steps.report_save_failure(result.error or "The results could not be copied.")

    job_id = run_project_folder_copy(job_runner, session, copy, on_done=done)
    if not outcome:
        steps.show_copy_progress(job_id)
    return bool(outcome and outcome[0].saved)


def _copy_workbooks_and_save(session: ProjectSession, copy: ProjectFolderCopy) -> None:
    created = copy_result_sets(list(copy.workbook_copies))
    try:
        session.save_as(copy.project_path, folder_copy=copy)
    except Exception:
        remove_result_sets(created)
        raise


def _report_saved(steps: SaveAsSteps, copy: ProjectFolderCopy) -> None:
    for path in copy.kept_workbooks:
        steps.log(f"WARNING: {path} was already in the new folder and was kept; "
                  "the project's own copy was not taken along.")
    steps.log(f"PROJECT: Saved {copy.project_path}")
