"""The first save of an Untitled project: its scan caches move in on a background job."""

from typing import Callable, Sequence

from core.jobs import job_step
from core.project_model import DataRoot
from io_modules.project_store import adopt_untitled_scan_caches
from orchestration.jobs import JobRunner


def run_untitled_scan_cache_carry(job_runner: JobRunner, project_path: str,
                                  data_roots: Sequence[DataRoot], *,
                                  on_warning: Callable[[str], None]) -> int:
    """
    Moves the scan caches built while the project was Untitled into its own
    `cache/scan/`, off the GUI thread; returns the job id.

    Never part of the save: a scan cache is rebuilt by the next scan, so one
    that cannot be moved costs time, not data -- `on_warning` gets one line
    for the log, on the thread that called this.
    """
    def carry() -> str:
        try:
            adopt_untitled_scan_caches(project_path, list(data_roots))
        except OSError as error:
            return f"WARNING: {error}"
        return ""

    def reported(warning: str, _index: int) -> None:
        if warning:
            on_warning(warning)

    return job_runner.submit("Carry scan caches into the project folder",
                             [job_step("Carry scan caches", carry)],
                             lane="interactive", quiet=True, on_step=reported)
