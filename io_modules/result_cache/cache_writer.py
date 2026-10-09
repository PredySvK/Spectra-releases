# =====================================================================
# FILE: io_modules/result_cache/cache_writer.py
# =====================================================================
"""
Writes a result set: a folder of HDF5 shards, one per measurement, plus a
JSON manifest (ADR §1.21).

The unit written whole is **one measurement**, not one result set, and that is
the whole point of the format. A spectrogram batch over forty files is
gigabytes; collecting it and writing it at the end -- what the order-cut-only
writer did -- meant holding all of it in memory, losing everything to a Cancel,
and rewriting the lot to change one file. A shard per measurement means each
background step writes its own file the moment it has one, nothing is held, and
a cancelled batch simply never gets its manifest.

Each shard is still written whole, at a temp path, and swapped in with
os.replace: HDF5 has no transactions, so a file built in place is a file a
crash can corrupt. `write_result_shard` is called from worker threads (one file
each, so no locking is needed); creating and committing the set around them is
ProjectSession's job, on the GUI thread.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import h5py

from core.data_block import NVHDataBlock
from io_modules.atomic_write import write_json_atomic
from io_modules.result_cache import block_io
from io_modules.result_cache import cache_layout as layout


@dataclass
class ChannelBlocks:
    """One channel's results, as the blocks the DSP already produced.

    Blocks rather than bare arrays because a block is what every producer
    already has: the workflow runner, Calculate & Save Data and the cache all
    speak the same carrier, so nothing has to be unpacked into a
    kind-specific shape on the way to disk and packed back on the way out."""
    channel_name: str
    blocks: List[NVHDataBlock]


@dataclass
class SourceResult:
    """Everything computed for one measurement file, identified the same
    way core.project_model.SourceEntry is, so a result set can be matched
    back against the project that produced it."""
    source_id: str
    relpath: str
    size_bytes: int
    mtime_ns: int
    channels: List[ChannelBlocks] = field(default_factory=list)
    # The Level 2 Excel row linked to this file at save time, carried into the
    # result set so it explains itself even when handed over without its
    # project (see core.project_model.SourceEntry.excel_metadata).
    excel_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultSetDraft:
    """
    Where a result set is being written, and what identifies it.

    Deliberately plain, frozen data with no open handles: it is handed to
    background workers that each write one shard, so it has to be safe to copy
    across threads. ProjectSession creates it (begin_result_set) and finishes
    it (commit_result_set / abort_result_set).
    """
    folder: str                 # absolute; may be a staging folder on overwrite
    kind: str
    label: str
    params: Dict[str, Any]
    params_hash: str
    created_utc: str
    compression: Optional[str] = None


def write_result_shard(draft: ResultSetDraft, source: SourceResult) -> Dict[str, Any]:
    """
    Writes one measurement's shard, atomically, and returns its manifest entry.

    Runs on a worker thread. The returned entry is small (names and numbers
    only), so what crosses back to the GUI thread is bookkeeping rather than
    the arrays that were just written -- which is the second reason the write
    happens out here and not in the callback.
    """
    os.makedirs(draft.folder, exist_ok=True)
    path = os.path.join(draft.folder, layout.shard_name(source.source_id))
    temp_path = path + ".tmp"

    try:
        with h5py.File(temp_path, "w") as handle:
            handle.attrs[layout.ATTR_FORMAT_VERSION] = layout.FORMAT_VERSION
            handle.attrs[layout.ATTR_KIND] = draft.kind
            handle.attrs[layout.ATTR_PARAMS_JSON] = layout.dump_attr(draft.params)
            handle.attrs[layout.ATTR_PARAMS_HASH] = draft.params_hash
            handle.attrs[layout.ATTR_CREATED_UTC] = draft.created_utc
            handle.attrs[layout.ATTR_LABEL] = draft.label

            handle.attrs[layout.ATTR_SOURCE_ID] = source.source_id
            handle.attrs[layout.ATTR_RELPATH] = source.relpath
            handle.attrs[layout.ATTR_SIZE_BYTES] = source.size_bytes
            handle.attrs[layout.ATTR_MTIME_NS] = source.mtime_ns
            handle.attrs[layout.ATTR_EXCEL_METADATA_JSON] = layout.dump_attr(source.excel_metadata)

            for channel in source.channels:
                if not channel.blocks:
                    continue
                channel_group = handle.create_group(
                    layout.channel_group_key(channel.channel_name)
                )
                block_io.write_channel_group(
                    channel_group, channel.channel_name, channel.blocks, draft.compression
                )

            handle.flush()
    except Exception:
        # Never leave a half-written .tmp behind for a future write to trip over.
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    os.replace(temp_path, path)
    return manifest_entry_for(source)


def manifest_entry_for(source: SourceResult) -> Dict[str, Any]:
    """
    What the manifest records about one measurement.

    Enough for the Compare tab to list a result set, and for cache lookup to
    reject a candidate, without opening a single HDF5 file -- which is what
    makes browsing a result set free and a cache miss cheap.
    """
    return {
        "source_id": source.source_id,
        "relpath": source.relpath,
        "size_bytes": source.size_bytes,
        "mtime_ns": source.mtime_ns,
        "excel_metadata": dict(source.excel_metadata),
        "channels": [
            {
                "channel_name": channel.channel_name,
                "block_params": [dict(block.provenance.params) for block in channel.blocks],
            }
            for channel in source.channels if channel.blocks
        ],
    }


def build_manifest(draft: ResultSetDraft, entries: List[Dict[str, Any]],
                   status: str, all_channels: bool) -> Dict[str, Any]:
    """The `_set.json` contents: what the folder is, and what is in it."""
    return {
        "manifest_version": layout.MANIFEST_FORMAT_VERSION,
        "format_version": layout.FORMAT_VERSION,
        "kind": draft.kind,
        "label": draft.label,
        "params": dict(draft.params),
        "params_hash": draft.params_hash,
        "created_utc": draft.created_utc,
        "status": status,
        "all_channels": all_channels,
        "sources": list(entries),
    }


def write_set_manifest(folder: str, manifest: Dict[str, Any]) -> str:
    """Writes `_set.json` atomically, the same way project_store writes the project."""
    return write_json_atomic(os.path.join(folder, layout.SET_MANIFEST_NAME), manifest)
