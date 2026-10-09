# =====================================================================
# FILE: io_modules/result_cache/cache_index.py
# =====================================================================
"""
`<project>/cache/index.json` -- the answer to "do I already have this result?"
without opening a single HDF5 file (ADR §1.21).

One entry per (result set × measurement): which kind, computed with which
parameters, over which source, covering which channels and which blocks. That
is everything cache lookup needs to reject a candidate; only a surviving
candidate costs a file open, and then only of that one measurement's shard.

**The index is derived and never authoritative.** The truth is `_set.json`
inside each result-set folder plus the `ResultSetRef` list in the project;
`rebuild()` reconstructs the index from those at any time, and every reader
here falls back to a rebuild rather than trusting a stale file. That is what
keeps the rule intact -- the cache stays derived data that may
be deleted whenever the user likes.

A JSON file rather than SQLite because at this size the whole thing is a
single small read, it can be inspected and diffed by eye, and there is no
second binary state to keep beside the project. If a project ever grows past
what a linear scan can carry, the entries below are already shaped like rows.
"""
import json
import os
from typing import Any, Dict, List, Optional

from core.project_model import NVHProject
from io_modules.atomic_write import write_json_atomic
from io_modules.project_store import cache_folder, project_folder
from io_modules.result_cache import cache_layout as layout
from io_modules.result_cache.cache_reader import read_set_manifest

INDEX_FORMAT_VERSION = 1


def index_path(project_path: str) -> str:
    return os.path.join(cache_folder(project_path), layout.INDEX_NAME)


def _index_entry(result_set, *, source_id: str, source_size_bytes: Optional[int],
                 file: str, channels: Optional[List[str]],
                 block_params: Optional[List[Any]]) -> Dict[str, Any]:
    """
    One index row. Both builders below construct their rows through here so the
    format-2 and format-1 paths cannot drift to different key sets -- if they
    did, `candidates()` would silently stop filtering on the key one side omits.
    """
    return {
        "kind": result_set.kind,
        "params_hash": result_set.params_hash,
        "result_set_id": result_set.id,
        "label": result_set.label,
        "status": result_set.status,
        "all_channels": bool(result_set.all_channels),
        "created_utc": result_set.created_utc,
        "source_id": source_id,
        "source_size_bytes": source_size_bytes,
        "file": file,
        "channels": channels,
        "block_params": block_params,
    }


def entries_for_result_set(result_set, manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    One index entry per measurement covered by `result_set`.

    `size_bytes` is copied in because a cache hit requires the source file to
    be unchanged, and byte count is how that is decided (see cache_lookup) --
    carrying it here is what lets a changed measurement be rejected without
    opening anything.
    """
    return [
        _index_entry(
            result_set,
            source_id=source.get("source_id", ""),
            source_size_bytes=int(source.get("size_bytes", 0) or 0),
            file=os.path.join(result_set.file, layout.shard_name(source.get("source_id", ""))),
            channels=[
                channel.get("channel_name", "")
                for channel in (source.get("channels") or [])
            ],
            block_params=[
                params
                for channel in (source.get("channels") or [])
                for params in (channel.get("block_params") or [])
            ],
        )
        for source in (manifest.get("sources") or [])
    ]


def load(project_path: str) -> List[Dict[str, Any]]:
    """
    The index as it is on disk, or an empty list when there is none.

    Never raises: an unreadable index means a rebuild, not a failure -- see
    `entries_for` which is what callers should actually use.
    """
    try:
        with open(index_path(project_path), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("format_version") != INDEX_FORMAT_VERSION:
        return []
    entries = data.get("entries")
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def write(project_path: str, entries: List[Dict[str, Any]]) -> str:
    """Writes the index atomically, the same shape project_store writes the project."""
    return write_json_atomic(
        index_path(project_path),
        {"format_version": INDEX_FORMAT_VERSION, "entries": entries},
    )


def rebuild(project: NVHProject, project_path: str) -> List[Dict[str, Any]]:
    """
    Reconstructs the index from the project's result sets and their manifests.

    Format-1 result sets are indexed too, from their `source_ids` -- with no
    channel list, because listing their channels would mean opening the .h5,
    which is exactly what the index exists to avoid. Lookup treats an entry
    with no channel list as "might match, open it and see", so a legacy set
    still gets found; it just does not get the free rejection.
    """
    entries: List[Dict[str, Any]] = []
    for result_set in project.result_sets:
        if result_set.format_version >= layout.FORMAT_VERSION:
            folder = os.path.join(project_folder(project_path), result_set.file)
            manifest = read_set_manifest(folder)
            if manifest is None:
                continue
            entries.extend(entries_for_result_set(result_set, manifest))
        else:
            entries.extend(_legacy_entries(result_set))
    return entries


def _legacy_entries(result_set) -> List[Dict[str, Any]]:
    return [
        _index_entry(
            result_set,
            source_id=source_id,
            source_size_bytes=None,     # unknown without opening the file
            file=result_set.file,
            channels=None,              # unknown without opening the file
            block_params=None,
        )
        for source_id in result_set.source_ids
    ]


def entries_for(project: NVHProject, project_path: Optional[str],
                persist: bool = True) -> List[Dict[str, Any]]:
    """
    The index to search, rebuilding it first if what is on disk does not
    describe this project's result sets.

    "Describes" is checked by result-set id coverage rather than by a full
    comparison: an index missing a set (written by an older build, deleted by
    the user, half-written by a crash) must self-heal, while an index that
    merely lists a set the project has since dropped costs nothing -- lookup
    resolves every candidate against the project anyway.

    `persist=False` keeps the rebuilt index in memory only: a view-only window
    (or a worker thread) must not persist derived state into the project
    folder, the same guard scan cache has via `write_cache`. A stale on-disk
    index is harmless -- the next writable lookup heals it.
    """
    if not project_path:
        return []

    entries = load(project_path)
    indexed_ids = {entry.get("result_set_id") for entry in entries}
    if any(rs.id not in indexed_ids for rs in project.result_sets):
        entries = rebuild(project, project_path)
        if persist:
            try:
                write(project_path, entries)
            except OSError:
                pass    # a read-only or missing cache folder must not break lookup
    return entries


def candidates(entries: List[Dict[str, Any]], kind: str, source_id: str,
               channel_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Index entries that could satisfy a request, cheapest checks first.

    `channels` of None means "not known from the index alone" (a format-1 set),
    which passes rather than fails -- the index may only ever narrow the search,
    never hide a result that is actually there.
    """
    matches = []
    for entry in entries:
        if entry.get("kind") != kind or entry.get("source_id") != source_id:
            continue
        if entry.get("status") != "complete":
            continue
        channels = entry.get("channels")
        if channel_name is not None and channels is not None and channel_name not in channels:
            continue
        matches.append(entry)
    return matches
