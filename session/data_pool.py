# =====================================================================
# FILE: session/data_pool.py
# =====================================================================
"""
The Data Pool: the working set of measurements, from every folder the user
has added to it (CONTEXT.md "Data Pool" -- not the panel that shows it, not
the last-viewed folder).

Owns loaded_runs, the pool's folders and the merged metadata schema, and
keeps all three reconciled with the ProjectSession on every change (add,
remove, remove-runs, restore). Also hosts trace resolution (DeadLink,
ResolvedTrace, build_source_lookup, resolve_trace, resolve_traces) turning
TraceSpecs back into live pool entries (#175). Lives in session/ because it
orchestrates
ProjectSession, metadata_schema, and canonical_path rather than being
plain core data or application shell.

Knows nothing of Qt, QSettings, the log hook or the session role. Methods
return counts and integrate_scanned_directory returns an IntegrateResult;
the application shell (AppContext) turns those into last-viewed-folder moves,
startup-pointer writes and log lines. No rule from ADR §1.24 changes here --
the code moved 1:1 out of AppContext.
"""

import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Union

from core.models import ChannelMetadata, MeasurementRunIndex
from core.project_model import NVHProject, SourceEntry
from io_modules.metadata_schema import NUMERIC_KINDS, infer_field_kind, resolve_schema_field
from io_modules.measurement_files import canonical_path
from io_modules.scan_cache import MeasurementScanner
from session.project import ProjectSession, correct_entry_channel, correct_run_channel
from io_modules.project_store import (
    DirectoryIndex,
    project_folder,
    read_root_directories,
    resolve_root,
    scan_cache_folder,
    untitled_scan_cache_folder,
)

# The project-wide Level 2 Excel sheet, primary source for run metadata --
# one file for every data root in the project, living beside the .nvhproject.
PROJECT_METADATA_EXCEL_NAME = "metadata.xlsx"


@dataclass(frozen=True)
class MergedSchema:
    master: dict
    conflicts: list
    baseline: dict = field(default_factory=dict)


# The same field name meaning two different things in two data folders. Both
# kinds are merged rather than refused -- a union that loses a column would
# hide data the user just added -- but the user is told, because a facet built
# out of a collision reads as one field and behaves like two.
LAYER_CONFLICT = "layer"        # spreadsheet column here, measurement-file fact there
TYPE_CONFLICT = "value_type"    # numbers here, free text there


@dataclass
class SchemaConflict:
    """
    One field name that two data folders disagree about.

    `detail` maps each folder to what it says about the field, so the dialog
    can name the folders rather than asking the user to guess which of their
    Excel sheets is the odd one out.
    """
    key: str
    kind: str
    detail: Dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        parts = ", ".join(f"{where}: {what}" for where, what in self.detail.items())
        if self.kind == LAYER_CONFLICT:
            return f"'{self.key}' is a spreadsheet column in one folder and a file header field in another ({parts})."
        return f"'{self.key}' holds different kinds of value per folder ({parts})."


# Which collisions the user has already been shown, so re-scanning the same
# folders is silent. Kept in ui_state rather than beside the field's own
# settings in metadata_schema: the metadata editor rewrites that dict
# wholesale from what it was given, which would drop an extra key it knows
# nothing about and make this dialog reappear after every visit to the editor.
ACKNOWLEDGED_KEY = "acknowledged_schema_conflicts"


def unacknowledged(project_or_context: Any,
                   conflicts: List[SchemaConflict]) -> List[SchemaConflict]:
    """The conflicts the user has not already been shown for these fields."""
    if hasattr(project_or_context, "project_session"):
        ui_state = getattr(project_or_context.project_session.project, "ui_state", {})
    elif hasattr(project_or_context, "project"):
        ui_state = getattr(project_or_context.project, "ui_state", {})
    elif hasattr(project_or_context, "ui_state"):
        ui_state = project_or_context.ui_state
    elif isinstance(project_or_context, dict):
        ui_state = project_or_context
    else:
        ui_state = {}
    seen = set(ui_state.get(ACKNOWLEDGED_KEY) or [])
    return [conflict for conflict in conflicts if conflict.key not in seen]


def merge_schema_master(baseline: Dict[str, Any], stored: Dict[str, Any]) -> Dict[str, Any]:
    """
    Combines a freshly discovered schema with the one saved in the project.

    Both halves matter and neither may win outright. The baseline is the only
    thing that knows about fields that exist now -- a column added to the Excel
    sheet since the project was saved appears only here, and dropping it would
    hide data the user just added. The stored half is the only record of what
    the user decided about a field, so a rediscovered field must not have its
    label and visibility reset to the defaults every time a folder is scanned.

    So: the baseline decides which fields exist, the project decides how the
    ones it knows about are presented. Fields the project remembers that are no
    longer discovered are dropped, because they describe nothing.
    """
    return {
        key: resolve_schema_field({"custom_label": key, **defaults}, stored.get(key))
        if isinstance(stored.get(key), dict)
        else resolve_schema_field(defaults)
        for key, defaults in baseline.items()
    }


def merge_schema_baselines(baselines_by_root: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Unions the per-folder baseline schemas of every data root in the pool.

    A project draws from several folders now, each with its own Metadata.xlsx
    and therefore its own set of columns. The union is what lets a file be
    filtered on a field its own folder never heard of -- it simply has no value
    for it, which the filter panel already handles by not offering that value.

    The first folder to define a field owns its definition. Dictionaries keep
    insertion order, so this is the folder the user added first, which makes
    the result stable across restarts rather than dependent on scan timing.
    Genuine disagreements are not resolved here; see detect_schema_conflicts.
    """
    merged: Dict[str, Any] = {}
    for baseline in baselines_by_root.values():
        for key, definition in baseline.items():
            merged.setdefault(key, dict(definition))
    return merged


def collect_metadata_value_types(indexed_runs: List[MeasurementRunIndex]) -> Dict[str, str]:
    """
    What kind of value each Level 2 field actually carries in these runs.

    Reports "number", "text" or "mixed" per field. Blank values are ignored
    rather than counted as text: a column that is simply not filled in for some
    runs is the normal case, not a disagreement about what the column is.
    """
    seen: Dict[str, set] = {}
    for run in indexed_runs:
        metadata = getattr(run, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        for key, value in metadata.items():
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            kind = "number" if infer_field_kind([value]) in NUMERIC_KINDS else "text"
            seen.setdefault(key, set()).add(kind)

    return {
        key: (next(iter(kinds)) if len(kinds) == 1 else "mixed")
        for key, kinds in seen.items()
    }


def detect_schema_conflicts(baselines_by_root: Dict[str, Dict[str, Any]],
                            value_types_by_root: Optional[Dict[str, Dict[str, str]]] = None
                            ) -> List[SchemaConflict]:
    """
    Finds the field names two data folders genuinely disagree about.

    Two folders both having a "Speed" column is not a conflict -- that is the
    whole point of the union and the reason cross-folder comparison works at
    all. What is reported is a field whose meaning changes between folders:
    one where the name is a spreadsheet column here and a measurement-file
    header field there, and one where the values are numbers here and text
    there. Both survive the merge; the caller decides what to tell the user.

    `value_types_by_root` is optional because the layer check needs only the
    schemas, which the folder scan already returns, while the type check needs
    the runs themselves.
    """
    conflicts: List[SchemaConflict] = []

    layers_by_key: Dict[str, Dict[str, str]] = {}
    for root, baseline in baselines_by_root.items():
        for key, definition in baseline.items():
            layer = str(definition.get("layer", "excel"))
            layers_by_key.setdefault(key, {})[root] = layer

    for key, per_root in layers_by_key.items():
        if len(set(per_root.values())) > 1:
            conflicts.append(SchemaConflict(key=key, kind=LAYER_CONFLICT, detail=dict(per_root)))

    if not value_types_by_root:
        return conflicts

    already_reported = {conflict.key for conflict in conflicts}
    types_by_key: Dict[str, Dict[str, str]] = {}
    for root, value_types in value_types_by_root.items():
        for key, kind in value_types.items():
            types_by_key.setdefault(key, {})[root] = kind

    for key, per_root in types_by_key.items():
        if key in already_reported:
            continue
        if len(set(per_root.values())) > 1 or set(per_root.values()) == {"mixed"}:
            conflicts.append(SchemaConflict(key=key, kind=TYPE_CONFLICT, detail=dict(per_root)))

    return conflicts


@dataclass(frozen=True)
class IntegrateResult:
    """
    What integrate_scanned_directory did, for the shell to act on.

    `is_new_folder` is decided by the pool (it holds pool_keys); the shell
    reads it to know whether to move the last-viewed folder and write the
    startup pointer. `unit_corrections` / `metadata_synced` are counts the
    shell logs -- the pool itself never touches the log panel.
    """
    gained: int
    is_new_folder: bool
    stored_path: str
    unit_corrections: int
    metadata_synced: int


def run_from_entry(entry: SourceEntry, directory: str) -> Optional[MeasurementRunIndex]:
    """
    Rebuilds one measurement from its project entry, or None if it is not in
    the pool, or if the project never stored its channels -- an entry indexed
    by an older build, or one added but not yet scanned. Such a file is not
    shown as an empty node; it appears once the background scan reaches it.
    """
    if not entry.channels or not entry.in_pool:
        return None

    absolute = os.path.join(directory, entry.relpath)
    run = MeasurementRunIndex(os.path.basename(entry.relpath), absolute)
    run.metadata = dict(entry.excel_metadata)

    # file_level_facts() filtered these on the way out, but a project file is
    # editable text and a hand-written "file_path" here would quietly point the
    # run at another file.
    for key, value in entry.file_metadata.items():
        if key.startswith("_") or key in MeasurementRunIndex._STRUCTURAL_ATTRS:
            continue
        setattr(run, key, value)

    for label, facts in entry.channels.items():
        run.add_channel_metadata(label, ChannelMetadata.from_dict(facts))

    for channel_label, unit in entry.unit_overrides.items():
        correct_run_channel(run, channel_label, unit)
        correct_entry_channel(entry, channel_label, unit)

    return run


def runs_by_directory(project: NVHProject,
                      project_path: Optional[str]) -> Dict[str, List[MeasurementRunIndex]]:
    """
    Every measurement the project remembers, grouped by the folder it lives in.

    Grouped by folder because that is the unit the pool adds, re-scans and
    removes. A root that cannot be resolved right now is skipped rather than
    reported: its files have not moved as far as the project is concerned, and
    saying so is the job of the index pass, not of drawing a tree.
    """
    by_directory: Dict[str, List[MeasurementRunIndex]] = {}

    for root in project.data_roots:
        directory = resolve_root(project_path, root)
        if directory is None:
            continue

        runs = []
        for entry in project.sources:
            if entry.root_id != root.id:
                continue
            run = run_from_entry(entry, directory)
            if run is not None:
                runs.append(run)

        if runs:
            by_directory.setdefault(directory, []).extend(runs)

    return by_directory


# ---- trace resolution (TraceSpec -> live run/channel or DeadLink) ----


@dataclass(frozen=True)
class DeadLink:
    """A ``(source_id, channel_name)`` pair that no longer resolves against the pool."""

    source_id: str
    channel_name: str
    reason: str  # "file_not_loaded" | "channel_not_found" | "file_unreadable"


@dataclass(frozen=True)
class ResolvedTrace:
    """A ``(source_id, channel_name)`` pair resolved to its live pool entries."""

    run_index: MeasurementRunIndex
    channel_meta: ChannelMetadata


def build_source_lookup(loaded_runs: List[MeasurementRunIndex]) -> Dict[str, MeasurementRunIndex]:
    """
    ``canonical_path(run.file_path) -> run`` for every loaded run.

    Built once and passed to ``resolve_trace`` when resolving many traces (a
    whole ``TabSpec``, or a restore over several tabs) so the pool is not
    walked once per trace -- same reasoning as ``channel_drop.py``'s
    ``runs_by_path``, keyed canonically instead of raw because ``source_id`` is
    already a ``canonical_path`` (``TraceSpec`` docstring).
    """
    return {canonical_path(run.file_path): run for run in loaded_runs}


def resolve_trace(source_id: str, channel_name: str,
                  source_lookup: Dict[str, MeasurementRunIndex]) -> Union[ResolvedTrace, DeadLink]:
    """
    Resolve one ``(source_id, channel_name)`` pair against an already-built
    ``source_lookup`` (``build_source_lookup``).

    Two ways to be dead: the file itself isn't in the pool right now (moved,
    removed, or the project just hasn't loaded its folder yet), or the file is
    there but this particular channel isn't (re-recorded with a different
    channel set). Both are reported distinctly so a restore log line can say
    which one happened.
    """
    run_index = source_lookup.get(source_id)
    if run_index is None:
        return DeadLink(source_id, channel_name, reason="file_not_loaded")

    from selection.channel_identity import resolve_stripped_override

    # Older snapshots and base recipes used plain names. Resolve them only
    # when unambiguous; duplicate names must keep their exact reader label.
    channels = run_index.available_channels
    label = resolve_stripped_override(
        channel_name, ((key, meta.name) for key, meta in channels.items()),
    )
    channel_meta = channels.get(label)
    if channel_meta is None:
        return DeadLink(source_id, channel_name, reason="channel_not_found")

    return ResolvedTrace(run_index, channel_meta)


def resolve_traces(pairs: List[Tuple[str, str]],
                   loaded_runs: List[MeasurementRunIndex]) -> List[Union[ResolvedTrace, DeadLink]]:
    """
    Resolve several ``(source_id, channel_name)`` pairs against ``loaded_runs``
    in one pass -- the convenience form S4/S6 call for a whole ``TabSpec``.
    """
    source_lookup = build_source_lookup(loaded_runs)
    return [resolve_trace(source_id, channel_name, source_lookup) for source_id, channel_name in pairs]


class DataPool:
    def __init__(self, project_session: ProjectSession):
        # A stable reference: AppContext.__init__ makes it once and never
        # reassigns it (ProjectSession.open_project mutates in place).
        self.project_session = project_session

        # The only consumer is scan_pool_directory.
        self.scanner = MeasurementScanner()

        # Every measurement currently in the Data Pool, from every folder that
        # has been added to it. Deliberately one flat list of runs: what a run
        # belongs to is a question for the project (its SourceEntry), and
        # keeping the shape means everything that iterates over the workspace --
        # unit fixes, the comparator, the order batch -- kept working unchanged
        # when the pool grew from one folder to many.
        self.loaded_runs: List[MeasurementRunIndex] = []

        # Folders in the pool, in the order the user added them.
        self.pool_directories: List[str] = []

        # Per-folder baseline schema, kept apart so a folder can be removed
        # from the pool without its columns lingering in the merged schema.
        self._schema_baselines: dict = {}

        # Lazily derived on first access and cached until the pool's membership,
        # baselines, or project schema change.
        self._merged_schema: Optional[MergedSchema] = None

    @property
    def primary_excel_metadata_path(self) -> Optional[str]:
        """
        Path of the project's own metadata.xlsx, the primary Level 2 source.

        None until the project has been saved -- there is nowhere beside an
        Untitled project to put it, so every data root falls back to whatever
        Metadata.xlsx sits next to its own files.
        """
        if not self.project_session.has_file:
            return None
        return os.path.join(project_folder(self.project_session.path), PROJECT_METADATA_EXCEL_NAME)

    def prepare_scan_inputs(self) -> dict:
        """Prepare session-derived scan inputs while the caller is on the GUI thread."""
        session = self.project_session
        return {
            "cache_dir": (scan_cache_folder(session.path) if session.has_file
                          else untitled_scan_cache_folder()),
            "primary_excel_path": self.primary_excel_metadata_path,
            "project_path": session.path,
            "roots": tuple(replace(root) for root in session.project.data_roots),
        }

    # ---- the data pool -------------------------------------------------

    def scan_pool_directory(self, directory_path: str, cache_dir: str,
                            primary_excel_path: Optional[str], progress_fn=None,
                            parent_excel_path=None, project_path=None, roots=()):
        """
        Reads a folder's measurement structure. Safe to call off the GUI thread.

        Returns runs, metadata schema and the folder's DirectoryIndex. `roots`
        are copies taken on the calling thread, not live project objects.

        Deliberately touches neither the project nor the pool: it only returns
        what the folder says, so the caller can run it in a QThreadPool worker
        while the window stays responsive and integrate the result afterwards
        (see integrate_scanned_directory). Logging goes to stdout rather than
        through a log hook for the same reason -- the log panel is a Qt widget
        and must not be written to from a worker thread.

        `progress_fn(done, total)`, when passed, is called as the folder's
        stale files are re-parsed one by one, so a folder of large files is not
        a single 0-to-100 jump in the ingest dialog. It only needs to be
        thread-safe -- the QtJobRunner hands in one that emits a queued signal.
        """
        file_listing = {}
        runs, schema = self.scanner.quick_scan_directory(
            directory_path,
            primary_excel_path=primary_excel_path,
            log_fn=print,
            cache_dir=cache_dir,
            progress_fn=progress_fn,
            parent_excel_path=parent_excel_path,
            file_listing=file_listing,
        )
        return runs, schema, DirectoryIndex(
            file_listing, read_root_directories(project_path, roots))

    def integrate_scanned_directory(self, directory_path: str, runs_list, schema_master: dict,
                                    only_files=None, admit_unknown: bool = False,
                                    *, index: DirectoryIndex) -> IntegrateResult:
        """
        Folds a scanned folder into the pool. Must run on the GUI thread.

        `index` is the DirectoryIndex the worker scan returned, so nothing here
        touches the disk.

        Everything here mutates the project, so it is kept apart from the scan
        above rather than being done in the worker. Returns an IntegrateResult:
        how many runs the pool actually gained (a folder already in the pool
        adds nothing and is re-scanned in place instead of duplicated), whether
        this was a folder new to the pool, and the counts the shell logs.

        `only_files` narrows a whole-folder scan to the measurements the user
        actually picked. The scan itself always covers the folder, because the
        folder cache is written per folder and reading one file out of it costs
        the same as reading all of them; what changes is which of the results
        enter the pool. Files already in the pool from this folder are kept
        regardless, so picking one file today and another next week grows the
        same folder node rather than replacing it. None means the whole folder,
        which is what an explicit "Add folder" asks for and what therefore
        overrides an earlier removal.

        `admit_unknown` is what makes a refresh useful: a measurement written
        into the folder since the last scan joins the pool, while one the user
        removed stays removed. "Unknown" is judged against the project as it
        was before this call, because registering the folder below gives every
        file an entry and would otherwise make them all look new.
        """
        if not directory_path:
            return IntegrateResult(0, False, directory_path, 0, 0)

        # A folder already in the pool keeps the spelling it was first added
        # under, so the settings, the project root and the tree all name it
        # the same way however it arrived this time.
        directory_path = self.pool_keys().get(canonical_path(directory_path), directory_path)

        # Only an explicit "Add folder" moves the last-viewed folder and the
        # startup pointer (the shell does that off is_new_folder). A background
        # re-scan of folders already in the pool (project open, folder watcher)
        # must not.
        is_new_folder = canonical_path(directory_path) not in self.pool_keys()
        session = self.project_session
        known_before = session.sources_by_path(index.root_directories)

        # Register the folder with the project as well. On an Untitled project
        # this costs nothing and is not treated as unsaved work -- the folder is
        # recovered from the setting on the next start -- but it means the
        # sources, and any metadata the user goes on to type, are already in
        # place if they later save.
        session.add_data_directory(directory_path, index=index)

        # The folder cache reports what the files say; the project restates what
        # the user decided about them. Applying the corrections here, on every
        # load, is what lets the cache stay purely derived and deletable.
        by_path = session.sources_by_path(index.root_directories)
        corrected = session.apply_unit_overrides(runs_list, by_path)

        # The reverse direction: the scan just re-read each run's Level 1/2
        # metadata, and the project keeps its own copy so the Compare/Filter
        # tab can see it without this data root being mounted.
        synced = session.sync_source_metadata(runs_list, by_path)

        key = canonical_path(directory_path)

        # A re-scan of a folder already in the pool replaces its runs rather
        # than piling a second copy of every file on top of the first. Keyed by
        # folder rather than by file so a measurement deleted since the last
        # scan disappears from the pool instead of lingering as a phantom.
        incoming = {canonical_path(run.file_path): run for run in runs_list}
        kept = [run for run in self.loaded_runs
                if canonical_path(os.path.dirname(run.file_path)) != key]
        already_here = {canonical_path(run.file_path) for run in self.loaded_runs
                        if canonical_path(os.path.dirname(run.file_path)) == key}

        if only_files is not None:
            wanted = {canonical_path(path) for path in only_files} | already_here
            if admit_unknown:
                wanted |= {path for path in incoming if path not in known_before}
                # A file the project already records as pooled but that is not
                # in the in-memory pool yet. Opening a project indexes the
                # folder first, so a measurement written into it while the
                # project was closed is no longer "unknown" by the time this
                # runs -- it was reported as new and then silently excluded,
                # and its in_pool was flipped to False for good.
                wanted |= {path for path in incoming
                           if getattr(known_before.get(path), "in_pool", False)}
            incoming = {path: run for path, run in incoming.items() if path in wanted}

        gained = len(incoming) - len(already_here)

        # A measurement the pool holds whose file is no longer on disk stays in
        # the pool, marked missing by the tree. Dropping it here was the one
        # path that made "Locate missing file..." unreachable for exactly the
        # files it exists for: the row vanished without a word, and came back
        # struck through only after the project was reopened.
        present_paths = {canonical_path(path) for path in index.file_listing}
        vanished = [run for run in self.loaded_runs
                    if canonical_path(os.path.dirname(run.file_path)) == key
                    and canonical_path(run.file_path) not in incoming
                    and canonical_path(run.file_path) not in present_paths]

        folder_runs = vanished + list(incoming.values())
        self.loaded_runs = kept + folder_runs

        # The folder is in the pool exactly as long as it contributes something
        # to it. Appending unconditionally meant a folder whose measurements
        # the user had all removed came back on the next refresh -- with no
        # runs, but with its metadata columns, and so with filter facets that
        # can never match anything. Kept in the spelling it arrived in, not the
        # canonical lower-case form used for comparisons: this list is handed
        # on to add_data_directory and shown to the user, and a folder
        # registered twice under two spellings is two data roots for one folder.
        if folder_runs:
            if key not in self.pool_keys():
                self.pool_directories.append(directory_path)
            # An empty scan (folder unmounted, files deleted) must not wipe the
            # columns the runs still standing in the tree belong to.
            if schema_master or key not in self._schema_baselines:
                self._schema_baselines[key] = dict(schema_master or {})
        else:
            self._forget_pool_directory(key)

        # Pool membership is a decision, so it is recorded in the project and
        # survives a reload -- otherwise a file taken out of the pool, or one
        # never picked out of a folder in the first place, would be back the
        # next time the project was opened. Both directions are written: a
        # scan sees every file in the folder, and the ones it did not admit
        # are as much a statement as the ones it did.
        scanned = {canonical_path(run.file_path) for run in runs_list}
        session.set_pool_membership(incoming.keys(), True, by_path)
        session.set_pool_membership(scanned - set(incoming), False, by_path)
        self._merged_schema = None

        return IntegrateResult(
            gained=max(gained, 0),
            is_new_folder=is_new_folder,
            stored_path=directory_path,
            unit_corrections=corrected,
            metadata_synced=synced,
        )

    def _forget_pool_directory(self, key: str) -> None:
        """
        Drops a folder from the pool, columns and all.

        One method rather than the pair spelled out at each call site: a folder
        that leaves pool_directories but keeps its entry in _schema_baselines
        still contributes metadata columns, so the filter panel keeps offering
        facets from a folder that is no longer in the pool and can never match
        anything. Three call sites had to remember both halves; now none do.
        """
        stored = self.pool_keys().get(key)
        if stored is not None:
            self.pool_directories.remove(stored)
        self._schema_baselines.pop(key, None)

    def pool_keys(self) -> dict:
        """
        The pool's folders, canonical form to the spelling they are stored in.

        Windows takes both separators and ignores case, so the same folder
        arrives spelled several ways; comparisons go through the canonical
        form and everything handed onward uses the original.
        """
        return {canonical_path(directory): directory for directory in self.pool_directories}

    def add_pool_directory(self, directory_path: str, only_files=None,
                           admit_unknown: bool = False) -> IntegrateResult:
        """Scans a folder and adds it to the pool, keeping what is already there."""
        if not directory_path or not os.path.exists(directory_path):
            return IntegrateResult(0, False, directory_path or "", 0, 0)
        scan_inputs = self.prepare_scan_inputs()
        runs_list, schema_master, index = self.scan_pool_directory(
            directory_path, **scan_inputs
        )
        return self.integrate_scanned_directory(
            directory_path, runs_list, schema_master, only_files, admit_unknown,
            index=index
        )

    def remove_pool_directory(self, directory_path: str) -> int:
        """
        Drops a folder's measurements from the pool.

        The folder stays registered with the project: its sources carry the
        user's metadata, unit corrections and test-setup assignments, and every
        result set already computed refers to them by id. Removing the entries
        would orphan all of that to save a few kilobytes of JSON. What goes is
        the in-memory working set and the folder's columns from the merged
        schema. Returns how many runs were dropped.
        """
        key = canonical_path(directory_path)
        stored = self.pool_keys().get(key)
        if stored is None:
            return 0

        before = len(self.loaded_runs)
        # Cleared per source path rather than per loaded run, the same way
        # reset_pool_to_directory does it: a folder can hold files the user
        # never admitted, and those carry in_pool too. Left True, the next
        # refresh of this folder would admit them back.
        by_path = self.project_session.sources_by_path()
        leaving = [path for path in by_path
                   if canonical_path(os.path.dirname(path)) == key]
        self.loaded_runs = [run for run in self.loaded_runs
                            if canonical_path(os.path.dirname(run.file_path)) != key]
        self.project_session.set_pool_membership(leaving, False, by_path)
        self._forget_pool_directory(key)
        self._merged_schema = None
        return before - len(self.loaded_runs)

    def remove_pool_runs(self, file_paths) -> int:
        """
        Drops individual measurements from the pool.

        A folder left with nothing in it goes too, along with its columns: a
        schema still offering fields from a folder the user has emptied would
        put facets in the filter panel that can never match anything.
        """
        targets = {canonical_path(path) for path in file_paths}
        if not targets:
            return 0

        before = len(self.loaded_runs)
        self.loaded_runs = [run for run in self.loaded_runs
                            if canonical_path(run.file_path) not in targets]
        self.project_session.set_pool_membership(
            targets, False, self.project_session.sources_by_path())

        still_used = {canonical_path(os.path.dirname(run.file_path)) for run in self.loaded_runs}
        for key in list(self.pool_keys()):
            if key in still_used:
                continue
            self._forget_pool_directory(key)

        self._merged_schema = None
        return before - len(self.loaded_runs)

    def clear_pool(self) -> None:
        self.loaded_runs = []
        self.pool_directories = []
        self._schema_baselines = {}
        self._merged_schema = None

    def restore_pool_from_project(self) -> List[str]:
        """
        Fills the pool from what the project already stored, touching no file.

        What an opened project shows before the background scan has run. The
        entries are the same shape a scan produces, so the tree, the filters
        and the drag-and-drop router cannot tell which they are looking at --
        the scan simply replaces them folder by folder as it lands. Returns the
        folders recovered, so the shell can fall back active_directory onto one
        of them when the browser has nothing to point at.
        """
        from io_modules.metadata_schema import generate_baseline_schema_master

        self.clear_pool()
        session = self.project_session
        for directory, runs in runs_by_directory(session.project, session.path).items():
            self.pool_directories.append(directory)
            self._schema_baselines[canonical_path(directory)] = generate_baseline_schema_master(runs)
            self.loaded_runs.extend(runs)

        session.apply_unit_overrides(self.loaded_runs, session.sources_by_path())
        self._merged_schema = None
        return list(self.pool_directories)

    def schema(self) -> MergedSchema:
        """
        Return the merged metadata schema and detected conflicts.

        Lazily derived on first access and cached until the pool's membership,
        baselines, or project schema change.
        """
        if self._merged_schema is None:
            self._merged_schema = self._derive_merged_schema()
        return self._merged_schema

    def _derive_merged_schema(self) -> MergedSchema:
        """
        Re-derives the merged schema from every folder currently in the pool.

        Done wholesale rather than incrementally because removing a folder has
        to take its columns with it, which an accumulating merge cannot do.
        """
        baseline = merge_schema_baselines(self._schema_baselines)
        master = merge_schema_master(
            baseline, self.project_session.project.metadata_schema
        )

        value_types = {}
        for key in self._schema_baselines:
            runs_here = [run for run in self.loaded_runs
                         if canonical_path(os.path.dirname(run.file_path)) == key]
            value_types[key] = collect_metadata_value_types(runs_here)

        # Conflicts are keyed by folder and the dialog shows that key's basename
        # to the user, so the canonical (lower-cased) form would name the folder
        # back at them in a spelling it does not have on disk.
        spellings = self.pool_keys()
        conflicts = detect_schema_conflicts(
            {spellings.get(key, key): base for key, base in self._schema_baselines.items()},
            {spellings.get(key, key): types for key, types in value_types.items()},
        )

        # The merged schema is the first point where a field's kind is settled
        # (inference unioned across folders, then the user's overrides on top),
        # so typed metadata is parsed from here -- see
        # ProjectSession.sync_parsed_metadata.
        self.project_session.sync_parsed_metadata(master)
        return MergedSchema(master=master, conflicts=conflicts, baseline=baseline)

    def update_project_schema(self, finalized_schema: dict) -> None:
        """
        Update the project's metadata schema and invalidate the merged schema cache.
        """
        self.project_session.set_metadata_schema(finalized_schema)
        self._merged_schema = None

    def reset_pool_to_directory(self, directory_path: str) -> bool:
        """
        Empties the pool in preparation for one folder becoming the whole of it.

        Deliberately stops short of reading that folder: the scan belongs on a
        background worker (gui.handlers.data_pool), and
        doing it here meant the two callers that mean "start over from this
        folder" -- startup restore and spawning a second window -- parsed every
        UNV header on the GUI thread with nothing on screen. Returns whether
        the path is usable, so the caller knows whether to queue the scan.
        """
        if not directory_path or not os.path.exists(directory_path):
            return False

        # "Start over" is transactional: every folder being dropped must also
        # lose its recorded pool membership now, in the same step. Otherwise the
        # project keeps saying those files are pooled until the new folder's scan
        # happens to overwrite it, and a save in between -- or the next project
        # open -- would drag them all back in. Cleared per source path rather
        # than per loaded run: a folder can hold files the user never admitted,
        # and those carry in_pool too.
        dropping = set(self.pool_keys())
        by_path = self.project_session.sources_by_path()
        stale = [path for path in by_path
                 if canonical_path(os.path.dirname(path)) in dropping]
        self.project_session.set_pool_membership(stale, False, by_path)
        self.clear_pool()
        return True

    def has_data(self) -> bool:
        return len(self.loaded_runs) > 0
