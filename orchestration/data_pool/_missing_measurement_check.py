"""
Which measurements of the Data Pool are Missing measurements, found on a worker.

The pool remembers the answer (`DataPool.missing_paths`) so no redraw of the
Data Pool tree touches the disk; this module decides when the answer is worked
out again and what a run that lands late may still do. One stat
per measurement grows with the pool and with a slow drive, so it is a job on
the `JobRunner`, never a call on the caller's thread.

Started after a project's pool snapshot is restored and after every ingest
finishes (`PoolIngestUseCase`). Only the newest run writes: a superseded one or
one cancelled because the project was replaced lands with nothing to say.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from core.jobs import JobState, job_step
from io_modules.measurement_files import find_missing_files
from orchestration.jobs import JobRunner

MISSING_CHECK_SLOT_KEY = "pool_missing_check"


@dataclass(frozen=True)
class MissingCheckOutcome:
    """What a finished check found, and what the shell should log about it."""

    missing_paths: frozenset
    log_messages: Tuple[str, ...] = ()


class MissingMeasurementCheck:
    """
    Runs the existence check of the pool's measurements, one run at a time.

    `find_missing(paths) -> paths not on disk` is the I/O floor's function by
    default; tests hand in a fake disk. `on_checked` hears every run that
    wrote its result into the pool, after it did.
    """

    def __init__(self, pool, runner: JobRunner, *,
                 find_missing: Callable = find_missing_files,
                 on_checked: Optional[Callable[[MissingCheckOutcome], None]] = None):
        self._pool = pool
        self._runner = runner
        self._find_missing = find_missing
        self._on_checked = on_checked
        self._runs = 0
        self._active_run: Optional[int] = None
        # The project-open warning is owed until a run started after that open
        # finishes; a newer run (an ingest landing first) inherits the debt.
        self._warning_owed = False

    def start(self, *, after_project_open: bool = False) -> int:
        """Checks every measurement the pool holds now, on a worker."""
        self._runs += 1
        run = self._runs
        if after_project_open:
            self._warning_owed = True
        found = {"paths": None}
        paths = tuple(run_index.file_path for run_index in self._pool.loaded_runs)

        def _on_done(record) -> None:
            if run != self._active_run:
                return
            self._active_run = None
            if record.state is not JobState.DONE or found["paths"] is None:
                # A failed check owes nothing to a later, unrelated scan.
                self._warning_owed = False
                return
            self._finish(found["paths"])

        # The run exists before submit, which may finish it before it returns.
        self._active_run = run
        return self._runner.submit(
            "Checking Data Pool files",
            [job_step("measurement files", self._find_missing, paths)],
            lane="batch", slot_key=MISSING_CHECK_SLOT_KEY, max_parallel=1, quiet=True,
            on_step=lambda missing, _index: found.update(paths=missing),
            on_done=_on_done,
        )

    def cancel(self) -> None:
        """Abandons the run in flight: the project it was checking is going away."""
        self._active_run = None
        self._warning_owed = False
        self._runner.cancel_slot(MISSING_CHECK_SLOT_KEY)

    def _finish(self, missing) -> None:
        self._pool.set_missing_paths(missing)
        gone = len(self._pool.missing_paths)
        messages: Tuple[str, ...] = ()
        if self._warning_owed and gone:
            messages = (
                f"WARNING: {gone} measurement(s) are not on disk where the project "
                f"expects them. They are marked in the Data Pool; right-click one to locate it.",
            )
        self._warning_owed = False
        if self._on_checked is not None:
            self._on_checked(MissingCheckOutcome(self._pool.missing_paths, messages))
