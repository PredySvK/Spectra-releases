# =====================================================================
# FILE: session/project.py
# =====================================================================
"""
The open project, as the running application sees it.

The application always has a project. On startup it is an unsaved "Untitled"
one, exactly like a spreadsheet opening on Book1: real enough to browse data,
plot it and tune an FFT against, but with no file behind it yet. A path is
only demanded when the user does something that cannot be reconstructed by
re-scanning a folder -- editing metadata, correcting a unit, or computing a
result set.

Lives in session/ because it answers "what is open and how does it change over
time", not "how is it read from or written to disk" -- that part is delegated
to io_modules/project_store. It stays free of Qt so the lifecycle rules below
can be tested without starting a GUI; the file dialog is injected as a
callback instead.

All internal documentation strings and variable labels are standardly written
in English.
"""

import os
from collections import Counter
from dataclasses import replace
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from core.axis_projections import X_AXIS_NATIVE, X_AXIS_UNITS
from core.measurement_selection import MeasurementSelection
from core.models import ChannelIdentity
from core.project_model import DataRoot, NVHProject, SourceEntry
from core.workflow_graph import Workflow
from selection.measurement_selection import WHOLE_POOL_SELECTION_NAME
from io_modules.project_store import (
    DirectoryIndex,
    IndexReport,
    adopt_untitled_scan_caches,
    build_sources_by_path,
    index_all_roots,
    index_root_listing,
    load_project,
    reanchor_roots,
    read_root_directories,
    reconcile_root,
    resolve_root,
    resolve_root_in,
    save_project,
)
from core.units import determine_channel_type
from io_modules.measurement_files import canonical_path, file_exists, file_stamp
from session.result_sets import ResultSetsMixin

UNTITLED_NAME = "Untitled"

# ui_state key the global X axis unit is stored under (issue #459).
X_AXIS_UNIT_KEY = "x_axis_unit"

# Supplied by the GUI when a path is needed; returns a chosen path or None if
# the user cancelled. Injected so this module never imports a file dialog.
PathProvider = Callable[[], Optional[str]]

# Injected by the GUI window to run scan-cache adoption asynchronously (via
# QtJobRunner) rather than copying files synchronously on the GUI thread.
CacheAdopter = Callable[[str, Sequence[DataRoot]], None]


def correct_run_channel(run, channel_label: str, unit: str) -> bool:
    """
    The channel a stored unit correction belongs to, by label or by name.

    Corrections are keyed by whatever available_channels was keyed by when
    the user made them, and that is not one thing: a scanned run is keyed
    by the reader's bookkeeping label ("Set #5: Acc_X"), while a run
    rebuilt from the project snapshot (session.data_pool) is keyed
    by the channel's plain name. A correction made against one form was
    silently never re-applied to the other -- it stayed in the project
    looking saved while the unit reverted on every load. The same fallback
    also survives a re-measured file whose dataset numbering shifted --
    but only when the name is unique in the run; two same-named channels
    must not both claim a correction meant for just one of them (#423).
    """
    from selection.channel_identity import resolve_stripped_override

    channels = getattr(run, "available_channels", {})
    target = resolve_stripped_override(
        channel_label,
        ((label, getattr(meta, "name", "")) for label, meta in channels.items()),
    )
    if target is None:
        return False
    meta = channels[target]
    meta.unit = unit
    meta.type = determine_channel_type(unit, meta.name)
    return True


def correct_entry_channel(entry: SourceEntry, channel_label: str, unit: str) -> bool:
    """Same correction, applied to the entry's channel snapshot (`entry.channels`)."""
    from selection.channel_identity import resolve_stripped_override, strip_reader_label_prefix

    target = resolve_stripped_override(
        channel_label,
        ((key, facts.get("name", "")) for key, facts in entry.channels.items()),
    )
    if target is None:
        return False
    facts = entry.channels[target]
    facts["unit"] = unit
    ch_name = facts.get("name") or strip_reader_label_prefix(channel_label)
    facts["type"] = determine_channel_type(unit, ch_name)
    return True


class ProjectSession(ResultSetsMixin):
    """
    Holds the open project, where it is stored, and whether it needs saving.

    The unsaved-changes rule is the subtle part, because getting it wrong makes
    the application either nag or lose work:

      - Browsing, plotting and changing FFT settings never touch the project,
        so they can never mark it unsaved.
      - Indexing a folder marks an already-saved project as changed, because
        its stored source list is now behind. On an Untitled project it does
        not, because there is no stored list to be behind and the folder is
        recovered from the last-directory setting on the next start. This is
        what lets the user open the app, look at a folder and leave without
        being asked to save anything.
      - Metadata edits, unit corrections and result sets always mark the
        project as changed, Untitled or not. These exist nowhere else, so
        losing them silently is not acceptable.
    """

    def __init__(self, cache_adopter: Optional[CacheAdopter] = None):
        self._project = NVHProject(name=UNTITLED_NAME)
        self._path: Optional[str] = None
        self._dirty = False
        self._channel_pairs: List[Tuple[ChannelIdentity, ChannelIdentity]] = []
        self._cache_adopter = cache_adopter

    # ---- state --------------------------------------------------------

    @property
    def project(self) -> NVHProject:
        return self._project

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def has_file(self) -> bool:
        """Whether the project has ever been saved."""
        return self._path is not None

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def set_cache_adopter(self, adopter: Optional[CacheAdopter]) -> None:
        """
        Plugs in a background or custom strategy for adopting untitled scan caches.
        The GUI uses this to offload adoption onto QtJobRunner instead of copying
        files synchronously on the GUI thread during save_as (audit 02, S6/6.3).
        """
        self._cache_adopter = adopter

    @property
    def display_name(self) -> str:
        """Window-title form: the project name, marked when unsaved."""
        base = self._project.name or UNTITLED_NAME
        return f"{base}*" if self._dirty else base

    def mark_dirty(self) -> None:
        """
        Records a change that exists nowhere but in the project.

        Called by metadata editing, unit corrections and result-set creation.
        Applies to an Untitled project too, so that work is not lost on close.
        """
        self._dirty = True

    @property
    def x_axis_unit(self) -> str:
        """The project's global X axis unit (issue #459), one of
        core.axis_projections.X_AXIS_UNITS; native when unset or unknown."""
        value = self._project.ui_state.get(X_AXIS_UNIT_KEY, X_AXIS_NATIVE)
        return value if value in X_AXIS_UNITS else X_AXIS_NATIVE

    def set_x_axis_unit(self, x_axis_unit: str) -> None:
        """
        Records the global X axis unit with the project. Cosmetic, like the
        rest of ui_state: it asks to be saved only on a project that has a
        file, so switching it on an Untitled one never prompts.
        """
        if x_axis_unit not in X_AXIS_UNITS:
            raise ValueError(f"Unknown X axis unit: {x_axis_unit!r}")
        if x_axis_unit == self.x_axis_unit:
            return
        self._project.ui_state[X_AXIS_UNIT_KEY] = x_axis_unit
        if self.has_file:
            self._dirty = True

    def _mark_structural_change(self) -> None:
        """
        Records a change to the source list.

        Only meaningful once the project has a file: until then the folder is
        re-discovered from settings on the next start, so there is nothing to
        preserve and nothing to prompt about.
        """
        if self.has_file:
            self._dirty = True

    # ---- lifecycle ----------------------------------------------------

    def new_project(self, name: str = UNTITLED_NAME) -> NVHProject:
        self._project = NVHProject(name=name)
        self._channel_pairs = []
        self._path = None
        self._dirty = False
        return self._project

    def load_project_file(self, project_path: str) -> None:
        """
        Loads a project's stored state without reading its data folders.

        The GUI opens a project this way and then re-indexes the folders in the
        background (ProjectDocumentHandler.open_project), which is what
        keeps a project whose measurements sit on a slow or unmounted drive from
        freezing the window on open. open_project() below keeps doing both, for
        headless callers and tests that need the project reconciled with disk by
        the time the call returns.
        """
        self._project = load_project(project_path)
        self._channel_pairs = []
        self._path = os.path.abspath(project_path)
        self._dirty = False

    def open_project(self, project_path: str) -> Dict[str, IndexReport]:
        """
        Loads a project and brings its source list in line with disk.

        Re-indexing on open is what keeps the project honest about files that
        were added, edited, renamed or removed while it was closed. Any of
        those leaves the stored list behind, so the project is marked as
        needing a save; an untouched folder leaves it clean.
        """
        self.load_project_file(project_path)

        reports = index_all_roots(self._project, self._path)
        if any(report.changed for report in reports.values()):
            self._dirty = True
        return reports

    def save(self) -> str:
        """Saves to the existing path. Use save_as() when there is none yet."""
        if self._path is None:
            raise ValueError("Project has never been saved; a path is required.")
        save_project(self._project, self._path)
        self._dirty = False
        return self._path

    def save_edit(self, edit: Callable[[], None]) -> bool:
        """
        Applies an edit worth keeping and saves it -- but only when it is the
        sole unsaved change.

        A save writes the whole project, so saving over other unsaved edits
        would commit ones the user may still mean to discard at close, and
        clear the flag that would have asked (#337, #424). In that case the
        edit just joins them and goes to disk with the user's next save.

        Returns True when the project was written. A failed save raises
        OSError or ValueError with the edit still applied and marked unsaved.
        """
        had_other_unsaved_edits = self._dirty
        edit()
        self.mark_dirty()
        if had_other_unsaved_edits:
            return False
        self.save()
        return True

    def save_as(self, project_path: str) -> str:
        """
        Saves to a new location, re-expressing the data roots against it.

        The re-anchoring is not cosmetic. Roots added before the project had a
        file carry no relative path at all, and a Save As into a different
        folder invalidates the ones that do -- in both cases the project would
        reopen unable to find any of its measurements.
        """
        was_untitled = self._path is None
        new_path = os.path.abspath(project_path)
        old_path = self._path
        old_name = self._project.name
        root_snapshot = [
            (root, root.relpath, root.absolute_fallback)
            for root in self._project.data_roots
        ]

        try:
            reanchor_roots(self._project, self._path, new_path)
            self._path = new_path
            if self._project.name == UNTITLED_NAME:
                self._project.name = os.path.splitext(os.path.basename(new_path))[0]
            save_project(self._project, new_path)
        except Exception:
            self._path = old_path
            self._project.name = old_name
            for root, relpath, absolute_fallback in root_snapshot:
                root.relpath = relpath
                root.absolute_fallback = absolute_fallback
            raise

        if was_untitled:
            if self._cache_adopter is not None:
                self._cache_adopter(new_path, list(self._project.data_roots))
            else:
                self.adopt_untitled_scan_caches()
        self._dirty = False
        return new_path

    def adopt_untitled_scan_caches(self) -> List[str]:
        """
        Moves scan caches built while the project was Untitled into its own
        cache/scan/ folder, so the first rescan after a save is a cache hit
        rather than a full re-parse (ADR §1.22).

        Only the caches for this project's data roots are taken: the temp area
        is shared and may hold caches for folders that belong to a different
        session.
        """
        if not self._path:
            return []
        return adopt_untitled_scan_caches(self._path, self._project.data_roots)

    _adopt_untitled_scan_caches = adopt_untitled_scan_caches

    def ensure_saved(self, path_provider: PathProvider) -> bool:
        """
        Guarantees the project has a file, asking for one if it does not.

        The gate in front of anything that needs somewhere to put results or
        that records a decision worth keeping -- the metadata editor and the
        batch processor both call this first. Returns False when the user
        declines to choose a path, in which case the caller must not proceed.

        The dialog arrives as a callback so this module stays free of Qt.
        """
        if self.has_file:
            return True

        chosen = path_provider()
        if not chosen:
            return False

        self.save_as(chosen)
        return True

    # ---- data folders -------------------------------------------------

    def add_data_directory(self, directory: str, label: str = "",
                           *, index: DirectoryIndex) -> IndexReport:
        """
        Registers a folder with the project and indexes what is in it.

        Works on an Untitled project, which is the ordinary path: open the
        application, point it at a folder, start looking. Nothing is written
        to disk here.

        `index` is the folder as a worker read it, so nothing here touches
        the disk.
        """
        root, reconciled = reconcile_root(
            self._project, self._path, directory, label,
            root_directories=index.root_directories)
        report = index_root_listing(self._project, root, directory, index.file_listing)
        if reconciled or report.changed:
            self._mark_structural_change()
        return report

    def resolved_directories(self) -> List[str]:
        """Every data folder that currently exists, in project order."""
        found = (resolve_root(self._path, root) for root in self._project.data_roots)
        return [directory for directory in found if directory]

    # ---- metadata -----------------------------------------------------

    def set_metadata(self, source_id: str, field: str, value: str) -> bool:
        """Edits run-level metadata. Never touches the measurement file itself."""
        entry = self._project.source_by_id(source_id)
        if entry is None:
            return False
        entry.metadata[field] = value
        self.mark_dirty()
        return True

    def set_unit_override(self, source_id: str, channel_label: str, unit: str) -> bool:
        """
        Corrects a channel whose file-declared unit is wrong.

        The correction lives in the project so the raw measurement stays as it
        was recorded, and so it travels with the project to whoever opens it.
        """
        entry = self._project.source_by_id(source_id)
        if entry is None:
            return False
        entry.unit_overrides[channel_label] = unit

        # Keep entry.channels in sync so background batch workers (run_from_entry)
        # and selection resolution (_channels_for) see the corrected unit and type
        # immediately without needing a re-scan.
        correct_entry_channel(entry, channel_label, unit)

        self.mark_dirty()
        return True


    def set_metadata_schema(self, schema: Dict) -> None:
        """
        Stores which metadata fields are shown and what they are called.

        Kept in the project rather than the folder cache: the cache is derived
        from the measurement files and may be deleted to force a re-scan, which
        would take the user's labels and visibility choices with it.
        """
        self._project.metadata_schema = dict(schema)
        self.mark_dirty()

    @property
    def channel_pairs(self) -> List[Tuple[ChannelIdentity, ChannelIdentity]]:
        """Channel identity pairs read from channel_pairing.xlsx (#511); not part of the project file."""
        return list(self._channel_pairs)

    def set_channel_pairs(self, channel_pairs) -> None:
        self._channel_pairs = [tuple(pair) for pair in channel_pairs]

    # ---- applying project decisions to loaded data --------------------

    def record_unit_override(self, run, channel_label: str, unit: str) -> bool:
        """
        Remembers a unit correction against the measurement the channel is in.

        Takes the loaded run rather than a source id because that is what the
        explorer has in hand. Returns False when the file is not part of the
        project, which is the case while no data folder has been registered.
        """
        entry = self.source_for_path(getattr(run, "file_path", ""))
        if entry is None:
            return False
        return self.set_unit_override(entry.id, channel_label, unit)

    def apply_unit_overrides(self, runs, by_path: Dict[str, SourceEntry]) -> int:
        """
        Lays the project's unit corrections over freshly loaded runs.

        This is what keeps the correction out of the measurement file and out
        of the folder cache: both keep saying whatever was originally recorded,
        and the project restates it on every load. Deleting the cache costs a
        re-scan and nothing else.

        `by_path` is a map from sources_by_path(). Returns how many channels
        were corrected.
        """
        corrected = 0
        for run in runs:
            entry = self.entry_for_run(run, by_path)
            if entry is None or not entry.unit_overrides:
                continue

            for channel_label, unit in entry.unit_overrides.items():
                # A channel gone from the file keeps its correction in case it
                # comes back rather than being quietly dropped.
                if correct_run_channel(run, channel_label, unit):
                    corrected += 1

        return corrected

    def sync_source_metadata(self, runs, by_path: Dict[str, SourceEntry]) -> int:
        """
        Writes everything a scan just discovered about each run into its
        SourceEntry: the linked Level 2 Excel row, the file's own Level 1
        facts (id1..id5 today, whatever a future reader adds besides), and a
        snapshot of every channel's metadata (label, unit, sampling rate...).

        Runs the opposite direction from apply_unit_overrides: the scan is the
        source of truth here, and the project is what gets updated, so the
        comparator's filters can see a file's metadata without its data root
        being mounted. Only entries that actually changed are touched, so
        re-scanning an untouched folder never marks the project dirty on its
        own. `by_path` is a map from sources_by_path().
        """
        synced = 0
        for run in runs:
            entry = self.entry_for_run(run, by_path)
            if entry is None:
                continue

            excel_metadata = dict(getattr(run, "metadata", None) or {})
            file_metadata = run.file_level_facts() if hasattr(run, "file_level_facts") else {}

            # Keyed by the channel's name rather than the dict's own key, so
            # the snapshot matches what cache lookup and channel selection key
            # off of elsewhere. Two channels sharing a name (an ASC export with
            # two "Mic" columns) are each keyed by the run's own unique label
            # instead: keyed by name, the second silently replaced the first
            # (#320).
            snapshot = [
                (label, channel_meta.to_dict())
                for label, channel_meta in getattr(run, "available_channels", {}).items()
            ]
            name_counts = Counter(facts["name"] for _, facts in snapshot)
            channels = {
                (label if name_counts[facts["name"]] > 1 else facts["name"]): facts
                for label, facts in snapshot
            }

            changed = (
                excel_metadata != entry.excel_metadata
                or file_metadata != entry.file_metadata
                or channels != entry.channels
            )
            if changed:
                entry.excel_metadata = excel_metadata
                entry.file_metadata = file_metadata
                entry.channels = channels
                synced += 1

        if synced:
            # A folder re-scan syncing derived metadata is a structural change,
            # not a user decision -- on an Untitled project (no has_file guard
            # in mark_dirty()) it must not manufacture unsaved-changes state
            # out of the very first browse.
            self._mark_structural_change()
        return synced

    def sync_parsed_metadata(self, schema: Dict) -> int:
        """
        Rebuilds every source's typed `parsed_metadata` from its raw Level 1/2
        dicts and the given (merged) schema.

        Kept apart from sync_source_metadata because it needs the schema after
        it has been merged across folders and reconciled with the user's kind
        overrides -- which happens later, in DataPool.schema(), than the
        per-folder scan that fills the raw dicts. Re-run whenever either the
        raw metadata or the schema's kinds change. Returns how many entries
        actually changed.

        Never marks the project dirty: parsed_metadata is purely derived from
        excel_metadata/file_metadata plus the schema (see its field comment in
        core.project_model.SourceEntry) and is rebuilt identically on every
        load, so a stale stored copy -- e.g. a schema field dropped in a later
        app version -- would otherwise flag the project unsaved forever with
        nothing the user could actually save away. The one caller that changes
        the schema on purpose (ProjectDocumentHandler.open_metadata_editor)
        already marks dirty itself via set_metadata_schema before calling this.
        """
        from selection.source_facets import channel_summary_value
        from io_modules.metadata_schema import parsed_metadata_for_row

        changed = 0
        for entry in self._project.sources:
            # Channel-layer fields (BUGS.md N1/N2) live in entry.channels, not
            # file_metadata/excel_metadata -- fold in one representative value
            # per field the same way source_facets reads it for a facet.
            channel_raw = {
                key: channel_summary_value(entry, key)
                for key, config in (schema or {}).items()
                if config.get("layer") == "channel"
            }
            raw_by_key = {**channel_raw, **entry.file_metadata, **entry.excel_metadata}
            parsed = parsed_metadata_for_row(raw_by_key, schema or {})
            if parsed != entry.parsed_metadata:
                entry.parsed_metadata = parsed
                changed += 1

        return changed

    # ---- measurement selections (ADR §1.12) -----------------------------

    def selections(self) -> List[MeasurementSelection]:
        """Every named selection stored in this project, in stored order."""
        return list(self._project.selections)

    def find_selection(self, name: str) -> Optional[MeasurementSelection]:
        return self._project.selection_by_name(name)

    def save_selection(self, selection: MeasurementSelection) -> MeasurementSelection:
        """
        Stores a named selection, replacing one of the same name.

        A project decision, so it marks the project dirty -- unlike the Compare
        filter state, which is cosmetic and lives in ui_state precisely so that
        merely looking around does not make a project unsaved.
        """
        if not selection.name:
            raise ValueError("A stored selection needs a name -- it is how a recipe refers to it.")
        if selection.name == WHOLE_POOL_SELECTION_NAME:
            raise ValueError(
                f"'{WHOLE_POOL_SELECTION_NAME}' is reserved for the whole Data Pool -- "
                "pick another name for a stored selection."
            )
        stored = self._project.put_selection(selection)
        self.mark_dirty()
        return stored

    def remove_selection(self, name: str) -> bool:
        removed = self._project.remove_selection(name)
        if removed:
            self.mark_dirty()
        return removed

    def workflows_using_selection(self, name: str) -> List[str]:
        """Names of the workflows whose Input node refers to selection `name`."""
        return [workflow.name for workflow in self._project.workflows
                if any(node.is_input and node.input and node.input.selection_name == name
                       for node in workflow.nodes)]

    def rename_selection(self, old_name: str, new_name: str) -> None:
        """
        Renames a selection in place and, in the same step, the `selection_name`
        of every Input node that refers to it -- a workflow names its selection
        by string, so renaming only the selection would orphan them (#463).
        """
        selection = self._project.selection_by_name(old_name)
        if selection is None:
            raise KeyError(old_name)
        if not new_name:
            raise ValueError("A stored selection needs a name -- it is how a recipe refers to it.")
        if new_name == WHOLE_POOL_SELECTION_NAME:
            raise ValueError(f"'{WHOLE_POOL_SELECTION_NAME}' is reserved for the whole Data Pool.")
        if new_name != old_name and self._project.selection_by_name(new_name) is not None:
            raise ValueError(f"A selection named '{new_name}' already exists.")
        index = self._project.selections.index(selection)
        self._project.selections[index] = replace(selection, name=new_name)
        for workflow in list(self._project.workflows):
            nodes = tuple(
                replace(node, input=replace(node.input, selection_name=new_name))
                if node.is_input and node.input and node.input.selection_name == old_name else node
                for node in workflow.nodes)
            if nodes != workflow.nodes:
                self._project.put_workflow(replace(workflow, nodes=nodes))
        self.mark_dirty()

    # ---- block-diagram workflows (ADR §1.6) ----------------------------

    def workflows(self) -> List[Workflow]:
        """Every workflow stored in this project, in stored order."""
        return list(self._project.workflows)

    def find_workflow(self, name: str) -> Optional[Workflow]:
        return self._project.workflow_by_name(name)

    def save_workflow(self, workflow: Workflow) -> Workflow:
        """
        Stores a named workflow, replacing one of the same name.

        A project decision -- it marks the project dirty -- exactly like
        save_selection, and for the same reason: it is analysis intent the user
        authored, not a view they merely scrolled to.
        """
        if not workflow.name:
            raise ValueError("A stored workflow needs a name -- it is how a run refers to it.")
        stored = self._project.put_workflow(workflow)
        self.mark_dirty()
        return stored

    def remove_workflow(self, name: str) -> bool:
        removed = self._project.remove_workflow(name)
        if removed:
            self.mark_dirty()
        return removed

    @staticmethod
    def entry_for_run(run, by_path: Dict[str, SourceEntry]) -> Optional[SourceEntry]:
        """Looks a run up in a map from sources_by_path()."""
        file_path = getattr(run, "file_path", "")
        if not file_path:
            return None
        return by_path.get(canonical_path(file_path))

    def sources_by_path(self, root_directories: Optional[Mapping[str, Optional[str]]] = None,
                        ) -> Dict[str, SourceEntry]:
        """
        Every source the project can currently locate, keyed by its path on
        this machine in the form source_for_path() compares against.

        Built once and reused by anything that has to answer "which entry is
        this run?" for a whole pool at a time. Doing it with source_for_path()
        per run walks every root and every source again for each one, which a
        single folder hid but a pool of several hundred files does not.

        The sources are bucketed by root_id once rather than re-scanned for
        every root: this method is called four or five times per ingested
        folder, and the nested walk was O(roots x sources) each time.

        `root_directories` is a snapshot from read_root_directories(), for a
        caller that must not touch the disk; without one the roots are
        resolved here.
        """
        # ponytail: the argument-less call is the one synchronous disk read left
        # on the GUI thread -- GUI readers (filter routing, result content, data
        # pool panel) and the pool's remove/reset/restore steps; move them onto
        # a worker snapshot if a slow share makes them stall.
        if root_directories is None:
            root_directories = read_root_directories(self._path, self._project.data_roots)
        return build_sources_by_path(self._project.data_roots, self._project.sources,
                                     root_directories)

    def source_for_path(self, absolute_path: str) -> Optional[SourceEntry]:
        """Finds the project's entry for a file on disk, or None if unknown."""
        if not absolute_path:
            return None
        target = canonical_path(absolute_path)

        for root in self._project.data_roots:
            directory = resolve_root(self._path, root)
            if directory is None:
                continue
            for entry in self._project.sources:
                if entry.root_id != root.id:
                    continue
                candidate = os.path.normcase(os.path.join(directory, entry.relpath))
                if candidate == target:
                    return entry
        return None

    def relocate_source(self, source_id: str, new_absolute_path: str) -> bool:
        """
        Points an entry at a file that has moved, keeping everything attached to it.

        A project carries relative and absolute paths so it survives being
        copied between machines, but neither helps when the data itself was
        moved or renamed on the far side. Rebuilding the entry from scratch
        would be easy and wrong: its id is what every computed result set
        refers to, and its metadata, unit corrections and test setup exist
        nowhere else. So the entry stays and only its location changes.

        A file in a folder the project does not know yet brings a new data
        root with it. Relocating onto a file the project already has an entry
        for is refused -- two entries for one measurement would give it two
        sets of metadata and two histories.
        """
        entry = self._project.source_by_id(source_id)
        if entry is None or not new_absolute_path:
            return False

        absolute = os.path.abspath(new_absolute_path)
        if not file_exists(absolute):
            return False

        root_directories = read_root_directories(self._path, self._project.data_roots)
        existing = self.sources_by_path(root_directories).get(canonical_path(absolute))
        if existing is not None and existing.id != entry.id:
            return False

        directory = os.path.dirname(absolute)
        root, _ = reconcile_root(
            self._project, self._path, directory,
            root_directories=root_directories)
        if self._project.source_by_id(source_id) is not entry:
            # Finding the root folded a duplicate of the target folder away,
            # and this entry went with it into the one kept for the file.
            self.mark_dirty()
            return False

        stamp = file_stamp(absolute)
        entry.root_id = root.id
        entry.relpath = os.path.relpath(absolute, directory)
        if stamp is not None:
            entry.size_bytes = stamp["size"]
            entry.mtime_ns = stamp["mtime_ns"]
        entry.in_pool = True

        self.mark_dirty()
        return True

    def set_pool_membership(self, paths, in_pool: bool,
                            by_path: Dict[str, SourceEntry]) -> int:
        """
        Records which measurements are in the Data Pool.

        Takes paths rather than ids because that is what the pool deals in --
        it holds runs read off disk, not project entries. Returns how many
        entries actually changed, so a re-scan that admits the same files it
        admitted last time does not mark the project dirty. `by_path` is a map
        from sources_by_path().
        """
        changed = 0
        for path in paths:
            entry = by_path.get(canonical_path(path))
            if entry is None or entry.in_pool == in_pool:
                continue
            entry.in_pool = in_pool
            changed += 1

        if changed:
            self._mark_structural_change()
        return changed

    def set_setup_label(self, source_id: str, setup_label: str) -> bool:
        """
        Files a measurement under a test setup -- the top level of the Data Pool.

        A grouping the user invents, so it is recorded here rather than derived
        from the folder layout, and it marks the project dirty like any other
        decision that exists nowhere else.
        """
        entry = self._project.source_by_id(source_id)
        if entry is None:
            return False
        if entry.setup_label == setup_label:
            return True
        entry.setup_label = setup_label
        self.mark_dirty()
        return True

    def find_cached_result(self, absolute_path: str, channel_name: str, kind: str,
                           live_params: Dict, wanted_block_params: Optional[List[Dict]] = None,
                           channel_index: Optional[int] = None):
        """
        Answers "is this result already on disk?" for any block kind: looks for
        an already-saved result set of `kind` that can serve `channel_name` at
        `live_params` without recomputing it. Returns a cache_lookup.CachedResult
        (stored blocks plus the set they came from) or None on a miss (unknown
        source, no saved result set with matching settings, or a requested block
        not present).

        See io_modules.result_cache.cache_lookup for what "matching" means.
        `channel_index` (the channel's ChannelMetadata.index) tells two
        same-named channels of one file apart; every caller that has the
        channel's metadata in hand should pass it.
        """
        entry = self.source_for_path(absolute_path)
        if entry is None:
            return None

        from io_modules.result_cache.cache_lookup import find_cached_result as _lookup
        return _lookup(self._project, self._path, entry, channel_name, kind,
                       live_params, wanted_block_params,
                       write_index=True, channel_index=channel_index)

    def find_cached_result_background(self, absolute_path: str, channel_name: str, kind: str,
                                     live_params: Dict,
                                     wanted_block_params: Optional[List[Dict]] = None,
                                     channel_index: Optional[int] = None):
        """
        `find_cached_result` for a worker thread (ADR §1.54): the lookup -- which
        opens HDF5 shards and reads arrays out of them -- runs on the background
        thread rather than the GUI thread. Unlike `find_cached_result` there is
        no `write_index` knob: a worker never persists `cache/index.json`.
        """
        entry = self.source_for_path(absolute_path)
        if entry is None:
            return None

        from io_modules.result_cache.cache_lookup import find_cached_result_background as _lookup
        return _lookup(self._project, self._path, entry, channel_name, kind,
                       live_params, wanted_block_params, channel_index=channel_index)

    def find_cached_block_background(self, absolute_path: str, channel_name: str, kind: str,
                                     live_params: Dict,
                                     wanted_block_params: Optional[List[Dict]] = None,
                                     channel_index: Optional[int] = None):
        entry = self.source_for_path(absolute_path)
        if entry is None:
            return None

        from io_modules.result_cache.cache_lookup import find_cached_block_background as _lookup
        return _lookup(self._project, self._path, entry, channel_name, kind,
                       live_params, wanted_block_params, channel_index=channel_index)


# ---- test setup assignment (gui/file_explorer/actions/assign_test_setup.py) --

def apply_setup_label(session: ProjectSession, file_paths, label: str):
    """Records a test setup label against each file's project entry."""
    by_path = session.sources_by_path()

    assigned = 0
    unknown = 0
    for path in file_paths:
        entry = by_path.get(canonical_path(path))
        if entry is None:
            unknown += 1
            continue
        if session.set_setup_label(entry.id, label):
            assigned += 1

    return assigned, unknown


# ---- unit corrections (gui/file_explorer/actions/edit_unit.py) --------------

def channel_label_for(run_index, channel_meta) -> str:
    """
    The key a channel is filed under in its run.

    Corrections are stored against this label rather than the display name,
    because that is what apply_unit_overrides looks the channel up by when the
    project is reopened.
    """
    for label, meta in run_index.available_channels.items():
        if meta is channel_meta:
            return label
    return channel_meta.name


def apply_unit_override(session: ProjectSession, run_index, channel_meta, label: str, unit: str) -> bool:
    """Updates the live channel and records the decision in the project."""
    channel_meta.unit = unit
    channel_meta.type = determine_channel_type(unit, channel_meta.name)
    return session.record_unit_override(run_index, label, unit)
