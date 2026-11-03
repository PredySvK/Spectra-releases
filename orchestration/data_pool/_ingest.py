"""
The decision half of "Add to Data Pool": one folder per step over a JobRunner.

What this module owns is the *sequence*: which folders are read, in what
order, what happens to each one when it lands, and what the run adds up to at
the end. It never draws anything. The progress dialog, the Cancel button, the
explorer refresh, the conflict dialog and the failure popup are consequences
the shell applies to the reports this module hands it.

Two properties of the run are the reason it is written the way it is:

* **The identity of a run exists before `submit`.** `on_done` may arrive
  before `submit` returns -- always for `SynchronousJobRunner`, and for
  QtJobRunner whenever there are no steps. So the run's state dict,
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
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from core.jobs import JobState, job_step
from core.import_template import ImportTemplate
from io_modules.import_template import (
    resolve_installed_template, read_template_candidates, resolve_template_name_fit,
)
from io_modules.pool_ingest_plan import discover_selection_tree
from io_modules.measurement_files import (
    canonical_path, discover_measurement_files, resolve_imported_result_reader, is_measurement_file,
)
from orchestration.data_pool._missing_measurement_check import MissingMeasurementCheck
from orchestration.data_pool._selection_plan import (
    build_ingest_folder_map, find_parent_metadata_files,
)
from orchestration.data_pool._template_assignment import (
    ImportTemplateAsker, Misfit, plan_template_assignment, resolve_unanswered_misfits, plan_template_questions,
    resolve_template_answers,
)
from orchestration.data_pool._test_setup import resolve_test_setups
from io_modules.project_store import DirectoryIndex, read_root_directories
from orchestration.data_pool._source_amplitude import (
    SourceAmplitudeAsker, plan_source_amplitude_questions, resolve_file_amplitudes,
)
from orchestration.jobs import JobRunner
from io_modules.scan_cache import ScannedDirectory, read_pool_folder
from session.data_pool import IntegrateResult
from session.project import apply_setup_label
from session.source_location import build_source_location

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

    `import_templates` maps a file path to the Import template this run
    assigns to it. `ambiguous` are files that fit several templates, until the
    user chooses (path -> the names of the templates that fit); `misfits` are
    files whose name belongs to a template that their content does not fit --
    they are never read into the pool and the run reports them.
    """

    directories: Tuple[str, ...] = ()
    only_files: Dict[str, Optional[set]] = field(default_factory=dict)
    parent_excel: Dict[str, str] = field(default_factory=dict)
    skipped_files: Tuple[str, ...] = ()
    imported_files: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    import_templates: Dict[str, str] = field(default_factory=dict)
    ambiguous: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    misfits: Tuple[Misfit, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.directories)


def plan_pool_ingest(paths, folder_files: Optional[dict] = None, project_path=None,
                     roots=(), sources=(), templates: Sequence[ImportTemplate] = ()) -> IngestPlan:
    """
    Turns a path selection into the plan one ingest runs on.

    `folder_files` is the explicit form used by a folder re-scan, which names
    its folders and passes no paths: it re-tags nothing and inherits no parent
    sheet, so both maps come out empty.

    Walks each selected folder tree once and reads the headers of generic-suffix
    files, so for a path selection it runs on a worker (`PoolIngestUseCase.start_selection`).
    `roots` and `sources` (copies, as for `plan_pool_refresh`) let a file the project
    already knows keep the Import template it was assigned. `templates` are
    what this Add reads with: a file whose name and header fit one is assigned
    it, one that fits several is `ambiguous`, one whose name belongs to a
    template its header does not fit is a misfit.
    """
    tree = discover_selection_tree(paths)
    known = build_source_location(roots, sources, read_root_directories(project_path, roots))
    folder_files = folder_files if folder_files is not None else build_ingest_folder_map(paths, tree)
    candidates = {canonical_path(path): path for directory in tree.walked
                  for path in read_template_candidates(directory, templates)}
    candidates.update({canonical_path(path): path for path in paths
                       if os.path.isfile(path) and any(
                           resolve_template_name_fit(path, template) for template in templates)})
    found = plan_template_assignment(candidates.values(), templates)
    assigned_by_key = {canonical_path(path): name for path, name in found.assigned.items()}
    ambiguous_keys = {canonical_path(path) for path in found.ambiguous}
    misfits = tuple(misfit for misfit in found.misfits
                    if not _is_assigned(known.entry_for_path(misfit.path)))
    imported: Dict[str, list] = {}
    for directory, files in folder_files.items():
        # A whole folder (None) is every file in it; a picked set is just those.
        for path in sorted(tree.files_in(directory) if files is None else files):
            if canonical_path(path) in ambiguous_keys:
                continue
            entry = known.entry_for_path(path)
            import_template = assigned_by_key.get(canonical_path(path)) or (entry.import_template if entry else "")
            reader = resolve_imported_result_reader(path, import_template)
            if reader is not None:
                imported.setdefault(reader, []).append(path)
    misfit_keys = {canonical_path(misfit.path) for misfit in misfits}
    return IngestPlan(
        directories=tuple(folder_files.keys()),
        only_files=dict(folder_files),
        parent_excel=find_parent_metadata_files(tree),
        skipped_files=tuple(path for path in paths
                            if os.path.isfile(path) and not is_measurement_file(path)
                            and canonical_path(path) not in misfit_keys),
        imported_files={reader: tuple(files) for reader, files in imported.items()},
        import_templates=dict(found.assigned),
        ambiguous=dict(found.ambiguous),
        misfits=misfits,
    )


def _is_assigned(entry) -> bool:
    return bool(entry is not None and entry.import_template)


def plan_pool_refresh(directories, project_path, roots, sources) -> IngestPlan:
    """
    The plan of a folder re-scan that may ask the Source amplitude question.

    A re-scan only asks about Imported-result files the project does not know
    yet; a file it knows -- in the pool or taken out of it -- keeps its answer
    and is never asked again. `roots` and `sources` are copies taken on the
    calling thread; listing the folders and resolving the roots is disk work,
    so this runs on a worker (`PoolIngestUseCase.start_refresh`).
    """
    known = build_source_location(roots, sources, read_root_directories(project_path, roots)).entries_by_path
    imported: Dict[str, list] = {}
    assigned: Dict[str, str] = {}
    ambiguous: Dict[str, Tuple[str, ...]] = {}
    misfits = []
    for directory in directories:
        # A new file is read with the templates the folder's files already have.
        templates = _templates_of_folder(directory, known)
        unknown = [path for path in read_template_candidates(directory, templates)
                   if canonical_path(path) not in known]
        found = plan_template_assignment(unknown, templates)
        assigned.update(found.assigned)
        ambiguous.update(found.ambiguous)
        misfits.extend(found.misfits)
        assigned_by_key = {canonical_path(path): name for path, name in found.assigned.items()}
        ambiguous_keys = {canonical_path(path) for path in found.ambiguous}
        for path in discover_measurement_files(directory):
            key = canonical_path(path)
            if key in known or key in ambiguous_keys:
                continue
            reader = resolve_imported_result_reader(path, assigned_by_key.get(key, ""))
            if reader is not None:
                imported.setdefault(reader, []).append(path)
    return IngestPlan(
        directories=tuple(directories),
        only_files={directory: set() for directory in directories},
        imported_files={reader: tuple(files) for reader, files in imported.items()},
        import_templates=assigned,
        ambiguous=ambiguous,
        misfits=tuple(misfits),
    )


def plan_template_rescan(name: str, project_path, roots, sources, pool_directories=()) -> IngestPlan:
    """
    The plan that re-reads the files the Import template `name` reads, after
    the project's copy of it was edited.

    Only the pool folders that hold such a file are read, and nothing new is
    admitted: the scan re-parses a file whose template changed (its cache key
    holds the copy's fingerprint), so every other file of those folders is
    served from the cache. A file of the template that the user took out of
    the pool stays out. Resolving the roots is disk work: runs on a worker.
    """
    known = build_source_location(roots, sources, read_root_directories(project_path, roots)).entries_by_path
    pooled = {canonical_path(directory): directory for directory in pool_directories}
    held = {canonical_path(os.path.dirname(path)) for path, entry in known.items() if entry.import_template == name}
    directories = tuple(pooled[key] for key in sorted(held) if key in pooled)
    return IngestPlan(directories=directories, only_files={directory: set() for directory in directories})


def _templates_of_folder(directory: str, known: Mapping[str, Any]) -> Tuple[ImportTemplate, ...]:
    """The installed Import templates that files already in `directory` are assigned."""
    here = canonical_path(directory)
    names = sorted({entry.import_template for path, entry in known.items()
                    if entry.import_template and canonical_path(os.path.dirname(path)) == here})
    return tuple(template for template in map(resolve_installed_template, names) if template is not None)


def _templates_in(import_templates: Dict[str, str], directory: str) -> Dict[str, str]:
    """The part of path -> template name that lies directly in `directory`."""
    here = canonical_path(directory)
    return {path: name for path, name in import_templates.items()
            if canonical_path(os.path.dirname(path)) == here}


def _without_misfits(scanned: ScannedDirectory, misfits: Tuple[Misfit, ...]) -> ScannedDirectory:
    """The scan minus the files that are misfits, so they neither enter the pool nor become sources."""
    out = {canonical_path(misfit.path) for misfit in misfits}
    if not out:
        return scanned
    listing = {path: stamp for path, stamp in scanned.index.file_listing.items()
               if canonical_path(path) not in out}
    return scanned._replace(
        runs=[run for run in scanned.runs if canonical_path(run.file_path) not in out],
        index=DirectoryIndex(listing, scanned.index.root_directories))


@dataclass(frozen=True)
class FolderReport:
    """
    What one folder of a running ingest did, for the shell to act on.

    Exactly one of `integrated` / `failure` is set. `integrated` carries the
    pool's own report so the shell can apply its effects;
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
    # Files that do not fit the Import template their name belongs to: not in
    # the pool, listed once for the run. `report_misfits` is whether the shell
    # shows them (a refresh nobody asked for reports through the log only).
    misfits: Tuple[Misfit, ...] = ()
    report_misfits: bool = False


class PoolIngestUseCase:
    """
    Runs one ingest at a time: folders in, reports out.

    Knows the pool, the project session and a `JobRunner`, and nothing else --
    no `app_context`, no window, no Qt. `start()` returns the job id the shell
    needs in order to follow the run's progress and to cancel it; cancelling is
    not this object's business, because the only cancel it would ever decide on
    its own is the supersede that `slot_key` already performs.
    """

    def __init__(self, pool, session, runner: JobRunner, *,
                 missing_check: Optional[MissingMeasurementCheck] = None,
                 read_folder: Optional[Callable[..., ScannedDirectory]] = None):
        self._pool = pool
        self._session = session
        self._runner = runner
        # What each step runs on a worker: the folder read itself. A test hands
        # in its own so the run can be followed without a disk.
        self._read_folder = read_folder or read_pool_folder
        # Started after every ingest that finished, so a file deleted while the
        # application runs is marked once the next scan of its folder lands.
        self._missing_check = missing_check
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
                        import_templates: Sequence[ImportTemplate] = (),
                        ask_source_amplitude: Optional[SourceAmplitudeAsker] = None,
                        ask_import_template: Optional[ImportTemplateAsker] = None,
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

        `import_templates` are the templates the user added with: the project
        takes a copy of each now (on this thread), and every file one fits is
        read by that copy and assigned to its source. A copy the project holds
        already under the name stays, so the fit is checked against the copy
        that reads the file, never against the template passed. The files they
        read are not asked about their Source amplitude -- the template says. A file
        that fits several is put to `ask_import_template` (without it the file
        is a misfit); files that fit none of the templates their name belongs
        to are reported as misfits and not read.
        """
        session = self._session
        for template in import_templates:
            session.adopt_import_template(template)
        copies = tuple(session.resolve_import_template(template.name) or template for template in import_templates)
        return self._start_planned(
            "Add to Data Pool - finding measurements", "the selection",
            plan_pool_ingest,
            [list(paths), None, session.path, tuple(replace(root) for root in session.project.data_roots),
             tuple(session.project.sources), copies],
            quiet=quiet, admit_unknown=admit_unknown, ask_for_setup=ask_for_setup,
            ask_source_amplitude=ask_source_amplitude, ask_import_template=ask_import_template,
            on_folder=on_folder, on_finished=on_finished)

    def start_refresh(self, directories, *, quiet: bool = False,
                      ask_source_amplitude: Optional[SourceAmplitudeAsker] = None,
                      ask_import_template: Optional[ImportTemplateAsker] = None,
                      on_folder: Optional[Callable[[FolderReport], None]] = None,
                      on_finished: Optional[Callable[[IngestOutcome], None]] = None) -> int:
        """
        Re-reads folders already in the pool, asking about files the project
        does not know yet before they join it.

        Like `start_selection` it plans on a worker first: telling a new
        Imported-result file from a known one means listing the folder and
        reading generic-suffix headers. Without `ask_source_amplitude` nothing
        is asked, which is what opening a project wants.

        A new file whose name fits an Import template its folder already uses
        is read by it, or reported as a misfit when its content does not fit.
        """
        session = self._session
        return self._start_planned(
            "Re-reading Data Pool folders - finding new measurements", "the folders",
            plan_pool_refresh,
            [tuple(directories), session.path, tuple(replace(root) for root in session.project.data_roots),
             tuple(session.project.sources)],
            quiet=quiet, admit_unknown=True, ask_for_setup=False,
            ask_source_amplitude=ask_source_amplitude, ask_import_template=ask_import_template,
            on_folder=on_folder, on_finished=on_finished)

    def start_template_edit(self, template: ImportTemplate, *, quiet: bool = False,
                            on_folder: Optional[Callable[[FolderReport], None]] = None,
                            on_finished: Optional[Callable[[IngestOutcome], None]] = None) -> int:
        """
        Confirms an edit of the project's copy of an Import template: the copy
        of `template`'s name is replaced now (on this thread), and the files it
        reads are re-read on a worker -- only those (`plan_template_rescan`).

        Nothing is asked: the files are known, their template and Source
        amplitude already decided. A file the edited template no longer fits
        is Unreadable, naming the template, and leaves the pool until it fits.
        """
        session = self._session
        session.replace_import_template(template)
        return self._start_planned(
            f"Re-reading the files of the Import template '{template.name}'", "the files",
            plan_template_rescan,
            [template.name, session.path, tuple(replace(root) for root in session.project.data_roots),
             tuple(session.project.sources), tuple(self._pool.pool_directories)],
            quiet=quiet, admit_unknown=False, ask_for_setup=False,
            ask_source_amplitude=None, ask_import_template=None,
            on_folder=on_folder, on_finished=on_finished)

    def _start_planned(self, label: str, step_label: str, plan_fn, args, *, quiet: bool,
                       admit_unknown: bool, ask_for_setup: bool,
                       ask_source_amplitude: Optional[SourceAmplitudeAsker],
                       ask_import_template: Optional[ImportTemplateAsker],
                       on_folder, on_finished) -> int:
        self._runs += 1
        run = self._runs
        planned: Dict[str, Any] = {"plan": None, "failures": []}

        def _on_planned(record) -> None:
            if run != self._active_run:
                return
            plan = planned["plan"]
            if record.state is JobState.DONE and plan is not None:
                plan = self._resolve_ambiguous(plan, ask_import_template)
                amplitudes = None if plan is None else self._ask_source_amplitudes(plan, ask_source_amplitude)
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
    def _resolve_ambiguous(plan: IngestPlan, ask: Optional[ImportTemplateAsker]) -> Optional[IngestPlan]:
        """
        The plan with every file that fits several Import templates put to the
        user; a file nobody chose a template for becomes a misfit. None when
        the user cancelled the question.
        """
        if not plan.ambiguous:
            return plan
        answers: Mapping = {}
        if ask is not None:
            answers = ask(plan_template_questions(plan.ambiguous))
            if answers is None:
                return None
        chosen = resolve_template_answers(plan.ambiguous, answers)
        return replace(plan, import_templates={**plan.import_templates, **chosen}, ambiguous={},
                       misfits=plan.misfits + resolve_unanswered_misfits(plan.ambiguous, chosen))

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
        # worker steps receive them as plain data.
        scan_inputs = self._pool.prepare_scan_inputs()
        steps = [
            job_step(os.path.basename(directory) or directory,
                     self._read_folder, directory,
                     **scan_inputs,
                     **self._assigned_scan_input(plan, directory),
                     parent_excel_path=plan.parent_excel.get(directory))
            for directory in state["directories"]
        ]

        # Last statement that touches the run: submit() may report the whole
        # job finished before it returns.
        self._active_run = state["run"]
        job_id = self._runner.submit(
            f"Add to Data Pool - {len(steps)} folder(s)", steps,
            lane="batch", slot_key=INGEST_SLOT_KEY, max_parallel=1, quiet=quiet,
            progress_keyword="progress_fn",
            on_step=lambda scanned, index: self._on_scanned(state, scanned, index),
            on_error=lambda message, index: self._on_failed(state, message, index),
            on_done=lambda record: self._on_finished(state, record),
        )
        if self._active_run == state["run"]:
            self._job_id = job_id
        return job_id

    @staticmethod
    def _assigned_scan_input(plan: IngestPlan, directory: str) -> Dict[str, Any]:
        """The Import templates this Add assigns in one folder, as the scan's input; {} when none."""
        assigned = _templates_in(plan.import_templates, directory)
        return {"assigned_templates": assigned} if assigned else {}

    # ---- run callbacks (the thread that called start) -------------------

    def _on_scanned(self, state: dict, scanned: ScannedDirectory, index: int) -> None:
        directory = state["directories"][index]
        plan: IngestPlan = state["plan"]
        scanned = _without_misfits(scanned, plan.misfits)

        only_files = plan.only_files.get(directory)
        extra = {}
        here = canonical_path(directory)
        answered = {path: amplitude for path, amplitude in state["source_amplitudes"].items()
                    if canonical_path(os.path.dirname(path)) == here}
        if answered:
            extra["source_amplitudes"] = answered
        assigned = _templates_in(plan.import_templates, directory)
        if assigned:
            extra["import_templates"] = assigned
        result = self._pool.integrate_scanned_directory(
            directory, scanned, only_files=only_files, admit_unknown=state["admit_unknown"], **extra
        )

        wanted = (only_files if only_files is not None
                  else {canonical_path(run.file_path) for run in scanned.runs})
        state["added_paths"].extend(wanted)

        if result.entered:
            self._assign_test_setups(result.entered)

        # A quiet refresh repeats the list only when it changed, so a recorder
        # still writing a file does not flood the log on every watcher tick.
        lines = ()
        if not state["quiet"] or result.read_problems_changed:
            lines = tuple(f"POOL: {line}" for line in result.read_problems.lines(directory))
        self._report(state, FolderReport(
            directory=directory, integrated=result,
            log_messages=lines + tuple(scanned.messages)))

    def _assign_test_setups(self, entered) -> None:
        """
        Files each measurement that just entered the pool without a Test setup
        under the one ADR §1.207 resolves. Only what entered: a measurement
        already in the pool keeps whatever it carries, Unassigned included.
        """
        session = self._session
        setup_by_path = {path: entry.setup_label
                         for path, entry in session.source_location.entries_by_path.items()}
        resolved = resolve_test_setups(entered, setup_by_path, session.project.setup_labels())
        paths_by_setup: Dict[str, list] = {}
        for path, label in resolved.items():
            paths_by_setup.setdefault(label, []).append(path)
        for label, paths in paths_by_setup.items():
            apply_setup_label(session, paths, label)

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
        if self._missing_check is not None:
            self._missing_check.start()

        quiet = state["quiet"]
        skipped = tuple(f"POOL: Skipped {path}: not a measurement file."
                        for path in state["plan"].skipped_files)
        listed = tuple(f"POOL: {misfit.path} does not fit the Import template {misfit.template}: {misfit.reason}."
                       for misfit in state["plan"].misfits)
        summary = skipped + listed + (() if quiet else (
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
            misfits=state["plan"].misfits,
            report_misfits=bool(state["plan"].misfits) and not quiet,
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
