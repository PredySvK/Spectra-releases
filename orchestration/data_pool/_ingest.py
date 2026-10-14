"""
The decision half of "Add to Data Pool": one folder per step over a JobRunner.

What this module owns is the *sequence*: which folders are read, in what
order, what happens to each one when it lands, and what the run adds up to at
the end. It never draws anything. The progress dialog, the Cancel button, the
explorer refresh, the conflict dialog and the failure popup are consequences
the shell applies to the reports this module hands it (ADR 1.13, 1.69, 1.70).

Two properties of the run are the reason it is written the way it is:

* **The identity of a run exists before `submit`.** `on_done` may arrive
  before `submit` returns -- always for `SynchronousJobRunner`, and for
  QtJobRunner whenever there are no steps (ADR 1.70). So the run's state dict,
  including the token that says which run it is, is complete before `submit`,
  and `submit` is the last statement that touches it.
* **Per-run state lives in the state dict captured by the callbacks, not on
  self.** A second Add supersedes the first through `slot_key`, but the
  superseded run's folder read is still in flight and its `on_done` lands
  afterwards; holding its state anywhere shared would let it write into the
  run that replaced it (audit 02, S3/3.1).

All internal documentation strings and variable labels are standardly written
in English.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Optional, Tuple

from core.jobs import JobState, job_step
from io_modules.pool_ingest_plan import (
    build_ingest_folder_map, derive_auto_tags, find_parent_metadata_files,
)
from io_modules.measurement_files import (
    canonical_path, discover_measurement_files, resolve_imported_result_reader, is_measurement_file,
)
from io_modules.project_store import build_sources_by_path, read_root_directories
from orchestration.data_pool._source_amplitude import (
    SourceAmplitudeAsker, plan_source_amplitude_questions, resolve_file_amplitudes,
)
from orchestration.jobs import JobRunner
from session.data_pool import IntegrateResult
from session.project import apply_setup_label

INGEST_SLOT_KEY = "pool_ingest"


@dataclass(frozen=True)
class IngestPlan:
    """
    Which folders an ingest reads, and what each of them was selected as.

    `skipped_files` are files the user picked that no reader recognises -- a
    README or the metadata Excel offered by the browser on suffix alone; the
    run only says so in the log.

    `imported_files` is what the Source amplitude question is asked about: the
    Imported-result files the run reads, by the reader that opens them. A
    folder re-scan lists only the files the project does not know yet.
    """

    directories: Tuple[str, ...] = ()
    only_files: Dict[str, Optional[set]] = field(default_factory=dict)
    auto_tag: Dict[str, str] = field(default_factory=dict)
    parent_excel: Dict[str, str] = field(default_factory=dict)
    skipped_files: Tuple[str, ...] = ()
    imported_files: Dict[str, Tuple[str, ...]] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.directories)


def plan_pool_ingest(paths, folder_files: Optional[dict] = None) -> IngestPlan:
    """
    Turns a path selection into the plan one ingest runs on.

    `folder_files` is the explicit form used by a folder re-scan, which names
    its folders and passes no paths: it re-tags nothing and inherits no parent
    sheet, so both maps come out empty.

    Walks folder trees and reads the headers of generic-suffix files, so for a
    path selection it runs on a worker (`PoolIngestUseCase.start_selection`).
    """
    folder_files = folder_files if folder_files is not None else build_ingest_folder_map(paths)
    imported: Dict[str, list] = {}
    for directory, files in folder_files.items():
        # A whole folder (None) is every file in it; a picked set is just those.
        for path in sorted(discover_measurement_files(directory) if files is None else files):
            reader = resolve_imported_result_reader(path)
            if reader is not None:
                imported.setdefault(reader, []).append(path)
    return IngestPlan(
        directories=tuple(folder_files.keys()),
        only_files=dict(folder_files),
        auto_tag=derive_auto_tags(paths),
        parent_excel=find_parent_metadata_files(paths),
        skipped_files=tuple(path for path in paths
                            if os.path.isfile(path) and not is_measurement_file(path)),
        imported_files={reader: tuple(files) for reader, files in imported.items()},
    )


def plan_pool_refresh(directories, project_path, roots, sources) -> IngestPlan:
    """
    The plan of a folder re-scan that may ask the Source amplitude question.

    A re-scan only asks about Imported-result files the project does not know
    yet; a file it knows -- in the pool or taken out of it -- keeps its answer
    and is never asked again. `roots` and `sources` are copies taken on the
    calling thread; listing the folders and resolving the roots is disk work,
    so this runs on a worker (`PoolIngestUseCase.start_refresh`).
    """
    known = build_sources_by_path(roots, sources, read_root_directories(project_path, roots))
    imported: Dict[str, list] = {}
    for directory in directories:
        for path in discover_measurement_files(directory):
            reader = resolve_imported_result_reader(path)
            if reader is not None and canonical_path(path) not in known:
                imported.setdefault(reader, []).append(path)
    return IngestPlan(
        directories=tuple(directories),
        only_files={directory: set() for directory in directories},
        imported_files={reader: tuple(files) for reader, files in imported.items()},
    )


@dataclass(frozen=True)
class FolderReport:
    """
    What one folder of a running ingest did, for the shell to act on.

    Exactly one of `integrated` / `failure` is set. `integrated` carries the
    pool's own report so the shell can apply its effects (ADR 1.69);
    `log_messages` is what the run decided is worth saying about the folder,
    in the order it should be said.
    """

    directory: str
    integrated: Optional[IntegrateResult] = None
    failure: Optional[str] = None
    log_messages: Tuple[str, ...] = ()


@dataclass(frozen=True)
class IngestOutcome:
    """
    What a finished ingest adds up to.

    Every field is a decision already made: a cancelled or superseded run
    reports nothing to say and nothing to show, because the folders it did
    read are already in the pool and a summary plus a conflict dialog for a run
    the user just abandoned is noise, not information.
    """

    state: JobState
    completed: bool = False
    log_messages: Tuple[str, ...] = ()
    schema_conflicts: Tuple[Any, ...] = ()
    failures: Tuple[Tuple[str, str], ...] = ()
    report_failures: bool = False
    ask_for_setup: bool = False
    added_paths: Tuple[str, ...] = ()
    # The user cancelled the Source amplitude question: nothing was added, and
    # the run is a decision, not a failure to retry.
    declined: bool = False


class PoolIngestUseCase:
    """
    Runs one ingest at a time: folders in, reports out.

    Knows the pool, the project session and a `JobRunner`, and nothing else --
    no `app_context`, no window, no Qt. `start()` returns the job id the shell
    needs in order to follow the run's progress and to cancel it; cancelling is
    not this object's business, because the only cancel it would ever decide on
    its own is the supersede that `slot_key` already performs (ADR 1.70).
    """

    def __init__(self, pool, session, runner: JobRunner):
        self._pool = pool
        self._session = session
        self._runner = runner
        self._runs = 0
        self._active_run: Optional[int] = None
        self._job_id: Optional[int] = None

    @property
    def is_running(self) -> bool:
        """Whether a run this use case started is still going."""
        return self._active_run is not None

    @property
    def job_id(self) -> Optional[int]:
        """
        The job the running run is on right now, for the shell's progress and
        Cancel. A run from `start_selection` moves from its planning job to its
        folder job, so the shell asks here rather than keeping `submit`'s id.
        """
        return self._job_id

    def start_selection(self, paths, *, quiet: bool = False,
                        admit_unknown: bool = False, ask_for_setup: bool = False,
                        ask_source_amplitude: Optional[SourceAmplitudeAsker] = None,
                        on_folder: Optional[Callable[[FolderReport], None]] = None,
                        on_finished: Optional[Callable[[IngestOutcome], None]] = None) -> int:
        """
        Plans `paths` on a worker, then reads the planned folders as `start` does.

        Planning walks the selected trees and reads the headers of `.xlsx` /
        `.txt` files, which is disk work the calling (GUI) thread must not do
        (#507). It is a job of its own under the same `slot_key`, so a second
        Add supersedes a run still planning exactly as one already reading.

        `ask_source_amplitude`, when given, is called once the plan is known and
        before anything is read, with one question per Imported-result reader
        that has files in it; returning None cancels the whole Add.
        """
        return self._start_planned(
            "Add to Data Pool - finding measurements", "the selection",
            plan_pool_ingest, [list(paths)],
            quiet=quiet, admit_unknown=admit_unknown, ask_for_setup=ask_for_setup,
            ask_source_amplitude=ask_source_amplitude,
            on_folder=on_folder, on_finished=on_finished)

    def start_refresh(self, directories, *, quiet: bool = False,
                      ask_source_amplitude: Optional[SourceAmplitudeAsker] = None,
                      on_folder: Optional[Callable[[FolderReport], None]] = None,
                      on_finished: Optional[Callable[[IngestOutcome], None]] = None) -> int:
        """
        Re-reads folders already in the pool, asking about files the project
        does not know yet before they join it.

        Like `start_selection` it plans on a worker first: telling a new
        Imported-result file from a known one means listing the folder and
        reading generic-suffix headers. A refresh that must not ask goes
        straight to `start`.
        """
        session = self._session
        return self._start_planned(
            "Re-reading Data Pool folders - finding new measurements", "the folders",
            plan_pool_refresh,
            [tuple(directories), session.path, tuple(replace(root) for root in session.project.data_roots),
             tuple(session.project.sources)],
            quiet=quiet, admit_unknown=True, ask_for_setup=False,
            ask_source_amplitude=ask_source_amplitude,
            on_folder=on_folder, on_finished=on_finished)

    def _start_planned(self, label: str, step_label: str, plan_fn, args, *, quiet: bool,
                       admit_unknown: bool, ask_for_setup: bool,
                       ask_source_amplitude: Optional[SourceAmplitudeAsker],
                       on_folder, on_finished) -> int:
        self._runs += 1
        run = self._runs
        planned: Dict[str, Any] = {"plan": None, "failures": []}

        def _on_planned(record) -> None:
            if run != self._active_run:
                return
            plan = planned["plan"]
            if record.state is JobState.DONE and plan is not None:
                amplitudes = self._ask_source_amplitudes(plan, ask_source_amplitude)
                if amplitudes is None:
                    self._active_run = None
                    self._job_id = None
                    self._finish({"on_finished": on_finished},
                                 IngestOutcome(state=JobState.CANCELLED, declined=True))
                    return
                self._begin(plan, quiet=quiet, admit_unknown=admit_unknown,
                            ask_for_setup=ask_for_setup, source_amplitudes=amplitudes,
                            on_folder=on_folder, on_finished=on_finished)
                return
            self._active_run = None
            self._job_id = None
            failures = tuple(planned["failures"])
            self._finish({"on_finished": on_finished}, IngestOutcome(
                state=record.state,
                log_messages=tuple(f"POOL: Could not plan the ingest: {message}"
                                   for _, message in failures),
                failures=failures,
                report_failures=bool(failures) and not quiet,
            ))

        # Same rule as start(): the run exists before submit, which may finish
        # the whole run -- planning and folders -- before it returns.
        self._active_run = run
        job_id = self._runner.submit(
            label,
            [job_step(step_label, plan_fn, *args)],
            lane="batch", slot_key=INGEST_SLOT_KEY, max_parallel=1, quiet=quiet,
            on_step=lambda plan, _index: planned.update(plan=plan),
            on_error=lambda message, _index: planned["failures"].append(
                (step_label, message.splitlines()[0])),
            on_done=_on_planned,
        )
        if self._active_run == run:
            self._job_id = job_id
        return job_id

    @staticmethod
    def _ask_source_amplitudes(plan: IngestPlan,
                               ask: Optional[SourceAmplitudeAsker]) -> Optional[Dict[str, str]]:
        """
        File path -> Source amplitude the user answered for it; {} when nothing
        had to be asked, None when the user cancelled the question.
        """
        questions = plan_source_amplitude_questions(plan.imported_files) if ask is not None else ()
        if not questions:
            return {}
        answers = ask(questions)
        if answers is None:
            return None
        return resolve_file_amplitudes(plan.imported_files, answers)

    def start(self, plan: IngestPlan, *, quiet: bool = False,
              admit_unknown: bool = False, ask_for_setup: bool = False,
              ask_source_amplitude: Optional[SourceAmplitudeAsker] = None,
              on_folder: Optional[Callable[[FolderReport], None]] = None,
              on_finished: Optional[Callable[[IngestOutcome], None]] = None) -> Optional[int]:
        """
        Reads `plan`'s folders one at a time, folding each into the pool as it
        lands, and reports the run through `on_folder` / `on_finished`.

        One folder is one step and `max_parallel=1`: folders are read one at a
        time so the tree fills in progressively and several hundred-megabyte
        reads are not competing for the same disk. A folder of large files
        would then be a single jump from 0 to 100 percent, so the step is given
        a `progress_fn` (`progress_keyword`) it calls as it re-parses each
        stale file.

        With `ask_source_amplitude` the question is asked first; a cancelled
        question reports a declined outcome and returns None, with the run that
        was going on (if any) left alone.
        """
        amplitudes = self._ask_source_amplitudes(plan, ask_source_amplitude)
        if amplitudes is None:
            self._finish({"on_finished": on_finished},
                         IngestOutcome(state=JobState.CANCELLED, declined=True))
            return None
        return self._begin(plan, quiet=quiet, admit_unknown=admit_unknown,
                           ask_for_setup=ask_for_setup, source_amplitudes=amplitudes,
                           on_folder=on_folder, on_finished=on_finished)

    def _begin(self, plan: IngestPlan, *, quiet: bool, admit_unknown: bool,
               ask_for_setup: bool, source_amplitudes: Dict[str, str],
               on_folder, on_finished) -> int:
        self._runs += 1
        state = {
            "run": self._runs,
            "plan": plan,
            "quiet": quiet,
            "admit_unknown": admit_unknown,
            "ask_for_setup": ask_for_setup,
            "source_amplitudes": source_amplitudes,
            "directories": list(plan.directories),
            "added_paths": [],
            "failures": [],
            "on_folder": on_folder,
            "on_finished": on_finished,
        }
        # Session-derived values are read here, on the calling thread; the
        # worker steps receive them as plain data (ADR 1.54).
        scan_inputs = self._pool.prepare_scan_inputs()
        steps = [
            job_step(os.path.basename(directory) or directory,
                     self._pool.scan_pool_directory, directory,
                     **scan_inputs,
                     parent_excel_path=plan.parent_excel.get(directory))
            for directory in state["directories"]
        ]

        # Last statement that touches the run: submit() may report the whole
        # job finished before it returns (ADR 1.70).
        self._active_run = state["run"]
        job_id = self._runner.submit(
            f"Add to Data Pool - {len(steps)} folder(s)", steps,
            lane="batch", slot_key=INGEST_SLOT_KEY, max_parallel=1, quiet=quiet,
            progress_keyword="progress_fn",
            on_step=lambda payload, index: self._on_scanned(state, payload, index),
            on_error=lambda message, index: self._on_failed(state, message, index),
            on_done=lambda record: self._on_finished(state, record),
        )
        if self._active_run == state["run"]:
            self._job_id = job_id
        return job_id

    # ---- run callbacks (the thread that called start) -------------------

    def _on_scanned(self, state: dict, payload, index: int) -> None:
        directory = state["directories"][index]
        runs, schema, directory_index = payload
        plan: IngestPlan = state["plan"]

        only_files = plan.only_files.get(directory)
        extra = {}
        here = canonical_path(directory)
        answered = {path: amplitude for path, amplitude in state["source_amplitudes"].items()
                    if canonical_path(os.path.dirname(path)) == here}
        if answered:
            extra["source_amplitudes"] = answered
        result = self._pool.integrate_scanned_directory(
            directory, runs, schema, only_files, admit_unknown=state["admit_unknown"],
            index=directory_index, **extra
        )

        wanted = (only_files if only_files is not None
                  else {canonical_path(run.file_path) for run in runs})
        state["added_paths"].extend(wanted)

        tag = plan.auto_tag.get(directory)
        if tag and wanted:
            apply_setup_label(self._session, wanted, tag)

        self._report(state, FolderReport(directory=directory, integrated=result))

    def _on_failed(self, state: dict, message: str, index: int) -> None:
        directory = state["directories"][index]
        state["failures"].append((directory, message))
        self._report(state, FolderReport(
            directory=directory, failure=message,
            log_messages=(f"POOL: Could not read {directory}: {message}",),
        ))

    def _on_finished(self, state: dict, record) -> None:
        # A superseded run's late on_done: the run that replaced it owns the
        # screen now, and this one has nothing left to say (audit 02, S3/3.1).
        if state["run"] != self._active_run:
            return
        self._active_run = None
        self._job_id = None

        if record.state is not JobState.DONE:
            self._finish(state, IngestOutcome(state=record.state))
            return

        quiet = state["quiet"]
        skipped = tuple(f"POOL: Skipped {path}: not a measurement file."
                        for path in state["plan"].skipped_files)
        summary = skipped + (() if quiet else (
            f"POOL: {len(self._pool.loaded_runs)} measurement(s) in the pool "
            f"from {len(self._pool.pool_directories)} folder(s).",
        ))
        added_paths = tuple(state["added_paths"])
        failures = tuple(state["failures"])
        self._finish(state, IngestOutcome(
            state=record.state,
            completed=True,
            log_messages=summary,
            schema_conflicts=tuple(self._pool.schema().conflicts),
            failures=failures,
            # A refresh nobody asked for reports through the log only; a popup
            # arriving out of nowhere would make the watcher a feature to
            # switch off.
            report_failures=bool(failures) and not quiet,
            ask_for_setup=bool(state["ask_for_setup"] and added_paths),
            added_paths=added_paths,
        ))

    # ---- reporting ------------------------------------------------------

    @staticmethod
    def _report(state: dict, report: FolderReport) -> None:
        callback = state["on_folder"]
        if callback is not None:
            callback(report)

    @staticmethod
    def _finish(state: dict, outcome: IngestOutcome) -> None:
        callback = state["on_finished"]
        if callback is not None:
            callback(outcome)
