"""The one order of a Save As: settle, read, plan, ask, copy, save."""

from typing import Callable, Optional, Protocol

from core.jobs import JobRecord, JobState, job_step
from io_modules.project_folder import ProjectFolderListing, read_project_folder_listing
from io_modules.result_cache import copy_result_sets, remove_result_sets
from orchestration.jobs import JobRunner
from session.project import ProjectSession
from session.project_folder import ProjectFolderCopy, ProjectFolderListingRequest

from ._copy import ProjectFolderCopyOutcome, run_project_folder_copy

_CANCELLED = "PROJECT: Save As cancelled; the project was not saved."


class SaveAsSteps(Protocol):
    """What a Save As needs from the window; the GUI handler implements it."""

    def finish_tab_cache_writes(self) -> None:
        """Lets Tab cache writes still running land, so the copy sees them."""

    def show_listing_progress(self, job_id: int) -> None:
        """Modal progress while the folders are read; its Cancel cancels `job_id`."""

    def close_listing_progress(self) -> None: ...

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
    saved by the time this returns; a Save As still reading or copying
    returns False and ends through the steps.

    All or nothing: a refused folder, a cancelled question, a failed or
    cancelled read or copy leave the session on the project it started from
    and no project file in the destination. Into another folder, what lies
    in the folders is read on a background job first -- sizing the result
    sets grows with the project (§1.253) -- and the large copies (result
    sets, scan caches, Tab cache) run on another; with only the workbooks to
    copy they are copied on the calling thread -- two small files (§1.137).
    Whatever fails before the project file is written counts, not just a disk
    error; whatever fails after it is a warning in the log (§1.251).
    """
    steps.finish_tab_cache_writes()
    try:
        request = session.build_project_folder_listing_request(project_path)
        if not request.moves_folder:
            copy = session.build_project_folder_copy(request)
            _copy_workbooks_and_save(session, copy)
    except Exception as error:      # noqa: BLE001 -- any failure before the write (§1.251)
        steps.report_save_failure(error)
        return False

    if not request.moves_folder:
        _report_saved(steps, copy)
        return True

    saved = []

    def listed(listing: Optional[ProjectFolderListing], record: JobRecord) -> None:
        steps.close_listing_progress()
        if listing is None:
            if record.state in (JobState.CANCELLED, JobState.SUPERSEDED):
                steps.log(_CANCELLED)
            else:
                steps.report_save_failure(
                    "; ".join(str(error) for error in record.errors)
                    or "The project folder could not be read.")
            saved.append(False)
            return
        saved.append(_save_as_from_listing(steps, session, job_runner, request, listing))

    job_id = _run_project_folder_listing(job_runner, request, on_done=listed)
    if not saved:
        steps.show_listing_progress(job_id)
    return bool(saved and saved[0])


def _run_project_folder_listing(
        job_runner: JobRunner, request: ProjectFolderListingRequest, *,
        on_done: Callable[[Optional[ProjectFolderListing], JobRecord], None]) -> int:
    """Reads the `ProjectFolderListing` on a background job; `on_done` gets None unless it was read."""
    listings = []

    def finished(record: JobRecord) -> None:
        listing = listings[0] if record.state is JobState.DONE and listings else None
        on_done(listing, record)

    return job_runner.submit(
        "Save As: read project folder",
        [job_step("Reading the project folder", read_project_folder_listing,
                  request.source_path, request.project_path, request.result_set_files)],
        lane="interactive",
        max_parallel=1,
        cancel_token_keyword="cancel_token",
        on_step=lambda listing, _index: listings.append(listing),
        on_done=finished,
    )


def _save_as_from_listing(steps: SaveAsSteps, session: ProjectSession, job_runner: JobRunner,
                          request: ProjectFolderListingRequest,
                          listing: ProjectFolderListing) -> bool:
    """Plan, ask, copy, save -- once the folders are read. True when saved by the time it returns."""
    try:
        copy = session.build_project_folder_copy(request, listing)
        if copy.relabels:
            keep = steps.ask_keep_result_sets(copy)
            if keep is None:
                return False
            if not keep:
                copy = session.build_project_folder_copy(request, listing, keep_result_sets=False)
        if not copy.copies:
            _copy_workbooks_and_save(session, copy)
    except Exception as error:      # noqa: BLE001 -- any failure before the write (§1.251)
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
