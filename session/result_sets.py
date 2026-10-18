# =====================================================================
# FILE: session/result_sets.py
# =====================================================================
"""
Result-set lifecycle for ProjectSession: begin / commit / abort a batch write,
plus the label and duplicate bookkeeping around it.

Mixed into ProjectSession rather than built as a separate collaborator
(`session.result_sets.begin(...)`): the project rules name result sets, alongside
metadata, unit corrections and pool membership, as a project decision that
lives on ProjectSession. A collaborator would move that public surface off
the session and weaken the invariant; a mixin keeps every call site (and the
sentence in the project rules) unchanged while still splitting the file.

The disk side of a commit (folder creation, deletion, and the overwrite
rename-swap) lives in io_modules/result_cache/cache_folders.py, not here --
see that module's docstring for why (#172). This module calls it rather than
touching the filesystem directly.
"""

import os
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from core.project_model import ResultSetRef, utc_now
from io_modules.project_store import (
    CACHE_DIR_NAME, SCAN_CACHE_DIR_NAME, TAB_CACHE_DIR_NAME, cache_folder, project_files_in,
    project_folder, scan_cache_folder, tab_cache_folder)
from io_modules.result_cache import cache_folders
from io_modules.tab_cache import read_tab_cache_names, resolve_tab_cache_path

# The staging folder name carries a per-draft random token: resolve_overwrites
# can point two save nodes at the same existing set (audit 02, finding
# S1/1.1), and a shared "<label>.staging" folder meant the second commit
# swapped an empty folder over the first's committed data. commit and abort
# both work from `draft.folder`, so the unique name stays contained. The
# suffix contains a "." -- which cache_naming.sanitize_result_set_label
# strips from every user-chosen label in begin_result_set -- so no
# user-chosen label can ever collide with it.
_STAGING_SUFFIX = ".staging"

# Subfolders of the cache folder that are not result sets.
_CACHE_SUBFOLDER_NAMES = frozenset({SCAN_CACHE_DIR_NAME, TAB_CACHE_DIR_NAME})


def _names_a_cache_subfolder(label: str) -> bool:
    return label.lower() in _CACHE_SUBFOLDER_NAMES


@dataclass(frozen=True)
class ResultSetCopyPlan:
    """
    What a Save As into another folder copies, and what the project then names.

    Built by `build_result_set_copy` before anything is written. `copies` are
    absolute `(source, destination)` pairs -- the result sets first, then the
    scan caches and the Tab cache files the destination does not have yet; `relabels` is
    `(result_set_id, label, file)` for every result set the new project keeps.
    `fingerprint` is what the result sets were when the plan was made: a batch
    that commits or overwrites one while the copy runs makes the plan stale,
    and `save_as` refuses it rather than name a set that was never copied.
    With `keep_result_sets=False` the new project keeps none and only the scan
    caches and the Tab cache are copied. An empty plan (same folder, or a first save) copies
    nothing and changes nothing.
    """
    project_path: str
    keep_result_sets: bool = True
    copies: Tuple[Tuple[str, str], ...] = ()
    relabels: Tuple[Tuple[str, str, str], ...] = ()
    result_set_bytes: int = 0
    fingerprint: Tuple = ()

    @property
    def result_set_count(self) -> int:
        return len(self.relabels) if self.keep_result_sets else 0

    @property
    def destinations(self) -> List[str]:
        return [destination for _source, destination in self.copies]


class ResultSetsMixin:
    """Result-set begin/commit/abort and label bookkeeping, mixed into ProjectSession."""

    # Counts commits, so a Save As copy plan can tell it went stale (#674).
    _result_set_commits = 0

    # ---- result sets ----------------------------------------------------

    def begin_result_set(self, kind: str, params: Dict, label: Optional[str] = None,
                         overwrite_result_set_id: Optional[str] = None,
                         compression: Optional[str] = None):
        """
        Opens a result set for writing and returns the draft to write into.

        Three calls rather than one (begin / write shards / commit) because a
        result set is written by many background steps, one measurement each
       : a spectrogram batch is gigabytes, so nothing may be held
        until the end. The draft is plain frozen data with no open handles, so
        it is safe to hand to workers; each of them calls
        cache_writer.write_result_shard with it.

        Requires an already-saved project: the cache lives in a folder next to
        the project file, so there is nowhere to put it before ensure_saved()
        has run.

        On overwrite the shards go to a staging folder and are swapped in by
        commit_result_set, so a failure part-way through leaves the existing
        result set exactly as it was.
        """
        if not self.has_file:
            raise ValueError("Project must be saved before a result set can be written.")

        from io_modules.result_cache import cache_layout, cache_naming
        from io_modules.result_cache.cache_writer import ResultSetDraft

        if overwrite_result_set_id:
            existing = self._result_set_by_id(overwrite_result_set_id)
            label = existing.label
            folder = os.path.join(
                cache_folder(self._path),
                f"{label}.{uuid.uuid4().hex[:8]}{_STAGING_SUFFIX}",
            )
            cache_folders.remove_tree(folder)
        else:
            # The label is free user text (dialog QLineEdit) and becomes a
            # folder name a line below -- unsanitised it can escape the cache
            # dir or overwrite cache/scan/ (audit 02 finding 5.1). The dialogs
            # preview and block this, so a non-empty label that strips to
            # nothing here is a programming error, not a user typo.
            if label:
                clean = cache_naming.sanitize_result_set_label(label)
                if not clean:
                    raise ValueError(f"Result set name {label!r} has no usable characters.")
                label = clean
            label = self._unique_label(label) if label else self._next_result_set_label(kind)
            folder = os.path.join(cache_folder(self._path), label)

        cache_folders.make_result_set_folder(folder)
        return ResultSetDraft(
            folder=folder, kind=kind, label=label, params=dict(params),
            params_hash=cache_layout.params_hash(params), created_utc=utc_now(),
            compression=compression or None,
        )

    def commit_result_set(self, draft, entries: List[Dict], status: str = "complete",
                          all_channels: bool = False,
                          overwrite_result_set_id: Optional[str] = None) -> ResultSetRef:
        """
        Finishes a draft: writes its manifest, records it in the project, and
        saves -- as one unit.

        `entries` are the manifest entries the shard writes returned, in any
        order. `status` should be "partial" when some channels or sources
        failed while others succeeded: cache lookup refuses to treat a partial
        set as a hit, so mislabelling one "complete" would hand back coverage
        that was never computed.

        If the project save fails, everything is rolled back -- the result set
        is removed from the model again and the freshly written folder is
        deleted -- so a failure never leaves cache files on disk that the
        project does not know about, or vice versa.
        """
        from io_modules.result_cache.cache_writer import build_manifest, write_set_manifest

        manifest = build_manifest(draft, entries, status, all_channels)
        write_set_manifest(draft.folder, manifest)
        self._result_set_commits = self._result_set_commits + 1

        source_ids = [entry.get("source_id", "") for entry in entries]
        if overwrite_result_set_id:
            result_set = self._commit_overwrite(
                overwrite_result_set_id, draft, status, all_channels, source_ids
            )
        else:
            result_set = ResultSetRef(
                label=draft.label, kind=draft.kind,
                file=os.path.join(CACHE_DIR_NAME, draft.label),
                params=dict(draft.params), params_hash=draft.params_hash,
                created_utc=draft.created_utc,
                status=status, source_ids=source_ids, all_channels=all_channels,
            )
            self._project.add_result_set(result_set)
            try:
                self._save_with_index()
            except Exception:
                self._project.result_sets.remove(result_set)
                cache_folders.remove_tree(draft.folder)
                raise
        # After the rollback window: a failing listener must not undo a set
        # that is already on disk and named in the project file.
        self._notify_saved()
        return result_set

    def _commit_overwrite(self, result_set_id: str, draft, status: str,
                          all_channels: bool, source_ids: List[str]) -> ResultSetRef:
        """
        Swaps a staged folder over the result set it replaces, then updates it.

        The label, id and file path are kept -- only the content, params_hash,
        source coverage and timestamp change -- so anything that already
        referenced this result set by id still finds it. The folder swap
        happens before the project save; if that save then fails, both are
        rolled back -- the model fields, and the folders (the retired set is
        renamed back and the staged data discarded) -- so the reverted ref
        names its own data again rather than the new numbers (#315). Should
        the folder restore itself fail, the swapped-in manifest still carries
        the new params_hash, and find_cached_result skips it as a mismatch.
        """
        existing = self._result_set_by_id(result_set_id)
        final_folder = os.path.join(cache_folder(self._path), existing.label)

        previous = (existing.params, existing.params_hash, existing.status,
                    existing.source_ids, existing.all_channels, existing.created_utc,
                    existing.file, existing.kind)

        existing.params = dict(draft.params)
        existing.params_hash = draft.params_hash
        existing.status = status
        existing.source_ids = source_ids
        existing.all_channels = all_channels
        existing.created_utc = draft.created_utc
        existing.kind = draft.kind
        existing.file = os.path.join(CACHE_DIR_NAME, existing.label)

        try:
            cache_folders.swap_in_overwrite(final_folder, draft.folder)
            self._save_with_index()
        except Exception:
            (existing.params, existing.params_hash, existing.status,
             existing.source_ids, existing.all_channels, existing.created_utc,
             existing.file, existing.kind) = previous
            cache_folders.restore_retired(final_folder, draft.folder)
            cache_folders.remove_tree(draft.folder)
            raise

        cache_folders.discard_retired(final_folder)
        return existing

    def abort_result_set(self, draft) -> None:
        """
        Throws a draft away -- a cancelled batch, or one that produced nothing.

        Best-effort: a shard a reader still has open cannot be deleted on
        Windows, and a leftover folder with no manifest is inert (every reader
        treats a manifest-less folder as unreadable and the project never
        names it).
        """
        cache_folders.remove_tree(getattr(draft, "folder", ""))

    # ---- Save As into another folder ------------------------

    def build_result_set_copy(self, project_path: str,
                             keep_result_sets: bool = True) -> ResultSetCopyPlan:
        """
        Plans what a Save As to `project_path` has to copy so that the new
        project reads its own results, never another copy's.

        The cache belongs to the folder, and a result set is named relative to
        it -- so a project moved to another folder without its cache would read
        `cache/<label>` there: missing, or worse, a different project's numbers
        under the same label (#674). Each kept set gets a label that is free in
        the destination cache (`_2`, `_3`... as `_unique_label` does), so a
        leftover there is neither overwritten nor adopted.

        Raises ValueError when the destination folder already holds another
        project. Copies nothing itself: the copy can be gigabytes and runs on
        a background job; `save_as(project_path, result_set_copy=plan)` then
        commits it.
        """
        new_path = os.path.abspath(project_path)
        self._refuse_shared_folder(new_path)
        if not self._moves_folder(new_path):
            return ResultSetCopyPlan(project_path=new_path)

        old_folder = project_folder(self._path)
        new_cache = cache_folder(new_path)
        copies: List[Tuple[str, str]] = []
        relabels: List[Tuple[str, str, str]] = []
        taken = set()
        if keep_result_sets:
            for result_set in self._project.result_sets:
                label = result_set.label
                n = 2
                while self._destination_label_taken(new_cache, label, taken):
                    label = f"{result_set.label}_{n}"
                    n += 1
                taken.add(label)
                source = os.path.join(old_folder, result_set.file)
                is_file = os.path.isfile(source)
                name = f"{label}.h5" if is_file else label
                relabels.append((result_set.id, label, os.path.join(CACHE_DIR_NAME, name)))
                # A set whose folder is already gone has nothing to copy; it
                # keeps its fresh label, so it stays missing rather than
                # reading whatever the destination holds under the old one.
                if os.path.exists(source):
                    copies.append((source, os.path.join(new_cache, name)))
        result_set_bytes = cache_folders.measure_result_sets(s for s, _ in copies)

        old_scan, new_scan = scan_cache_folder(self._path), scan_cache_folder(new_path)
        if os.path.isdir(old_scan):
            for name in sorted(os.listdir(old_scan)):
                source, destination = os.path.join(old_scan, name), os.path.join(new_scan, name)
                if os.path.isfile(source) and not os.path.exists(destination):
                    copies.append((source, destination))

        copies.extend(self._tab_cache_copies(new_path))

        return ResultSetCopyPlan(
            project_path=new_path, keep_result_sets=keep_result_sets,
            copies=tuple(copies), relabels=tuple(relabels),
            result_set_bytes=result_set_bytes,
            fingerprint=self._result_set_fingerprint(),
        )

    def _tab_cache_copies(self, new_path: str) -> List[Tuple[str, str]]:
        """
        Every Tab cache file, so the new project's tabs open without a compute
       . Names are relative to `cache/tabs/`, so they stay valid.
        Kept whatever the user chose for result sets: a Tab cache is no
        result set. One the destination already has is left alone. A write
        still in progress is not listed: Save As waits for those before it
        builds the copy.
        """
        old_tabs, new_tabs = tab_cache_folder(self._path), tab_cache_folder(new_path)
        copies = []
        for name in read_tab_cache_names(old_tabs):
            destination = resolve_tab_cache_path(new_tabs, name)
            if destination is not None and not os.path.exists(destination):
                copies.append((resolve_tab_cache_path(old_tabs, name), destination))
        return copies

    def _result_set_fingerprint(self) -> Tuple:
        # The commit count, not the refs alone: an overwrite keeps id, label
        # and file, and its timestamp has one-second resolution.
        return (self._result_set_commits,
                tuple((rs.id, rs.file) for rs in self._project.result_sets))

    @staticmethod
    def _destination_label_taken(new_cache: str, label: str, taken) -> bool:
        return (_names_a_cache_subfolder(label) or label in taken
                or cache_folders.label_folder_exists(os.path.join(new_cache, label)))

    def _moves_folder(self, new_path: str) -> bool:
        """Whether saving to `new_path` leaves the folder the cache lives in."""
        if not self._path:
            return False
        return (os.path.normcase(project_folder(self._path))
                != os.path.normcase(project_folder(new_path)))

    def _apply_result_set_copy(self, new_path: str,
                               plan: Optional[ResultSetCopyPlan]) -> List:
        """
        Points the result sets at their copies for a Save As to `new_path`;
        returns what `_restore_result_sets` needs to undo it.

        Refuses a move between folders that would carry result sets without a
        plan: the refs would name `cache/<label>` in a folder that does not
        hold them (#674).
        """
        snapshot = [list(self._project.result_sets)] + [
            (rs, rs.label, rs.file) for rs in self._project.result_sets]
        if plan is None:
            if self._moves_folder(new_path) and self._project.result_sets:
                raise ValueError(
                    "Saving into another folder needs a plan for the result sets "
                    "(ProjectSession.build_result_set_copy).")
            return snapshot
        if os.path.normcase(plan.project_path) != os.path.normcase(new_path):
            raise ValueError("The result-set copy plan was made for a different path.")
        if not plan.keep_result_sets:
            self._project.result_sets = []
            return snapshot
        if self._moves_folder(new_path) and plan.fingerprint != self._result_set_fingerprint():
            raise ValueError(
                "The project's result sets changed while they were being copied "
                "(a batch run finished). Nothing was saved; try Save As again.")
        by_id = {rs.id: rs for rs in self._project.result_sets}
        for result_set_id, label, file in plan.relabels:
            result_set = by_id.get(result_set_id)
            if result_set is not None:
                result_set.label, result_set.file = label, file
        return snapshot

    def _restore_result_sets(self, snapshot: List) -> None:
        self._project.result_sets = snapshot[0]
        for result_set, label, file in snapshot[1:]:
            result_set.label, result_set.file = label, file

    def _refuse_shared_folder(self, new_path: str) -> None:
        """
        One folder holds one project: projects in a folder share
        its `cache/`, so a second one would read and overwrite the first's
        results. Saving over the open project's own file is just a save.
        """
        if self._path and os.path.normcase(self._path) == os.path.normcase(new_path):
            return
        folder = project_folder(new_path)
        existing = project_files_in(folder)
        if existing:
            raise ValueError(
                f"The folder '{folder}' already holds a project "
                f"({os.path.basename(existing[0])}).\n\n"
                "Projects in one folder would share their computed results, so each "
                "project needs a folder of its own. Choose an empty folder, or remove "
                "that project first."
            )

    def _save_with_index(self) -> None:
        """Saves the project and refreshes the derived cache index alongside it."""
        self._write()
        self._write_cache_index()

    def _write_cache_index(self) -> None:
        from io_modules.result_cache import cache_index
        try:
            cache_index.write(self._path, cache_index.rebuild(self._project, self._path))
        except OSError:
            pass    # the index is derived; a failure to write it costs a rebuild, not data

    def _result_set_by_id(self, result_set_id: str) -> ResultSetRef:
        existing = next((rs for rs in self._project.result_sets if rs.id == result_set_id), None)
        if existing is None:
            raise ValueError(f"No result set with id '{result_set_id}' to overwrite.")
        return existing

    def find_duplicate_result_set(self, params: Dict, kind: str = None) -> Optional[ResultSetRef]:
        """
        Looks for an existing result set of `kind` computed with exactly these
        settings, so the caller can offer to overwrite it instead of writing a
        near-duplicate. See
        io_modules.result_cache.cache_lookup.find_duplicate_result_set for
        what "exactly" means.
        """
        from core.block_kinds import KIND_ORDER_CUT
        from io_modules.result_cache.cache_lookup import find_duplicate_result_set as _find
        return _find(self._project, params, kind=kind or KIND_ORDER_CUT)

    def _label_is_taken(self, label: str) -> bool:
        """
        Whether a result set may not be written under this label.

        The cache folder is checked as well as the project's own list, because
        the label decides the folder name and the two can legitimately disagree:
        project_store creates the cache folder eagerly so a pre-computed cache
        can be copied in before anything has been calculated, and such a file
        is on disk without any ResultSetRef naming it. Going by the list alone,
        the first Calculate & Save Data would overwrite it.

        The cache's own subfolders are refused outright: scan caches live in
        `cache/scan/` (§1.22) and the Tab cache in `cache/tabs/` (§1.178), so
        a result set that happened to be labelled "scan" or "tabs" -- in any
        case, the folder names are case-insensitive on Windows -- would write
        its shards straight over them.
        """
        if _names_a_cache_subfolder(label):
            return True
        if any(rs.label == label for rs in self._project.result_sets):
            return True
        if not self._path:
            return False
        return cache_folders.label_folder_exists(os.path.join(cache_folder(self._path), label))

    def _next_result_set_label(self, prefix: str) -> str:
        """First unused "{prefix}_vNN" label, so repeated saves auto-version."""
        n = 1
        while self._label_is_taken(f"{prefix}_v{n:02d}"):
            n += 1
        return f"{prefix}_v{n:02d}"

    def _unique_label(self, candidate: str) -> str:
        """
        Disambiguates a caller-supplied label that already exists, so saving
        the same selection twice never silently overwrites the first result
        set -- it appends "_2", "_3", ... instead.
        """
        if not self._label_is_taken(candidate):
            return candidate
        n = 2
        while self._label_is_taken(f"{candidate}_{n}"):
            n += 1
        return f"{candidate}_{n}"
