"""
The per-folder scan cache: the directory scan that fills it, and the reading
and writing of the JSON file that survives between sessions.

`measurement_files.py` holds the file-level facts this builds on -- which
extensions count, how a path is keyed, what a file's cheap identity is.
"""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from core.models import ChannelMetadata, LostPart, MeasurementRunIndex, UnreadableFile
from core.project_model import DataRoot, SourceEntry
from io_modules.measurement_files import (
    canonical_path,
    discover_measurement_files,
    file_stamp,
    open_measurement_reader,
    scan_cache_basename,
)
from io_modules.import_template import resolve_template_cache_key
from io_modules.metadata_parser import AccMetadataParser, build_normalized_lookup, normalize_file_key
from io_modules.metadata_schema import generate_baseline_schema_master, resolve_excel_metadata_for_files
from io_modules.project_store import DirectoryIndex, read_root_directories, resolve_root_in


# Cap on parallel header parses in read_pool_folder. Measured 2026-09-03 on a
# real 131 MB / 17-channel UNV: 1/2/5 workers = 156/305/749 MB peak and
# 0.84/1.66/4.11 s -- memory grows ~150 MB/worker and time grows linearly too
# (the GIL keeps pyuff serialised, so there is no throughput gain). The unbounded
# default (min(32, cpu+4) = 28 here) turns a folder of 28 large UNVs into a ~4.4 GB
# spike for zero saved seconds. Kept > 1 so I/O wait on a network share can still
# overlap. Do not "optimise" this back to the default -- audit 02 finding 5.3.
_SCAN_PARSE_MAX_WORKERS = 4


# Bumped whenever the shape of _workspace_runs_data entries changes (a field
# renamed or removed in MeasurementRunIndex/ChannelMetadata.to_dict()). Without
# this, a cache written by an older version would be loaded as if still valid
# and fed to from_dict() as-is -- the same class of problem the order-cut cache
# already guards against with DSP_ALGORITHM_VERSIONS.
# 2: metadata schema fields carry a typed `kind`
# 3: UNV 58b channel units read by column, not by whitespace split (issue #323)
# 4: Imported channels carry their readable block kind for navigation (#496).
# 5: MASTA channels carry their header as Raw metadata (#520).
# 6: MASTA workbooks read every H<order> sheet, not only the first (#639).
# 7: A run remembers the datasets it could not read (#722).
# 8: An ANSYS CSV remembers the rows it dropped (#723).
# 9: A MASTA channel remembers its lost rows; a gap inside a column is one (§1.177).
# 10: The cached schema only ever gained fields, so an older one still lists Raw
#     metadata fields no channel carries (#764).
# 11: A run remembers the Import template it was read by; a changed assignment re-reads it (#862).
WORKSPACE_CACHE_FORMAT_VERSION = 11

# The scan cache's name when it is written beside the data -- only when no
# cache folder is passed, which production never does.
WORKSPACE_CACHE_FILE_NAME = ".nvh_workspace_cache.json"


def _stamps_match(cached: Optional[dict], current: Optional[dict]) -> bool:
    if not cached or not current:
        return False
    return (cached.get("mtime_ns") == current.get("mtime_ns")
            and cached.get("size") == current.get("size"))


@dataclass
class _CacheLoadResult:
    """
    What survived a cache read.

    `runs` holds only entries still believed to describe the file on disk, so the
    caller re-parses whatever is missing. `metadata_is_stale` means the Excel
    sheet changed and every run needs re-linking, so the caller cannot simply
    return early.

    `parent_source` is the dataset-root sheet the scan should link against: the
    one the caller passed, or -- when the caller did not know it -- the one the
    cache remembers from the ingest that reached this folder through its root.
    """
    runs: Dict[str, MeasurementRunIndex] = field(default_factory=dict)
    schema_master: dict = field(default_factory=dict)
    metadata_is_stale: bool = False
    parent_source: Optional[str] = None
    # Why the cache was not usable as a whole, when that is worth telling the user.
    problem: Optional[str] = None


class ScannedDirectory(NamedTuple):
    """
    What one scan of a Data Pool folder found, handed from the worker to the
    GUI thread.

    `index` is the folder's DirectoryIndex, so registering it with the project
    touches no disk. `unreadable` are the files that could not be read -- never
    cached, so the next scan tries them again -- and `messages` what the scan
    has to say; both are carried as data, because the scan runs on a worker
    and never writes to the log itself.
    """
    runs: list
    schema: dict
    index: DirectoryIndex
    unreadable: Tuple[UnreadableFile, ...] = ()
    messages: Tuple[str, ...] = ()


def read_pool_folder(directory_path: str, *, cache_dir: Optional[str] = None,
                     primary_excel_path: Optional[str] = None,
                     parent_excel_path: Optional[str] = None,
                     progress_fn: Optional[Callable[[int, int], None]] = None,
                     project_path: Optional[str] = None,
                     roots: Sequence[DataRoot] = (),
                     sources: Sequence[SourceEntry] = (),
                     assigned_templates: Optional[Mapping[str, str]] = None) -> ScannedDirectory:
    """
    Reads a Data Pool folder's measurements. Safe to call off the GUI thread.

    Touches neither the project nor the pool -- it only returns what the folder
    says, so the caller can run it on a worker while the window stays
    responsive and integrate the result afterwards. `roots` are copies taken on
    the calling thread, not live project objects. `sources` likewise: the
    Import template a source assigns to a file picks the reader that scans it.
    `assigned_templates` (file path -> template name) is what the Add being run
    assigns to files that have no source yet; it wins over `sources`.

    `cache_dir` is where the scan cache lives -- a project's cache/scan/ or the
    Untitled temp area, chosen by the caller who knows the project state
   . None keeps the legacy behaviour of writing beside the data;
    production always passes a directory, the None branch only carries the
    invalidation tests.

    `progress_fn(done, total)` is invoked as stale files are re-parsed, so a
    caller driving a progress bar over one folder of large files sees it move
    rather than jump. Must be safe to call from a worker thread.

    A file that fails to parse is reported in the result's `unreadable`
    rather than dropped. It is never cached, so every scan tries it again.
    """
    file_listing: dict = {}
    root_directories = read_root_directories(project_path, roots)
    import_templates = _resolve_import_templates(roots, sources, root_directories)
    import_templates.update({canonical_path(path): name for path, name in (assigned_templates or {}).items()})
    runs, schema, unreadable, messages = _scan_folder(
        directory_path, cache_dir, primary_excel_path, parent_excel_path, progress_fn, file_listing,
        import_templates)
    return ScannedDirectory(
        runs, schema, DirectoryIndex(file_listing, root_directories), unreadable, messages)


def _resolve_import_templates(roots: Sequence[DataRoot], sources: Sequence[SourceEntry],
                              root_directories) -> Dict[str, str]:
    """Assigned Import template by canonical file path, for the sources that have one."""
    templates: Dict[str, str] = {}
    for root in roots:
        directory = resolve_root_in(root_directories, root)
        if directory is None:
            continue
        for entry in sources:
            if entry.root_id == root.id and entry.import_template:
                templates.setdefault(canonical_path(os.path.join(directory, entry.relpath)),
                                     entry.import_template)
    return templates


def _metadata_sources(directory_path: str, primary_excel_path: Optional[str],
                      parent_excel_path: Optional[str]) -> Tuple[Optional[str], str, Optional[str]]:
    """
    The Excel sheets that can supply run-level metadata for a folder.

    `primary_excel_path` is the project's own metadata.xlsx, the same for
    every data root in the project -- passed in by the caller, not derived
    from `directory_path`. The folder-adjacent Metadata.xlsx is always the
    fallback now: it fills in files the primary sheet does not know about.

    `parent_excel_path` is a second fallback, one level lower priority than
    the folder-adjacent one: the sheet found at the root folder a caller
    recursed from to reach `directory_path` (e.g. a dataset root sitting
    above per-run subfolders). It fills in only what neither the primary
    nor the folder-local sheet already answered.
    """
    fallback = os.path.join(directory_path, "Metadata.xlsx")
    return primary_excel_path, fallback, parent_excel_path


def _scan_folder(directory_path: str, cache_dir: Optional[str],
                 primary_excel_path: Optional[str], parent_excel_path: Optional[str],
                 progress_fn: Optional[Callable[[int, int], None]], file_listing: dict,
                 import_templates: Mapping[str, str]):
    """
    `(runs, schema, unreadable, messages)` for one folder, served from the scan
    cache where the files are unchanged.

    `file_listing` receives every discovered path and its stamp, including
    files that fail to parse and cache hits, so the caller can reconcile source
    entries without another directory walk.
    """
    messages: List[str] = []

    if not os.path.exists(directory_path):
        return [], {}, (), ()

    discovered_files = _with_assigned_files(
        discover_measurement_files(directory_path), directory_path, import_templates)
    file_listing.update({path: file_stamp(path) for path in discovered_files})
    if not discovered_files:
        return [], {}, (), ()

    if cache_dir is None:
        cache_path = os.path.join(directory_path, WORKSPACE_CACHE_FILE_NAME)
    else:
        cache_path = os.path.join(cache_dir, scan_cache_basename(directory_path))
    primary_source, fallback_source, parent_source = _metadata_sources(
        directory_path, primary_excel_path, parent_excel_path)

    cached = _read_workspace_cache(
        cache_path, discovered_files, primary_source, fallback_source, parent_source, import_templates)
    cached_runs = cached.runs
    if cached.problem:
        messages.append(cached.problem)
    # A folder refresh does not know which dataset root the folder was
    # reached from; the cache does (issue #324).
    parent_source = cached.parent_source

    # Only files whose stamp no longer matches need re-reading. Re-parsing a
    # whole folder because one measurement was overwritten is expensive when
    # a single .unv runs to a hundred megabytes.
    stale_files = [path for path in discovered_files if path not in cached_runs]

    if cached_runs and not stale_files and not cached.metadata_is_stale:
        return ([cached_runs[path] for path in discovered_files],
                cached.schema_master, (), tuple(messages))

    metadata_lookup = _build_excel_metadata_lookup(
        discovered_files, primary_source, parent_source, fallback_source, messages.append)

    parsed_runs = {}
    unreadable: List[UnreadableFile] = []
    if stale_files:
        total = len(stale_files)
        if progress_fn is not None:
            progress_fn(0, total)
        with ThreadPoolExecutor(max_workers=_SCAN_PARSE_MAX_WORKERS) as executor:
            for done, (path, run_index, reason) in enumerate(
                    executor.map(lambda path: _parse_outcome(path, import_templates.get(canonical_path(path), "")),
                                 stale_files), start=1):
                if run_index:
                    parsed_runs[run_index.file_path] = run_index
                else:
                    unreadable.append(UnreadableFile(path, reason))
                if progress_fn is not None:
                    progress_fn(done, total)

    indexed_runs = _index_scanned_runs(
        discovered_files, parsed_runs, cached_runs, metadata_lookup, cached.metadata_is_stale)

    # Keep whatever the user customised in the metadata editor and add only
    # fields that are newly discovered. Regenerating from scratch on every
    # rescan would silently throw away their labels and visibility flags.
    schema_master = dict(cached.schema_master or {})
    for key, definition in generate_baseline_schema_master(indexed_runs).items():
        schema_master.setdefault(key, definition)

    if cache_dir is not None:
        os.makedirs(cache_dir, exist_ok=True)

    if not _write_workspace_cache(cache_path, indexed_runs, schema_master,
                                  primary_source, fallback_source, parent_source, import_templates):
        # The in-memory scan is still good and is returned as-is; only the
        # on-disk cache is stale. Saying so matters because the next start
        # will silently re-parse the whole folder -- a confusing slowdown
        # with no other trace if the write failure is swallowed here.
        messages.append(f"CACHE_IO: Folder index could not be written to {cache_path}; "
                        f"this folder will be re-parsed in full on the next open.")
    return indexed_runs, schema_master, tuple(unreadable), tuple(messages)


def _link_run_metadata(run_index: MeasurementRunIndex, metadata_lookup: dict) -> dict:
    """Matches a run to its Excel row by exact, case-insensitive filename identity."""
    return metadata_lookup.get(normalize_file_key(run_index.file_name), {})


def _build_excel_metadata_lookup(discovered_files: List[str], primary_source: Optional[str],
                                 parent_source: Optional[str], fallback_source: str,
                                 log_fn: Callable[[str], None]) -> dict:
    """
    Layers the project-wide sheet, the dataset-root sheet and the folder-local
    Metadata.xlsx into one filename -> metadata lookup.

    Parent sheet first, folder-local fallback on top: a recursed-into child
    folder inherits whatever the dataset-root sheet says, but its own
    Metadata.xlsx (if any) wins on a key both define.
    """
    primary_lookup = {}
    if primary_source and os.path.exists(primary_source):
        primary_lookup = build_normalized_lookup(AccMetadataParser(primary_source).parse_and_link_metadata())

    fallback_lookup = {}
    if parent_source and os.path.exists(parent_source):
        fallback_lookup.update(
            build_normalized_lookup(AccMetadataParser(parent_source).parse_and_link_metadata()))
    if os.path.exists(fallback_source):
        fallback_lookup.update(
            build_normalized_lookup(AccMetadataParser(fallback_source).parse_and_link_metadata()))

    return resolve_excel_metadata_for_files(
        (os.path.basename(path) for path in discovered_files), primary_lookup, fallback_lookup, log_fn,
    )


def _index_scanned_runs(discovered_files: List[str], parsed_runs: dict, cached_runs: dict,
                        metadata_lookup: dict, metadata_is_stale: bool) -> List[MeasurementRunIndex]:
    """
    Merges freshly parsed runs with still-valid cached ones, in folder order.

    A cached run already carries its linked metadata; re-link only what was
    just parsed, or everything when either Excel sheet changed.
    """
    indexed_runs: List[MeasurementRunIndex] = []
    for path in discovered_files:
        run_index = parsed_runs.get(path) or cached_runs.get(path)
        if run_index is None:
            continue
        if path in parsed_runs or metadata_is_stale:
            run_index.metadata = _link_run_metadata(run_index, metadata_lookup)
        indexed_runs.append(run_index)
    return indexed_runs


def _with_assigned_files(discovered: List[str], directory_path: str,
                         import_templates: Mapping[str, str]) -> List[str]:
    """
    The discovered files plus those in the folder with an assigned Import
    template that discovery did not recognise. A generic-suffix file counts
    as a measurement by its header; one that no longer fits its template would
    otherwise drop out of the scan unseen, and the pool keep its old reading.
    Read by its template, it fails and is reported as an Unreadable file.
    """
    if not import_templates:
        return discovered
    known = {canonical_path(path) for path in discovered}
    try:
        names = os.listdir(directory_path)
    except OSError:
        return discovered
    extra = [path for path in (os.path.join(directory_path, name) for name in names)
             if canonical_path(path) in import_templates and canonical_path(path) not in known
             and os.path.isfile(path)]
    return sorted(discovered + extra) if extra else discovered


def _parse_outcome(file_path: str, import_template: str = ""):
    """
    `(path, run, reason)`: the parsed run, or None and why the file could not
    be read -- naming the Import template it was read with, if any.
    """
    try:
        run_index = _parse_measurement_file(file_path, import_template)
        reason = "" if run_index is not None else "The file could not be read."
    except Exception as e:
        run_index, reason = None, str(e) or type(e).__name__
    if run_index is not None:
        return file_path, run_index, ""
    if import_template:
        reason = f"does not fit the Import template {import_template}: {reason}"
    return file_path, None, reason


def _parse_measurement_file(file_path: str, import_template: str = "") -> MeasurementRunIndex:
    """
    Isolated multi-threaded worker routing to the correct parsing engine dynamically.
    Raises when the file cannot be read; `_parse_outcome` turns that into a reason.
    """
    reader = open_measurement_reader(file_path, import_template)

    run_index = reader.scan_file_structure()
    reader.load_channels_on_demand(run_index)
    return run_index


def _resolve_read_by(import_templates: Optional[Mapping[str, str]], file_path: str) -> str:
    """
    What a cache entry records of how its file was read: the assigned Import
    template with a fingerprint of its copy, the bare name when nobody holds a
    copy, blank for none -- so a newly assigned or edited template re-reads it.
    """
    name = (import_templates or {}).get(canonical_path(file_path), "")
    return resolve_template_cache_key(name) or name


def _write_workspace_cache(cache_path: str, indexed_runs: List[MeasurementRunIndex],
                           schema_master: dict, primary_source: Optional[str] = None,
                           fallback_source: Optional[str] = None,
                           parent_source: Optional[str] = None,
                           import_templates: Optional[Mapping[str, str]] = None) -> bool:
    """
    Writes the folder index to disk. Returns True on success.

    A failed write is reported, not raised: the cache is derived data and
    the caller's in-memory scan is unaffected, so the scan must still
    succeed. But the caller has to know the write failed to warn about the
    re-parse it now can't avoid on the next open.
    """
    import pandas as pd
    try:
        runs_data = {}
        for run in indexed_runs:
            channels_map = {}
            for key, meta in run.available_channels.items():
                dt = getattr(meta, 'abscissa_inc', 0.0)
                calculated_fs = float(1.0 / dt) if dt > 0.0 else 0.0
                # Serialization must not mutate the live model -- write the
                # derived rate into the exported dict copy only.
                channel_dict = meta.to_dict()
                channel_dict['sampling_rate'] = calculated_fs
                channels_map[key] = channel_dict

            clean_metadata = {}
            if getattr(run, 'metadata', None) and isinstance(run.metadata, dict):
                for m_key, m_val in run.metadata.items():
                    if isinstance(m_val, pd.Timestamp):
                        clean_metadata[m_key] = m_val.strftime("%Y-%m-%d %H:%M:%S")
                    elif hasattr(m_val, 'item'):
                        clean_metadata[m_key] = m_val.item()
                    else:
                        clean_metadata[m_key] = m_val

            runs_data[canonical_path(run.file_path)] = {
                "file_name": run.file_name,
                # Kept alongside the canonical key so the original spelling
                # survives for anything that reads it back.
                "file_path": run.file_path,
                "id1": getattr(run, 'id1', None),
                "id2": getattr(run, 'id2', None),
                "id3": getattr(run, 'id3', None),
                "id4": getattr(run, 'id4', None),
                "id5": getattr(run, 'id5', None),
                "metadata": clean_metadata,
                "channels": channels_map,
                "lost_parts": [{"dataset": part.dataset, "reason": part.reason}
                               for part in run.lost_parts],
                # What this entry was built from. Without it the cache had no
                # way to notice a file had been re-measured and kept serving
                # the old channel list until it was deleted by hand.
                "source_stamp": file_stamp(run.file_path),
                "read_by": _resolve_read_by(import_templates, run.file_path),
            }

        composite_package = {
            "_cache_format_version": WORKSPACE_CACHE_FORMAT_VERSION,
            "_metadata_schema_master": schema_master,
            "_metadata_source_stamps": {
                "primary": file_stamp(primary_source) if primary_source else None,
                "fallback": file_stamp(fallback_source) if fallback_source else None,
                "parent": file_stamp(parent_source) if parent_source else None,
            },
            # The dataset-root sheet is not derivable from the folder, so its
            # path is kept too: a later rescan that does not pass it (folder
            # refresh, watcher) must still link against it.
            "_parent_metadata_source": parent_source,
            "_workspace_runs_data": runs_data
        }

        # Write-then-replace so a crash mid-write leaves the previous
        # cache intact instead of a truncated/corrupt JSON file.
        cache_dir = os.path.dirname(cache_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, prefix=".cache_tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(composite_package, f, indent=4)
            os.replace(tmp_path, cache_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        return True
    except Exception:
        return False


def _read_workspace_cache(cache_path: str, active_files: List[str],
                          primary_source: Optional[str] = None,
                          fallback_source: Optional[str] = None,
                          parent_source: Optional[str] = None,
                          import_templates: Optional[Mapping[str, str]] = None) -> _CacheLoadResult:
    """
    Reads the on-disk index and returns only the parts still valid.

    A run appears in the result only when the file it describes still has the
    modification time and size it had when cached, so a re-measured file is
    left out and gets re-parsed while its neighbours are served from cache.

    The Excel sheets are tracked separately from the measurement files:
    when only one of them has changed, every run needs its metadata
    re-linked but none of them need re-parsing, which is the difference
    between a moment and a minute.

    `parent_source=None` means "not known here", not "none": the dataset-root
    sheet recorded by an earlier scan is adopted and returned in the result.
    """
    def _current_stamps(parent: Optional[str]) -> dict:
        return {
            "primary": file_stamp(primary_source) if primary_source else None,
            "fallback": file_stamp(fallback_source) if fallback_source else None,
            "parent": file_stamp(parent) if parent else None,
        }

    def _cold_miss(**kwargs) -> _CacheLoadResult:
        return _CacheLoadResult(metadata_is_stale=any(_current_stamps(parent_source).values()),
                               parent_source=parent_source, **kwargs)

    if not os.path.exists(cache_path):
        return _cold_miss()

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            composite_package = json.load(f)

        if (not isinstance(composite_package, dict)
                or composite_package.get("_cache_format_version") != WORKSPACE_CACHE_FORMAT_VERSION):
            # Older/newer entry shape than this build expects -- treat as a
            # full miss rather than risk feeding an incompatible dict to
            # ChannelMetadata.from_dict()/MeasurementRunIndex. The next
            # _write_workspace_cache() call re-stamps the current version.
            return _cold_miss()
        schema_master = composite_package.get("_metadata_schema_master", {})
        cached_parent_source = composite_package.get("_parent_metadata_source")
        cached_stamps = composite_package.get("_metadata_source_stamps") or {}
        cache_data = composite_package["_workspace_runs_data"]

        if parent_source is None:
            parent_source = cached_parent_source
        current_stamps = _current_stamps(parent_source)

        def _slot_stale(cached_stamp, current_stamp) -> bool:
            if cached_stamp is None and current_stamp is None:
                return False
            return not _stamps_match(cached_stamp, current_stamp)

        # A different dataset-root sheet than the one the runs were linked
        # against is stale even if its stamp happens to match.
        parent_moved = (
            (canonical_path(parent_source) if parent_source else None)
            != (canonical_path(cached_parent_source) if cached_parent_source else None)
        )
        metadata_is_stale = (
            _slot_stale(cached_stamps.get("primary"), current_stamps["primary"])
            or _slot_stale(cached_stamps.get("fallback"), current_stamps["fallback"])
            or _slot_stale(cached_stamps.get("parent"), current_stamps["parent"])
            or parent_moved
        )

        # Re-key whatever spelling the file on disk happens to use, so a cache
        # written through one path form is still found through another.
        cache_by_key = {canonical_path(key): entry for key, entry in cache_data.items()}

        loaded_runs: Dict[str, MeasurementRunIndex] = {}

        for file_path in active_files:
            cached_run = cache_by_key.get(canonical_path(file_path))
            if not cached_run:
                continue

            if not _stamps_match(cached_run.get("source_stamp"), file_stamp(file_path)):
                continue
            if cached_run.get("read_by", "") != _resolve_read_by(import_templates, file_path):
                continue

            run_index = MeasurementRunIndex(cached_run["file_name"], file_path)
            run_index.metadata = cached_run.get("metadata", {})

            # A fresh parse only sets id1..id5 when the reader actually
            # discovered one (MeasurementRunIndex.__init__ leaves them
            # unset otherwise, so file_level_facts() omits them). Setting
            # them here even when cached as None would add the attribute
            # to __dict__ regardless, making a cache-loaded run disagree
            # with a fresh parse of the same untouched file and marking
            # the project dirty on reopen (#317).
            for id_key in ("id1", "id2", "id3", "id4", "id5"):
                id_value = cached_run.get(id_key)
                if id_value is not None:
                    setattr(run_index, id_key, id_value)

            for unique_label, ch_dict in cached_run.get("channels", {}).items():
                run_index.add_channel_metadata(unique_label, ChannelMetadata.from_dict(ch_dict))

            run_index.lost_parts = [LostPart(part["dataset"], part["reason"])
                                    for part in cached_run.get("lost_parts", [])]

            loaded_runs[file_path] = run_index

        return _CacheLoadResult(
            runs=loaded_runs,
            schema_master=schema_master,
            metadata_is_stale=metadata_is_stale,
            parent_source=parent_source,
        )
    except Exception as e:
        return _CacheLoadResult(
            metadata_is_stale=True, parent_source=parent_source,
            problem=f"CACHE_IO: Folder index could not be read ({e}); this folder is re-parsed in full.")
