"""The background existence check behind both recent lists."""

from __future__ import annotations

from typing import Callable, Iterable, TYPE_CHECKING

from core.jobs import job_step
from io_modules.recent_projects import read_project_exists

if TYPE_CHECKING:
    from orchestration.jobs import JobRunner


def run_recent_project_check(job_runner: JobRunner, paths: Iterable[str], *, slot_key: str,
                             on_checked: Callable[[str, bool], None]) -> None:
    """
    Checks each path off the GUI thread; `on_checked(path, exists)` runs per path.

    `slot_key` belongs to the caller: a newer check of the same list supersedes
    the one still running, while the two lists never cancel each other.
    """
    steps = [job_step(f"Check recent project {path}", read_project_exists, path) for path in paths]
    if not steps:
        return
    job_runner.submit(
        "Check recent projects exist",
        steps=steps,
        lane="interactive",
        slot_key=slot_key,
        quiet=True,
        on_step=lambda payload, _index: on_checked(*payload),
    )
