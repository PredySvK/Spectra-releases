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
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from core.axis_projections import X_AXIS_NATIVE, X_AXIS_UNITS
from core.measurement_selection import MeasurementSelection
from core.models import ChannelIdentity
from core.project_model import DataRoot, NVHProject, SourceEntry, is_channel_layer
from core.source_amplitude import VALID_SOURCE_AMPLITUDES
from core.workflow_graph import Workflow
from selection.measurement_selection import WHOLE_POOL_SELECTION_NAME
from io_modules.project_store import (
    DirectoryIndex,
    IndexReport,
    index_root_listing,
    load_project,
    reanchor_roots,
    read_root_directories,
    reconcile_root,
    resolve_root,
    resolve_root_in,
    save_project,
    tab_cache_folder,
)
from core.import_template import ImportTemplate
from io_modules.import_template import (
    install_project_templates, resolve_installed_template, resolve_installed_templates,
)
from io_modules.tab_cache import remove_unreferenced_tab_cache_files
from .tab_cache import build_referenced_tab_cache_names
from core.units import determine_channel_type
from io_modules.measurement_files import canonical_path, file_exists, file_stamp
from session.project_folder import ProjectFolderMixin, ProjectFolderCopy
from session.result_sets import ResultSetsMixin
from session.source_location import SourceLocation, build_source_location

UNTITLED_NAME = "Untitled"

# view_state keys (core.project_model.NVHProject.view_state). The global X axis
# unit (issue #459); the Filter panel's switches, Global values and active card
# (ticket #178); which schema conflicts the user has already been shown.
X_AXIS_UNIT_KEY = "x_axis_unit"
FILTER_STATE_KEY = "compare_filters"
# Kept in view_state rather than beside the field's own settings in
# metadata_schema: the metadata editor rewrites that dict wholesale from what it
# was given, which would drop an extra key it knows nothing about and make the
# conflict dialog reappear after every visit to the editor.
ACKNOWLEDGED_KEY = "acknowledged_schema_conflicts"

# Supplied by the GUI when a path is needed; returns a chosen path or None if
# the user cancelled. Injected so this module never imports a file dialog.
PathProvider = Callable[[], Optional[str]]

# Injected by the GUI window to run scan-cache adoption asynchronously (via
# QtJobRunner) rather than copying files synchronously on the GUI thread.
CacheAdopter = Callable[[str, Sequence[DataRoot]], None]

# Supplied by the GUI: the recipe of every open graph, as TabSpec dicts. Called
# right before every write, so each way of saving keeps the current tabs.
OpenTabsCapture = Callable[[], List[Dict]]

# Supplied by the GUI: called after every successful write, whichever path
# triggered it, so the window title, recent list and file claim catch up.
SavedListener = Callable[[], None]


@dataclass
class _WorkflowHistory:
    snapshots: List[Workflow] = field(default_factory=list)
    cursor: int = -1


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


class ProjectSession(ProjectFolderMixin, ResultSetsMixin):
    """
    Holds the open project, where it is stored, and whether it needs saving.

    The unsaved-changes rule is the subtle part, because getting it wrong makes
    the application either nag or lose work:

      - Browsing, plotting and changing FFT settings never touch the project,
        so they can never mark it unsaved.
      - A View change (mark_view_changed) marks only a project that has a
        file: indexing a folder, the X axis unit, a checked filter value. On an
        Untitled project there is no stored state to be behind and the folder
        is recovered from the last-directory setting on the next start. This is
        what lets the user open the app, look at a folder and leave without
        being asked to save anything.
      - A Work change (mark_work_changed) always marks the project, Untitled or
        not: metadata edits, unit corrections, result sets, Filter cards, an
        open graph's recipe. These exist nowhere else, so losing them silently
        is not acceptable.

    Callers say which kind of change they made and never decide on their own
   .
    """

    def __init__(self, cache_adopter: Optional[CacheAdopter] = None):
        self._project = NVHProject(name=UNTITLED_NAME)
        self._path: Optional[str] = None
        self._dirty = False
        self._channel_pairs: List[Tuple[ChannelIdentity, ChannelIdentity]] = []
        self._cache_adopter = cache_adopter
        self._open_tabs_capture: Optional[OpenTabsCapture] = None
        self._saved_listener: Optional[SavedListener] = None
        self._workflow_history: Dict[str, _WorkflowHistory] = {}
        self._source_location = SourceLocation()

    # ---- state --------------------------------------------------------

    @property
    def project(self) -> NVHProject:
        return self._project

    @property
    def path(self) -> Optional[str]:
        return self._path

    @property
    def source_location(self) -> SourceLocation:
        """Memory-only path <-> entry lookup; current as of the last refresh_source_location()."""
        return self._source_location

    def refresh_source_location(self, root_directories: Mapping[str, Optional[str]]) -> SourceLocation:
        """
        Rebuilds the snapshot from `root_directories` (read_root_directories(),
        taken off the GUI thread) and the project's current sources. Reads no disk.
        """
        self._source_location = build_source_location(
            self._project.data_roots, self._project.sources, root_directories)
        return self._source_location

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

    def set_open_tabs_capture(self, capture: Optional[OpenTabsCapture]) -> None:
        """
        Plugs in the GUI's read of the open graphs. Every write calls it first,
        so Save, a committed result set and a save_edit all store the tabs as
        they are now -- not as they were at the last explicit Save (#654).
        """
        self._open_tabs_capture = capture

    def set_saved_listener(self, listener: Optional[SavedListener]) -> None:
        """Plugs in what the window does after every successful write."""
        self._saved_listener = listener

    @property
    def display_name(self) -> str:
        """Window-title form: the project name, marked when unsaved."""
        base = self._project.name or UNTITLED_NAME
        return f"{base}*" if self._dirty else base

    def mark_work_changed(self) -> None:
        """
        Records a Work change: one that exists nowhere but in the project.

        Applies to an Untitled project too, so that work is not lost on close.
        """
        self._dirty = True

    def mark_view_changed(self) -> None:
        """
        Records a View change: how the data is being looked at.

        Only meaningful once the project has a file: on an Untitled one there
        is nothing stored to be behind, so it never prompts.
        """
        if self.has_file:
            self._dirty = True

    @property
    def x_axis_unit(self) -> str:
        """The project's global X axis unit (issue #459), one of
        core.axis_projections.X_AXIS_UNITS; native when unset or unknown."""
        value = self._project.view_state.get(X_AXIS_UNIT_KEY, X_AXIS_NATIVE)
        return value if value in X_AXIS_UNITS else X_AXIS_NATIVE

    def set_x_axis_unit(self, x_axis_unit: str) -> None:
        """Records the global X axis unit with the project. A View change."""
        if x_axis_unit not in X_AXIS_UNITS:
            raise ValueError(f"Unknown X axis unit: {x_axis_unit!r}")
        if x_axis_unit == self.x_axis_unit:
            return
        self._project.view_state[X_AXIS_UNIT_KEY] = x_axis_unit
        self.mark_view_changed()

    @property
    def filter_state(self) -> Optional[Dict]:
        """The Filter panel's saved switches, Global values and active card."""
        return self._project.view_state.get(FILTER_STATE_KEY)

    def set_filter_state(self, snapshot: Dict, *, is_change: bool = True) -> None:
        """
        Records the Filter panel's state (session.trace_filter.
        build_filter_state_snapshot). A View change; `is_change=False` stores
        it without one -- picking another card's tab is a view choice the next
        Save keeps, not an edit. An unchanged snapshot is no change at all.
        """
        if self._project.view_state.get(FILTER_STATE_KEY) == snapshot:
            return
        self._project.view_state[FILTER_STATE_KEY] = snapshot
        if is_change:
            self.mark_view_changed()

    @property
    def filter_profiles(self) -> List[Dict]:
        """The user-added Filter cards' identities, as saved."""
        return [dict(profile) for profile in self._project.filter_profiles]

    def set_filter_profiles(self, profiles: Sequence[Dict]) -> None:
        """Records the user-added Filter cards. A Work change when they differ."""
        profiles = [dict(profile) for profile in profiles]
        if profiles == self._project.filter_profiles:
            return
        self._project.filter_profiles = profiles
        self.mark_work_changed()

    def put_filter_card(self, card) -> None:
        """Stores one Filter card's configuration. A Work change."""
        self._project.put_filter_card(card)
        self.mark_work_changed()

    @property
    def acknowledged_schema_conflicts(self) -> List[str]:
        return list(self._project.view_state.get(ACKNOWLEDGED_KEY) or [])

    def acknowledge_schema_conflicts(self, keys) -> None:
        """Remembers which schema conflicts the user has seen. A View change."""
        seen = set(self.acknowledged_schema_conflicts)
        seen.update(keys)
        if seen == set(self.acknowledged_schema_conflicts):
            return
        self._project.view_state[ACKNOWLEDGED_KEY] = sorted(seen)
        self.mark_view_changed()

    # ---- lifecycle ----------------------------------------------------

    def new_project(self, name: str = UNTITLED_NAME) -> NVHProject:
        self._project = NVHProject(name=name)
        self._workflow_history.clear()
        self._channel_pairs = []
        self._path = None
        self._dirty = False
        self._source_location = SourceLocation()
        self._install_import_templates()
        return self._project

    def load_project_file(self, project_path: str) -> None:
        """
        Loads a project's stored state without reading its data folders.

        The GUI opens a project the same way, in two steps (read_project_file,
        then install_project_file, so a failed read changes nothing), and then
        re-indexes the folders in the background (orchestration/project_swap), which is what
        keeps a project whose measurements sit on a slow or unmounted drive from
        freezing the window on open. Each folder's re-index lands through
        add_data_directory.
        """
        self.install_project_file(project_path, self.read_project_file(project_path))

    @staticmethod
    def read_project_file(project_path: str) -> NVHProject:
        """
        Reads a stored project without installing it: a file that cannot be
        read raises (OSError, ValueError, ProjectFormatError) and leaves the
        open project as it was -- the first step of a project swap (#771).
        """
        return load_project(project_path)

    def install_project_file(self, project_path: str, project: NVHProject) -> None:
        """Makes a project read by read_project_file the open one, clean."""
        self._project = project
        self._workflow_history.clear()
        self._channel_pairs = []
        self._path = os.path.abspath(project_path)
        self._dirty = False
        self._source_location = SourceLocation()
        self._install_import_templates()
        self._remove_unreferenced_tab_cache()

    def save(self) -> str:
        """Saves to the existing path. Use save_as() when there is none yet."""
        self._write()
        self._notify_saved()
        return self._path

    def _write(self) -> None:
        """Writes the project to its path, current tabs included. Tells nobody:
        a caller that must roll back on failure (commit_result_set) notifies
        only once the whole unit has succeeded."""
        if self._path is None:
            raise ValueError("Project has never been saved; a path is required.")
        self._capture_open_tabs()
        save_project(self._project, self._path)
        self._dirty = False
        self._remove_unreferenced_tab_cache()

    def _remove_unreferenced_tab_cache(self) -> None:
        """
        Deletes the Tab cache files the saved project no longer names:
        a closed tab, a removed curve, a result a newer Save replaced, or a file a
        crash or a "Don't save" left behind. Runs right after open and after
        every write, on the GUI thread: it only unlinks a handful of small
        files in one folder the project owns, and the deletion never raises,
        so a clean-up problem cannot fail a Save. Never touches anything
        outside `cache/tabs/`.
        """
        remove_unreferenced_tab_cache_files(
            tab_cache_folder(self._path),
            build_referenced_tab_cache_names(self._project.open_tabs))

    def current_open_tabs(self) -> List[Dict]:
        """The open graphs as they are now (`TabSpec.to_dict()` each), without writing them anywhere."""
        if self._open_tabs_capture is not None:
            return [dict(spec) for spec in self._open_tabs_capture()]
        return [dict(spec) for spec in self._project.open_tabs]

    def _capture_open_tabs(self) -> None:
        if self._open_tabs_capture is not None:
            self._project.open_tabs = list(self._open_tabs_capture())

    def _notify_saved(self) -> None:
        if self._saved_listener is not None:
            self._saved_listener()

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
        self.mark_work_changed()
        if had_other_unsaved_edits:
            return False
        self.save()
        return True

    def save_as(self, project_path: str,
                folder_copy: Optional[ProjectFolderCopy] = None) -> str:
        """
        Saves to a new location, re-expressing the data roots against it.

        The re-anchoring is not cosmetic. Roots added before the project had a
        file carry no relative path at all, and a Save As into a different
        folder invalidates the ones that do -- in both cases the project would
        reopen unable to find any of its measurements.

        Result sets are the same problem one level down: they live in the
        folder's `cache/`. A move into another folder with result sets needs
        `folder_copy` -- a plan from `build_project_folder_copy` whose copies
        have already been made -- or it is refused, and so is a folder that
        already holds another project.
        """
        was_untitled = self._path is None
        new_path = os.path.abspath(project_path)
        self._refuse_shared_folder(new_path)
        old_path = self._path
        old_name = self._project.name
        root_snapshot = [
            (root, root.relpath, root.absolute_fallback)
            for root in self._project.data_roots
        ]
        result_set_snapshot = self._apply_project_folder_copy(new_path, folder_copy)

        try:
            self._capture_open_tabs()
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
            self._restore_result_sets(result_set_snapshot)
            raise

        if folder_copy is not None and folder_copy.copies:
            self._write_cache_index()
        if was_untitled:
            self._carry_untitled_scan_caches()
        self._dirty = False
        self._notify_saved()
        return new_path

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
        self.refresh_source_location(index.root_directories)
        if reconciled or report.changed:
            self.mark_view_changed()
        return report

    def resolved_directories(self) -> List[str]:
        """Every data folder that currently exists, in project order."""
        found = (resolve_root(self._path, root) for root in self._project.data_roots)
        return [directory for directory in found if directory]

    # ---- metadata -----------------------------------------------------

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

        self.mark_work_changed()
        return True


    def set_metadata_schema(self, schema: Dict) -> None:
        """
        Stores which metadata fields are shown and what they are called.

        Kept in the project rather than the folder cache: the cache is derived
        from the measurement files and may be deleted to force a re-scan, which
        would take the user's labels and visibility choices with it.
        """
        self._project.metadata_schema = dict(schema)
        self.mark_work_changed()

    @property
    def channel_pairs(self) -> List[Tuple[ChannelIdentity, ChannelIdentity]]:
        """Channel identity pairs read from channel_pairing.xlsx (#511); not part of the project file."""
        return list(self._channel_pairs)

    def set_channel_pairs(self, channel_pairs) -> None:
        self._channel_pairs = [tuple(pair) for pair in channel_pairs]

    # ---- applying project decisions to loaded data --------------------

    def set_source_amplitude(self, source_id: str, source_amplitude: str) -> bool:
        """
        Records what the amplitude in an Imported result file means ("rms" | "peak").

        A user decision about the file, so it lives here and never in the file
        itself. Returns True when the stored answer changed, so asking again
        with the same answer does not mark the project dirty.
        """
        if source_amplitude not in VALID_SOURCE_AMPLITUDES:
            raise ValueError(f"Unknown source amplitude {source_amplitude!r}.")
        entry = self._project.source_by_id(source_id)
        if entry is None or entry.source_amplitude == source_amplitude:
            return False
        entry.source_amplitude = source_amplitude
        self.mark_work_changed()
        return True

    def resolve_import_templates(self) -> Mapping[str, ImportTemplate]:
        """The project's copies of Import templates by name, as its readers use them (a snapshot; do not edit)."""
        return resolve_installed_templates()

    def resolve_import_template(self, name: str) -> Optional[ImportTemplate]:
        """The project's copy of the Import template of this name, None when it holds none (or cannot read it)."""
        return resolve_installed_template(name)

    def _install_import_templates(self) -> None:
        """Hands the project's copies to the readers (readers §1.233): after every change of the copies."""
        install_project_templates(self._project.import_templates)

    def adopt_import_template(self, template) -> bool:
        """
        Gives the project its own copy of an Import template, so its sources
        read from the copy and never from the built-in or the library.

        A copy the project already holds under the name stays: a library change
        reaches a project only when the user confirms replacing the copy
        (`replace_import_template`). Returns whether a copy was added (a Work
        change).
        """
        if template.name in self._project.import_templates:
            return False
        self._project.import_templates[template.name] = template.to_dict()
        self._install_import_templates()
        self.mark_work_changed()
        return True

    def replace_import_template(self, template) -> bool:
        """
        Replaces the project's copy of the Import template of this name by an
        edited one -- the user's confirmed edit of the copy, never a library
        change on its own. Returns whether the copy changed (a Work change);
        the files it reads are re-read by the caller.
        """
        copy = template.to_dict()
        if self._project.import_templates.get(template.name) == copy:
            return False
        self._project.import_templates[template.name] = copy
        self._install_import_templates()
        self.mark_work_changed()
        return True

    def set_import_template(self, source_id: str, import_template: str) -> bool:
        """Assigns an Import template (by name) to a source. A Work change; False if nothing changed."""
        entry = self._project.source_by_id(source_id)
        if entry is None or entry.import_template == import_template:
            return False
        entry.import_template = import_template
        self.mark_work_changed()
        return True

    def apply_source_assignments(self, runs) -> int:
        """
        Lays the project's Source amplitude answers and assigned Import
        templates over freshly loaded runs, the way apply_unit_overrides lays
        unit corrections: the scan reports the file, the project restates what
        the user said about it. Returns how many runs were touched.
        """
        touched = 0
        for run in runs:
            entry = self._source_location.entry_for_run(run)
            if entry is None or not (entry.source_amplitude or entry.import_template):
                continue
            for channel_meta in getattr(run, "available_channels", {}).values():
                if entry.source_amplitude:
                    channel_meta.source_amplitude = entry.source_amplitude
                if entry.import_template:
                    channel_meta.import_template = entry.import_template
            touched += 1
        return touched

    def record_unit_override(self, run, channel_label: str, unit: str) -> bool:
        """
        Remembers a unit correction against the measurement the channel is in.

        Takes the loaded run rather than a source id because that is what the
        explorer has in hand. Returns False when the file is not part of the
        project, which is the case while no data folder has been registered.
        """
        entry = self._source_location.entry_for_run(run)
        if entry is None:
            return False
        return self.set_unit_override(entry.id, channel_label, unit)

    def apply_unit_overrides(self, runs) -> int:
        """
        Lays the project's unit corrections over freshly loaded runs.

        This is what keeps the correction out of the measurement file and out
        of the folder cache: both keep saying whatever was originally recorded,
        and the project restates it on every load. Deleting the cache costs a
        re-scan and nothing else.

        Returns how many channels were corrected.
        """
        corrected = 0
        for run in runs:
            entry = self._source_location.entry_for_run(run)
            if entry is None or not entry.unit_overrides:
                continue

            for channel_label, unit in entry.unit_overrides.items():
                # A channel gone from the file keeps its correction in case it
                # comes back rather than being quietly dropped.
                if correct_run_channel(run, channel_label, unit):
                    corrected += 1

        return corrected

    def sync_source_metadata(self, runs) -> int:
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
        own.
        """
        synced = 0
        for run in runs:
            entry = self._source_location.entry_for_run(run)
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
            # in mark_work_changed()) it must not manufacture unsaved-changes state
            # out of the very first browse.
            self.mark_view_changed()
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
        from io_modules.metadata_schema import parsed_metadata_for_row

        # Channel-layer fields are per channel: typed source metadata
        # carries only Excel- and file-layer fields.
        file_schema = {key: config for key, config in (schema or {}).items()
                       if not is_channel_layer(config)}
        changed = 0
        for entry in self._project.sources:
            raw_by_key = {**entry.file_metadata, **entry.excel_metadata}
            parsed = parsed_metadata_for_row(raw_by_key, file_schema)
            if parsed != entry.parsed_metadata:
                entry.parsed_metadata = parsed
                changed += 1

        return changed

    # ---- measurement selections -----------------------------

    def selections(self) -> List[MeasurementSelection]:
        """Every named selection stored in this project, in stored order."""
        return list(self._project.selections)

    def find_selection(self, name: str) -> Optional[MeasurementSelection]:
        return self._project.selection_by_name(name)

    def save_selection(self, selection: MeasurementSelection) -> MeasurementSelection:
        """
        Stores a named selection, replacing one of the same name.

        A Work change -- unlike the checked filter values, a View change kept
        in view_state so that merely looking around does not make an Untitled
        project unsaved.
        """
        if not selection.name:
            raise ValueError("A stored selection needs a name -- it is how a recipe refers to it.")
        if selection.name == WHOLE_POOL_SELECTION_NAME:
            raise ValueError(
                f"'{WHOLE_POOL_SELECTION_NAME}' is reserved for the whole Data Pool -- "
                "pick another name for a stored selection."
            )
        stored = self._project.put_selection(selection)
        self.mark_work_changed()
        return stored

    def remove_selection(self, name: str) -> bool:
        removed = self._project.remove_selection(name)
        if removed:
            self.mark_work_changed()
        return removed

    def workflows_using_selection(self, name: str) -> List[str]:
        """Names of the workflows whose Input block refers to selection `name`."""
        return [workflow.name for workflow in self._project.workflows
                if any(block.is_input and block.input and block.input.selection_name == name
                       for block in workflow.blocks)]

    def rename_selection(self, old_name: str, new_name: str) -> None:
        """
        Renames a selection in place and, in the same step, the `selection_name`
        of every Input block that refers to it -- a workflow names its selection
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
        def rename_input(workflow: Workflow) -> Workflow:
            blocks = tuple(
                replace(block, input=replace(block.input, selection_name=new_name))
                if block.is_input and block.input and block.input.selection_name == old_name else block
                for block in workflow.blocks)
            return replace(workflow, blocks=blocks) if blocks != workflow.blocks else workflow

        for workflow in list(self._project.workflows):
            self._project.put_workflow(rename_input(workflow))
        # Selection renames are project edits, not canvas undo steps. Rebase
        # snapshots so undo cannot resurrect the selection's obsolete name.
        for history in self._workflow_history.values():
            history.snapshots = [rename_input(snapshot) for snapshot in history.snapshots]
        self.mark_work_changed()

    # ---- block-diagram workflows ----------------------------

    def workflows(self) -> List[Workflow]:
        """Every workflow stored in this project, in stored order."""
        return list(self._project.workflows)

    def find_workflow(self, name: str) -> Optional[Workflow]:
        return self._project.workflow_by_name(name)

    def save_workflow(self, workflow: Workflow, *, record_history: bool = True) -> Workflow:
        """
        Stores a named workflow, replacing one of the same name.

        A project decision -- it marks the project dirty -- exactly like
        save_selection, and for the same reason: it is analysis intent the user
        authored, not a view they merely scrolled to.

        Each distinct edit records an in-memory snapshot for this workflow.
        Undo/redo uses the same save path with recording disabled; history is
        discarded when opening another project, never serialized to disk.
        """
        if not workflow.name:
            raise ValueError("A stored workflow needs a name -- it is how a run refers to it.")
        previous = self.find_workflow(workflow.name)
        if record_history:
            history = self._workflow_history.setdefault(workflow.name, _WorkflowHistory())
            snapshots = history.snapshots
            if not snapshots and previous is not None:
                snapshots.append(previous)
                history.cursor = 0
            cursor = history.cursor
            if cursor < 0 or snapshots[cursor] != workflow:
                del snapshots[cursor + 1:]
                snapshots.append(workflow)
                history.cursor = len(snapshots) - 1
        stored = self._project.put_workflow(workflow)
        self.mark_work_changed()
        return stored

    def can_undo_workflow(self, name: str) -> bool:
        """Whether this workflow has an earlier in-memory snapshot."""
        history = self._workflow_history.get(name)
        return history is not None and history.cursor > 0

    def can_redo_workflow(self, name: str) -> bool:
        """Whether this workflow has a later in-memory snapshot."""
        history = self._workflow_history.get(name)
        return history is not None and history.cursor + 1 < len(history.snapshots)

    def undo_workflow(self, name: str) -> Optional[Workflow]:
        """Restore the preceding snapshot through the normal dirty save path."""
        return self._restore_workflow(name, -1) if self.can_undo_workflow(name) else None

    def redo_workflow(self, name: str) -> Optional[Workflow]:
        """Restore the next snapshot without recording another edit."""
        return self._restore_workflow(name, 1) if self.can_redo_workflow(name) else None

    def _restore_workflow(self, name: str, step: int) -> Workflow:
        history = self._workflow_history[name]
        cursor = history.cursor + step
        workflow = history.snapshots[cursor]
        stored = self.save_workflow(workflow, record_history=False)
        history.cursor = cursor
        return stored

    def remove_workflow(self, name: str) -> bool:
        removed = self._project.remove_workflow(name)
        if removed:
            self._workflow_history.pop(name, None)
            self.mark_work_changed()
        return removed

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
        existing = self._source_location.entry_for_path(absolute)
        if existing is not None and existing.id != entry.id:
            return False

        directory = os.path.dirname(absolute)
        root, _ = reconcile_root(
            self._project, self._path, directory,
            root_directories=root_directories)
        if self._project.source_by_id(source_id) is not entry:
            # Finding the root folded a duplicate of the target folder away,
            # and this entry went with it into the one kept for the file.
            self.mark_work_changed()
            return False

        stamp = file_stamp(absolute)
        entry.root_id = root.id
        entry.relpath = os.path.relpath(absolute, directory)
        if stamp is not None:
            entry.size_bytes = stamp["size"]
            entry.mtime_ns = stamp["mtime_ns"]
        entry.in_pool = True

        self.refresh_source_location(root_directories)
        self.mark_work_changed()
        return True

    def set_pool_membership(self, paths, in_pool: bool) -> int:
        """
        Records which measurements are in the Data Pool.

        Takes paths rather than ids because that is what the pool deals in --
        it holds runs read off disk, not project entries. Returns how many
        entries actually changed, so a re-scan that admits the same files it
        admitted last time does not mark the project dirty.
        """
        changed = 0
        for path in paths:
            entry = self._source_location.entry_for_path(path)
            if entry is None or entry.in_pool == in_pool:
                continue
            entry.in_pool = in_pool
            changed += 1

        if changed:
            self.mark_view_changed()
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
        self.mark_work_changed()
        return True

    def cache_finder(self) -> Callable:
        """
        The result-set lookup for a worker thread: "is this
        result already on disk?" for any block kind. The returned callable owns
        the project, its path and the path <-> entry snapshot as they are now,
        so the worker neither reads the disk to find the entry nor touches the
        live session. It returns a cache_lookup.CachedResult (stored blocks plus
        the set they came from) or None on a miss (unknown source, no saved
        result set with matching settings, or a requested block not present),
        and never persists `cache/index.json`.

        See io_modules.result_cache.find_cached_result for what "matching" means.
        `channel_index` (the channel's ChannelMetadata.index) tells two
        same-named channels of one file apart; every caller that has the
        channel's metadata in hand should pass it.
        """
        from io_modules.result_cache import find_cached_result

        project, project_path, location = self._project, self._path, self._source_location

        def finder(absolute_path: str, channel_name: str, kind: str, live_params: Dict,
                   wanted_block_params: Optional[List[Dict]] = None,
                   channel_index: Optional[int] = None):
            entry = location.entry_for_path(absolute_path)
            if entry is None:
                return None
            return find_cached_result(project, project_path, entry, channel_name, kind,
                                      live_params, wanted_block_params,
                                      write_index=False, channel_index=channel_index)

        return finder


# ---- test setup assignment (gui/file_explorer/actions/assign_test_setup.py) --

def apply_setup_label(session: ProjectSession, file_paths, label: str):
    """Records a test setup label against each file's project entry."""
    location = session.source_location

    assigned = 0
    unknown = 0
    for path in file_paths:
        entry = location.entry_for_path(path)
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
