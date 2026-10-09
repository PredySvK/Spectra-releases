# =====================================================================
# FILE: io_modules/project_store.py
# =====================================================================
"""
Reading, writing and indexing of .nvhproject files.

This is the only module that turns an NVHProject into bytes and back. The model
itself (core.project_model) stays free of file access so it can be reasoned
about and tested without a disk; everything that can fail because of the
filesystem lives here.

Three jobs:
  - save/load, with a write that cannot leave a half-written project behind
  - resolving a data root back to a real folder after the project has moved
  - indexing a folder into source entries, recognising files that have only
    been renamed rather than replaced

All internal documentation strings and variable labels are standardly written
in English.
"""

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from core.project_model import (
    OLDEST_READABLE_PROJECT_FORMAT_VERSION,
    PROJECT_FORMAT_VERSION,
    DataRoot,
    NVHProject,
    SourceEntry,
)
from io_modules.atomic_write import write_json_atomic
from io_modules.measurement_files import canonical_path, discover_measurement_files, file_stamp
from io_modules.scan_cache import scan_cache_basename

# Computed result sets live beside the project file, not inside it.
CACHE_DIR_NAME = "cache"

# Folder-scan caches (parsed channel inventory per data folder) live under the
# project's cache folder too, in their own subfolder so the HDF5 result sets
# stay easy to browse (ADR §1.22).
SCAN_CACHE_DIR_NAME = "scan"

# How long an Untitled scan cache file may sit in the shared temp area before a
# startup sweep removes it.
UNTITLED_SCAN_CACHE_MAX_AGE_DAYS = 14


class ProjectFormatError(Exception):
    """The file is not a project, or its project format version is unsupported."""


# ---------------------------------------------------------------------------
# save / load
# ---------------------------------------------------------------------------

def save_project(project: NVHProject, project_path: str) -> str:
    """
    Writes the project to disk, atomically.

    A project file is the only record of the user's metadata edits and unit
    corrections; the raw measurements carry none of it. Writing in place would
    mean a crash or a full disk mid-write destroys that record, so the content
    goes to a temporary file in the same directory, is flushed all the way to
    the platter, and only then replaces the original. os.replace is atomic on
    both Windows and POSIX, so a reader either sees the whole old file or the
    whole new one.

    The written format_version is always this build's PROJECT_FORMAT_VERSION,
    never `project.format_version` (which only records what the file held when
    it was read). A project opened at an older format and re-saved now carries
    whatever this build's format added -- e.g. filter_cards at format 2 -- and
    must say so, or an older build's "refuse a newer format" guard cannot tell
    the file is no longer safe for it to open (issue #343).
    """
    project.touch()
    project_path = os.path.abspath(project_path)
    # Created eagerly, not just on first result-set write, so a
    # pre-computed cache can be copied in before anything is ever calculated.
    os.makedirs(cache_folder(project_path), exist_ok=True)

    payload = project.to_dict()
    payload["format_version"] = PROJECT_FORMAT_VERSION
    return write_json_atomic(project_path, payload)


def load_project(project_path: str) -> NVHProject:
    """
    Reads a project file.

    Refuses project format versions outside the readable range before building
    the model. Reading never writes or migrates the file (ADR §1.140).
    """
    with open(project_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict) or data.get("format") != "nvhproject":
        raise ProjectFormatError(f"Not an NVH project file: {project_path}")

    file_version = int(data.get("format_version", 0))
    if file_version < OLDEST_READABLE_PROJECT_FORMAT_VERSION:
        raise ProjectFormatError(
            "Project was created by an older Spectra; this release cannot read it "
            f"(project format version {file_version}, oldest readable "
            f"{OLDEST_READABLE_PROJECT_FORMAT_VERSION}). Create a new project."
        )
    if file_version > PROJECT_FORMAT_VERSION:
        raise ProjectFormatError(
            f"Project was written by a newer Spectra (project format version {file_version}, "
            f"this release reads up to {PROJECT_FORMAT_VERSION}). Update Spectra to open it."
        )

    return NVHProject.from_dict(data)


def project_folder(project_path: str) -> str:
    return os.path.dirname(os.path.abspath(project_path))


def cache_folder(project_path: str) -> str:
    """Folder holding the HDF5 result sets for this project."""
    return os.path.join(project_folder(project_path), CACHE_DIR_NAME)


def scan_cache_folder(project_path: str) -> str:
    """Folder holding this project's per-folder scan caches (ADR §1.22)."""
    return os.path.join(cache_folder(project_path), SCAN_CACHE_DIR_NAME)


def untitled_scan_cache_folder() -> str:
    """
    Scan cache location for a project with no file yet.

    An Untitled project has no folder of its own, but a big data folder should
    not be re-parsed on every rescan while the user is still deciding whether
    to save. The caches go to a shared temp area keyed by data-folder identity;
    ProjectSession.save_as copies the relevant ones into the project's own
    cache/scan/ on the first save (ADR §1.22).
    """
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "NVH_Tool", "untitled_scan")


def prune_untitled_scan_cache(max_age_days: int = UNTITLED_SCAN_CACHE_MAX_AGE_DAYS) -> None:
    """
    Drops stale Untitled scan caches. Best-effort: called once at startup, and
    a failure here must never stop the application from opening.
    """
    folder = untitled_scan_cache_folder()
    cutoff = time.time() - max_age_days * 86400
    try:
        entries = os.listdir(folder)
    except OSError:
        return
    for name in entries:
        path = os.path.join(folder, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# path resolution
# ---------------------------------------------------------------------------

def resolve_root(project_path: Optional[str], root: DataRoot) -> Optional[str]:
    """
    Turns a data root back into a real folder, or None if it cannot be found.

    Tries the relative form first, because that is what makes a project
    portable: copy the project and its data together and the relative path
    still lands. The absolute fallback covers the common case where only the
    project file was moved and the data never left its original location.

    A project that has never been saved has no folder to be relative to, so it
    carries absolute roots only and the relative step is skipped."""
    if project_path and root.relpath:
        candidate = os.path.abspath(os.path.join(project_folder(project_path), root.relpath))
        if os.path.isdir(candidate):
            return candidate

    if root.absolute_fallback and os.path.isdir(root.absolute_fallback):
        return os.path.abspath(root.absolute_fallback)

    return None


def adopt_untitled_scan_caches(project_path: str, data_roots: Sequence[Union[DataRoot, str]]) -> List[str]:
    """
    Moves scan caches built while the project was Untitled into its own
    cache/scan/ folder, so the first rescan after a save is a cache hit
    rather than a full re-parse (ADR §1.22).

    Only the caches for this project's data roots are taken: the temp area
    is shared and may hold caches for folders that belong to a different
    session.
    """
    source_folder = untitled_scan_cache_folder()
    if not os.path.isdir(source_folder):
        return []
    target_folder = scan_cache_folder(project_path)
    os.makedirs(target_folder, exist_ok=True)
    adopted: List[str] = []
    for root in data_roots:
        if isinstance(root, str):
            resolved = os.path.abspath(root) if os.path.isabs(root) else (
                os.path.normpath(os.path.join(os.path.dirname(project_path), root))
                if project_path else os.path.abspath(root)
            )
        else:
            resolved = resolve_root(project_path, root)
        if not resolved:
            continue
        name = scan_cache_basename(resolved)
        source = os.path.join(source_folder, name)
        if not os.path.isfile(source):
            continue
        try:
            shutil.copy2(source, os.path.join(target_folder, name))
            os.remove(source)
            adopted.append(name)
        except OSError:
            pass
    return adopted


def make_root(project_path: Optional[str], directory: str, label: str = "") -> DataRoot:
    """
    Builds a data root for a folder, expressed relatively where that is possible.

    Two cases leave the relative form empty: an unsaved project, which has no
    folder to be relative to yet, and a folder on another Windows drive, since
    a relative path cannot cross volumes. Neither is an error -- the root still
    resolves through its absolute form. reanchor_roots() fills the relative
    form in once the project is given a location.
    """
    directory = os.path.abspath(directory)
    relpath = _relative_or_blank(directory, project_path)

    return DataRoot(
        relpath=relpath,
        absolute_fallback=directory,
        label=label or os.path.basename(directory),
    )


def _relative_or_blank(directory: str, project_path: Optional[str]) -> str:
    if not project_path:
        return ""
    try:
        return os.path.relpath(directory, project_folder(project_path))
    except ValueError:
        # Different Windows drive; no relative path exists.
        return ""


def reanchor_roots(project: NVHProject,
                   old_project_path: Optional[str],
                   new_project_path: str) -> None:
    """
    Re-expresses every data root against the project's new location.

    Must run whenever the project file gains or changes a folder -- the first
    save of an unsaved project, and any Save As into a different directory.
    Without it a root keeps a relative path measured from where the project
    used to be, which after the move points somewhere else entirely and makes
    the measurements look like they have all vanished.

    Each root is resolved through its old anchor first, so what gets stored is
    where the folder actually is now rather than a path rewritten blindly. A
    root that cannot be resolved is left untouched: it is already broken, and
    overwriting it would destroy the only record of what it was looking for.
    """
    for root in project.data_roots:
        directory = resolve_root(old_project_path, root)
        if directory is None:
            continue
        root.relpath = _relative_or_blank(directory, new_project_path)
        root.absolute_fallback = directory


def reconcile_root(project: NVHProject, project_path: Optional[str],
                   directory: str, label: str = "",
                   *, root_directories: Mapping[str, Optional[str]],
                   ) -> Tuple[DataRoot, bool]:
    """
    The root standing for `directory`, and whether finding it changed the project.

    Roots are matched by the folder they resolve to, not by their stored
    spelling. A project file moved without its data reaches the folder through
    the absolute fallback while its relative path points somewhere that no
    longer exists (#314); comparing spellings made every rescan of such a
    folder a second root with a fresh, empty entry per file. The matched root
    is re-expressed from where the project is now, and any further roots
    resolving to the same folder -- saved while that bug was live -- are
    folded into it. Only a folder no root resolves to gets a new one.

    `root_directories` is a snapshot from read_root_directories(), so nothing
    here touches the disk.
    """
    fresh = make_root(project_path, directory, label)
    target = canonical_path(fresh.absolute_fallback)
    resolved = [(root, resolve_root_in(root_directories, root)) for root in project.data_roots]
    matches = [
        root for root, folder in resolved
        if folder is not None and canonical_path(folder) == target
    ]
    if not matches:
        return project.add_root(fresh), False

    keep = matches[0]
    changed = (keep.relpath, keep.absolute_fallback) != (fresh.relpath, fresh.absolute_fallback)
    keep.relpath = fresh.relpath
    keep.absolute_fallback = fresh.absolute_fallback
    for duplicate in matches[1:]:
        project.merge_root(keep, duplicate)
        changed = True
    return keep, changed


# ---------------------------------------------------------------------------
# indexing
# ---------------------------------------------------------------------------

@dataclass
class IndexReport:
    """
    What an index pass changed, so the caller can tell the user something useful.

    `renamed` and `missing` are kept apart deliberately: a renamed file keeps
    its metadata and its place in every result set, while a missing one is a
    question only the user can answer.
    """
    added: List[SourceEntry] = field(default_factory=list)
    updated: List[SourceEntry] = field(default_factory=list)
    renamed: List[Tuple[str, str]] = field(default_factory=list)   # (old relpath, new relpath)
    unchanged: List[SourceEntry] = field(default_factory=list)
    missing: List[SourceEntry] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.renamed or self.missing)


@dataclass(frozen=True)
class DirectoryIndex:
    """
    What registering one folder needs from disk, read in a worker so the GUI
    thread can reconcile the project without touching the file system.

    `root_directories` is where each project root resolved when the snapshot
    was taken (read_root_directories); `file_listing` maps every measurement
    file in the folder to its stamp.
    """
    file_listing: Mapping[str, Optional[dict]]
    root_directories: Mapping[str, Optional[str]]


def read_root_directories(project_path: Optional[str],
                          roots: Sequence[DataRoot]) -> Dict[str, Optional[str]]:
    """Where each root resolves on disk now, by root id. Safe off the GUI thread."""
    return {root.id: resolve_root(project_path, root) for root in roots}


def resolve_root_in(root_directories: Mapping[str, Optional[str]], root: DataRoot) -> Optional[str]:
    """A root's folder from a snapshot. A root added after the snapshot was
    made from a folder that existed then, so its absolute fallback stands."""
    return root_directories.get(root.id, root.absolute_fallback)


def build_sources_by_path(roots: Sequence[DataRoot], sources: Sequence[SourceEntry],
                          root_directories: Mapping[str, Optional[str]]) -> Dict[str, SourceEntry]:
    """
    Every source whose root resolves, keyed by its canonical path on this
    machine. Pure, so a worker can run it over copies of the project's roots
    and sources.

    The sources are bucketed by root_id once rather than re-scanned for every
    root: the nested walk was O(roots x sources) per call.
    """
    sources_by_root: Dict[str, list] = {}
    for entry in sources:
        sources_by_root.setdefault(entry.root_id, []).append(entry)

    by_path: Dict[str, SourceEntry] = {}
    for root in roots:
        directory = resolve_root_in(root_directories, root)
        if directory is None:
            continue
        for entry in sources_by_root.get(root.id, ()):
            # First root wins, the same tie-break source_for_path() makes,
            # so the pool and the cache never pick different entries.
            by_path.setdefault(canonical_path(os.path.join(directory, entry.relpath)), entry)
    return by_path


def read_file_listing(directory: str) -> Dict[str, Optional[dict]]:
    """Every measurement file in a folder with its stamp. Safe off the GUI thread."""
    return {path: file_stamp(path) for path in discover_measurement_files(directory)}


def read_directory_index(directory: str, project_path: Optional[str],
                         roots: Sequence[DataRoot]) -> DirectoryIndex:
    """The synchronous DirectoryIndex, for callers that are not in a worker."""
    return DirectoryIndex(read_file_listing(directory), read_root_directories(project_path, roots))


def index_root(project: NVHProject, project_path: Optional[str], root: DataRoot) -> IndexReport:
    """
    Brings the project's source list in line with what is actually in a folder.

    Reads the folder from disk; index_root_listing() does the matching.
    """
    directory = resolve_root(project_path, root)
    if directory is None:
        # Nothing to compare against: report every known source as missing
        # rather than guessing, so the caller can prompt for the folder.
        return IndexReport(missing=[s for s in project.sources if s.root_id == root.id])
    return index_root_listing(project, root, directory, read_file_listing(directory))


def index_root_listing(project: NVHProject, root: DataRoot, directory: str,
                       file_listing: Mapping[str, Optional[dict]]) -> IndexReport:
    """
    index_root() over a listing of `directory` already read from disk.

    Matching runs in two passes. Path first, which handles every ordinary case.
    Then, for files that no path matched, size and modification time are used to
    recognise a file that was only renamed -- the alternative is treating it as
    a brand new source, which would silently orphan the user's metadata and
    every result already computed for it.

    The stamp is a weak identity and two untouched copies of the same recording
    do collide, so a stamp match is only ever consumed once and only considered
    for entries whose own path has gone missing.
    """
    report = IndexReport()
    known = [s for s in project.sources if s.root_id == root.id]

    matched_ids: set = set()
    unmatched_paths: List[Tuple[str, dict]] = []

    # --- pass 1: match by path ---
    for absolute, stamp in file_listing.items():
        relpath = os.path.relpath(absolute, directory)
        if stamp is None:
            continue

        entry = project.source_by_relpath(root.id, relpath)
        if entry is None:
            unmatched_paths.append((relpath, stamp))
            continue

        matched_ids.add(entry.id)
        if entry.stamp_matches(stamp["size"], stamp["mtime_ns"]):
            report.unchanged.append(entry)
        else:
            entry.size_bytes = stamp["size"]
            entry.mtime_ns = stamp["mtime_ns"]
            report.updated.append(entry)

    # --- pass 2: the leftovers may be renames ---
    orphans = [s for s in known if s.id not in matched_ids]

    for relpath, stamp in unmatched_paths:
        twin = next(
            (s for s in orphans
             if s.stamp_matches(stamp["size"], stamp["mtime_ns"])),
            None,
        )
        if twin is not None:
            orphans.remove(twin)
            matched_ids.add(twin.id)
            report.renamed.append((twin.relpath, relpath))
            twin.relpath = relpath
            continue

        entry = SourceEntry(
            root_id=root.id,
            relpath=relpath,
            size_bytes=stamp["size"],
            mtime_ns=stamp["mtime_ns"],
        )
        project.add_source(entry)
        report.added.append(entry)

    report.missing = orphans
    return report


def index_all_roots(project: NVHProject, project_path: Optional[str]) -> Dict[str, IndexReport]:
    """Runs index_root over every root; returns one report per root id."""
    return {root.id: index_root(project, project_path, root) for root in project.data_roots}


def create_project(project_path: str, name: str = "", data_directory: str = "") -> NVHProject:
    """
    Builds a new project, optionally seeded with one data folder already indexed.

    Does not write anything: the caller decides when to save, so an abandoned
    "New Project" dialog leaves no file behind.
    """
    project = NVHProject(
        name=name or os.path.splitext(os.path.basename(project_path))[0],
    )

    if data_directory:
        root = project.add_root(make_root(project_path, data_directory))
        index_root(project, project_path, root)

    return project
