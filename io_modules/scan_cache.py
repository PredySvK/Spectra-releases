"""
The per-folder scan cache: the directory scan that fills it, and the reading
and writing of the JSON file that survives between sessions (ADR §1.22).

`measurement_files.py` holds the file-level facts this builds on -- which
extensions count, how a path is keyed, what a file's cheap identity is.
"""

import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from core.models import ChannelMetadata, MeasurementRunIndex
from io_modules.measurement_files import (
    canonical_path,
    discover_measurement_files,
    file_stamp,
    open_measurement_reader,
)
from io_modules.metadata_parser import AccMetadataParser, build_normalized_lookup, normalize_file_key
from io_modules.metadata_schema import generate_baseline_schema_master, resolve_excel_metadata_for_files


# Cap on parallel header parses in quick_scan_directory. Measured 2026-09-03 on a
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
# 2: metadata schema fields carry a typed `kind` (ADR §1.1)
# 3: UNV 58b channel units read by column, not by whitespace split (issue #323)
# 4: Imported channels carry their readable block kind for navigation (#496).
# 5: MASTA channels carry their header as Raw metadata (#520).
WORKSPACE_CACHE_FORMAT_VERSION = 5


def scan_cache_basename(directory_path: str) -> str:
    """
    File name for a folder's scan cache when it lives in a shared cache folder
    (a project's cache/scan/, or the Untitled temp area) rather than beside the
    data (ADR §1.22).

    The folder's own basename is kept for readability ("setup1-a1b2c3d4.json");
    the short canonical-path hash keeps two roots with the same basename from
    colliding in one cache folder. Both halves are derived from canonical_path,
    so the same folder spelled with either separator or any case resolves to
    exactly one cache file -- the label is lower-cased as a side effect, which
    is a fair price for that guarantee.
    """
    canonical = canonical_path(directory_path)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]
    raw_base = os.path.basename(canonical.rstrip("/\\")) or "folder"
    safe_base = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw_base)[:40]
    return f"{safe_base}-{digest}.json"



def _stamps_match(cached: Optional[dict], current: Optional[dict]) -> bool:
    if not cached or not current:
        return False
    return (cached.get("mtime_ns") == current.get("mtime_ns")
            and cached.get("size") == current.get("size"))



@dataclass
class CacheLoadResult:
    """
    What survived a cache read.

    `runs` holds only entries still believed to describe the file on disk, so the
    caller re-parses whatever is missing. The two flags separate the two reasons
    the caller cannot simply return early: the Excel sheet changed and every run
    needs re-linking, or entries were adopted from a pre-stamp cache and must be
    written back with stamps before the next open can detect anything.

    `parent_source` is the dataset-root sheet the scan should link against: the
    one the caller passed, or -- when the caller did not know it -- the one the
    cache remembers from the ingest that reached this folder through its root.
    """
    runs: Dict[str, MeasurementRunIndex] = field(default_factory=dict)
    schema_master: dict = field(default_factory=dict)
    metadata_is_stale: bool = False
    needs_restamp: bool = False
    parent_source: Optional[str] = None


class MeasurementScanner:
    def __init__(self):
        self.cache_file_name = ".nvh_workspace_cache.json"

    def resolve_metadata_sources(self, directory_path: str,
                                 primary_excel_path: Optional[str] = None,
                                 parent_excel_path: Optional[str] = None,
                                 ) -> Tuple[Optional[str], str, Optional[str]]:
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

    def discover_measurement_files(self, directory_path: str) -> List[str]:
        """Lists every supported measurement file in a directory, case-insensitively."""
        return discover_measurement_files(directory_path)

    def quick_scan_directory(self, directory_path: str, primary_excel_path: Optional[str] = None,
                             log_fn: Optional[Callable[[str], None]] = None,
                             cache_dir: Optional[str] = None,
                             progress_fn: Optional[Callable[[int, int], None]] = None,
                             parent_excel_path: Optional[str] = None,
                             file_listing: Optional[dict] = None,
                             ) -> Tuple[List[MeasurementRunIndex], dict]:
        """
        `progress_fn(done, total)` is invoked as stale files are re-parsed, so a
        caller driving a progress bar over one folder of large files sees it
        move rather than jump. Must be safe to call from a worker thread.

        `file_listing`, when supplied, receives every discovered path and its
        stamp, including files that fail to parse and cache hits. It lets the
        caller reconcile source entries without another directory walk.

        `cache_dir` is where the scan cache lives -- a project's cache/scan/ or
        the Untitled temp area, chosen by the caller who knows the project state
        (ADR §1.22). None keeps the legacy behaviour of writing beside the data;
        production always passes a directory, the None branch only carries the
        invalidation tests.
        """
        log_fn = log_fn or print

        if not os.path.exists(directory_path):
            return [], {}

        discovered_files = self.discover_measurement_files(directory_path)
        if file_listing is not None:
            file_listing.update({path: file_stamp(path) for path in discovered_files})
        if not discovered_files:
            return [], {}

        if cache_dir is None:
            cache_path = os.path.join(directory_path, self.cache_file_name)
        else:
            cache_path = os.path.join(cache_dir, scan_cache_basename(directory_path))
        primary_source, fallback_source, parent_source = self.resolve_metadata_sources(
            directory_path, primary_excel_path, parent_excel_path)

        cached = self.load_workspace_cache(
            cache_path, discovered_files, primary_source, fallback_source, parent_source)
        cached_runs = cached.runs
        # A folder refresh does not know which dataset root the folder was
        # reached from; the cache does (issue #324).
        parent_source = cached.parent_source

        # Only files whose stamp no longer matches need re-reading. Re-parsing a
        # whole folder because one measurement was overwritten is expensive when
        # a single .unv runs to a hundred megabytes.
        stale_files = [path for path in discovered_files if path not in cached_runs]

        # needs_restamp has to be part of this: adopting a pre-stamp cache and
        # then returning early would never write the stamps back, leaving the
        # folder permanently unable to notice a file had changed.
        if cached_runs and not stale_files and not cached.metadata_is_stale and not cached.needs_restamp:
            return [cached_runs[path] for path in discovered_files], cached.schema_master

        metadata_lookup = self._build_excel_metadata_lookup(
            discovered_files, primary_source, parent_source, fallback_source, log_fn)

        parsed_runs = {}
        if stale_files:
            print(f"CACHE_IO: Re-parsing {len(stale_files)} of {len(discovered_files)} files "
                  f"({len(cached_runs)} still valid).")
            total = len(stale_files)
            if progress_fn is not None:
                progress_fn(0, total)
            with ThreadPoolExecutor(max_workers=_SCAN_PARSE_MAX_WORKERS) as executor:
                for done, run_index in enumerate(
                        executor.map(self._parse_single_file_worker, stale_files), start=1):
                    if run_index:
                        parsed_runs[run_index.file_path] = run_index
                    if progress_fn is not None:
                        progress_fn(done, total)

        indexed_runs = self._index_scanned_runs(
            discovered_files, parsed_runs, cached_runs, metadata_lookup, cached.metadata_is_stale)

        # Keep whatever the user customised in the metadata editor and add only
        # fields that are newly discovered. Regenerating from scratch on every
        # rescan would silently throw away their labels and visibility flags.
        schema_master = dict(cached.schema_master or {})
        for key, definition in generate_baseline_schema_master(indexed_runs).items():
            schema_master.setdefault(key, definition)

        if cache_dir is not None:
            os.makedirs(cache_dir, exist_ok=True)

        if not self.save_workspace_cache(cache_path, indexed_runs, schema_master,
                                         primary_source, fallback_source, parent_source):
            # The in-memory scan is still good and is returned as-is; only the
            # on-disk cache is stale. Saying so matters because the next start
            # will silently re-parse the whole folder -- a confusing slowdown
            # with no other trace if the write failure is swallowed here.
            log_fn(f"CACHE_IO: Folder index could not be written to {cache_path}; "
                   f"this folder will be re-parsed in full on the next open.")
        return indexed_runs, schema_master

    @staticmethod
    def _link_run_metadata(run_index: MeasurementRunIndex, metadata_lookup: dict) -> dict:
        """Matches a run to its Excel row by exact, case-insensitive filename identity."""
        return metadata_lookup.get(normalize_file_key(run_index.file_name), {})

    @staticmethod
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

    @classmethod
    def _index_scanned_runs(cls, discovered_files: List[str], parsed_runs: dict, cached_runs: dict,
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
                run_index.metadata = cls._link_run_metadata(run_index, metadata_lookup)
            indexed_runs.append(run_index)
        return indexed_runs

    def _parse_single_file_worker(self, file_path: str) -> MeasurementRunIndex:
        """
        Isolated multi-threaded worker routing to the correct parsing engine dynamically.
        """
        try:
            reader = open_measurement_reader(file_path)

            run_index = reader.scan_file_structure()
            reader.load_channels_on_demand(run_index)
            return run_index
        except Exception as e:
            print(f"PARALLEL_IO_ERROR: Failed processing file thread {os.path.basename(file_path)}. Trace: {str(e)}")
            return None

    def save_workspace_cache(self, cache_path: str, indexed_runs: List[MeasurementRunIndex],
                             schema_master: dict, primary_source: Optional[str] = None,
                             fallback_source: Optional[str] = None,
                             parent_source: Optional[str] = None) -> bool:
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
                    # What this entry was built from. Without it the cache had no
                    # way to notice a file had been re-measured and kept serving
                    # the old channel list until it was deleted by hand.
                    "source_stamp": file_stamp(run.file_path),
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
        except Exception as e:
            print(f"CACHE_WRITE_ERROR: Could not save structure cache to disk. Trace: {str(e)}")
            return False

    def load_workspace_cache(self, cache_path: str, active_files: List[str],
                             primary_source: Optional[str] = None,
                             fallback_source: Optional[str] = None,
                             parent_source: Optional[str] = None) -> CacheLoadResult:
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

        def _cold_miss(**kwargs) -> CacheLoadResult:
            return CacheLoadResult(metadata_is_stale=any(_current_stamps(parent_source).values()),
                                   parent_source=parent_source, **kwargs)

        if not os.path.exists(cache_path):
            return _cold_miss()

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                composite_package = json.load(f)

            if isinstance(composite_package, dict) and "_workspace_runs_data" in composite_package:
                cached_format_version = composite_package.get("_cache_format_version", 0)
                if cached_format_version != WORKSPACE_CACHE_FORMAT_VERSION:
                    # Older/newer entry shape than this build expects -- treat as a
                    # full miss rather than risk feeding an incompatible dict to
                    # ChannelMetadata.from_dict()/MeasurementRunIndex. The next
                    # save_workspace_cache() call re-stamps the current version.
                    return _cold_miss()
                schema_master = composite_package.get("_metadata_schema_master", {})
                cached_parent_source = composite_package.get("_parent_metadata_source")
                cached_stamps = composite_package.get("_metadata_source_stamps")
                if cached_stamps is None:
                    # Pre-dual-source cache format: one stamp for the (then
                    # single, folder-adjacent) Excel sheet.
                    cached_stamps = {"primary": None, "fallback": composite_package.get("_metadata_source_stamp")}
                cache_data = composite_package["_workspace_runs_data"]
            else:
                # Pre-schema cache format: the file was the runs mapping itself.
                schema_master = {}
                cached_stamps = {"primary": None, "fallback": None}
                cached_parent_source = None
                cache_data = composite_package

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
            needs_restamp = False

            for file_path in active_files:
                cached_run = cache_by_key.get(canonical_path(file_path))
                if not cached_run:
                    continue

                cached_stamp = cached_run.get("source_stamp")
                if cached_stamp is None:
                    # Written before stamps existed. Adopted rather than discarded:
                    # manual unit fixes made through the file explorer live only in
                    # this file, so dropping the entry would silently undo them the
                    # first time an existing workspace is opened after an upgrade.
                    # Flagged so the caller writes stamps back -- without that the
                    # blind spot would never close.
                    needs_restamp = True
                elif not _stamps_match(cached_stamp, file_stamp(file_path)):
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

                loaded_runs[file_path] = run_index

            return CacheLoadResult(
                runs=loaded_runs,
                schema_master=schema_master,
                metadata_is_stale=metadata_is_stale,
                needs_restamp=needs_restamp,
                parent_source=parent_source,
            )
        except Exception as e:
            print(f"CACHE_READ_ERROR: Local JSON index parsing fault. Trace: {str(e)}")
            return CacheLoadResult(metadata_is_stale=True, parent_source=parent_source)
