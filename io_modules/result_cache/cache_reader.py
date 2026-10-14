# =====================================================================
# FILE: io_modules/result_cache/cache_reader.py
# =====================================================================
"""
Lazy reader for a result set folder.

Read-only, and deliberately split into a cheap browse step (which sources,
which channels are in this result set) and a per-channel fetch that actually
loads array data -- listing a result set should not mean loading every channel
of every source into memory. The browse step reads `_set.json` and opens no
HDF5 file at all.

A format-1 single `.h5` is no longer readable: opening one raises OSError, which
every caller already treats as "skip this result set".
"""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import h5py

from io_modules.result_cache import block_io
from io_modules.result_cache import cache_layout as layout
from io_modules.result_cache.block_io import StoredBlock


def read_set_manifest(folder: str) -> Optional[Dict[str, Any]]:
    """
    A result-set folder's `_set.json`, or None if it has none or it is corrupt.

    None rather than an exception because a folder without a readable manifest
    is an incomplete result set -- a batch that was cancelled or crashed after
    some shards were written -- and everything above should skip it, not fail.
    """
    path = os.path.join(folder, layout.SET_MANIFEST_NAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


@dataclass
class SourceInfo:
    source_id: str
    relpath: str
    size_bytes: int
    mtime_ns: int
    channel_names: List[str]
    excel_metadata: Dict[str, Any] = field(default_factory=dict)


class ResultCacheReader:
    """Opens a result-set folder for the lifetime of a `with` block."""

    def __init__(self, path: str):
        self._path = path
        self._shards: Dict[str, h5py.File] = {}           # opened lazily
        self._manifest: Optional[Dict[str, Any]] = None

    def __enter__(self) -> "ResultCacheReader":
        if not os.path.isdir(self._path):
            raise OSError(f"Result set '{self._path}' is not a result-set folder.")
        self._manifest = read_set_manifest(self._path)
        if self._manifest is None:
            raise OSError(f"Result set '{self._path}' has no readable {layout.SET_MANIFEST_NAME}.")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        for shard in self._shards.values():
            shard.close()
        self._shards.clear()
        self._manifest = None

    # ---- what this set is ------------------------------------------------

    @property
    def format_version(self) -> int:
        return layout.FORMAT_VERSION

    @property
    def kind(self) -> str:
        return (self._manifest or {}).get("kind") or ""

    @property
    def label(self) -> str:
        return (self._manifest or {}).get("label", "")

    @property
    def params_hash(self) -> str:
        return (self._manifest or {}).get("params_hash", "")

    @property
    def created_utc(self) -> str:
        return (self._manifest or {}).get("created_utc", "")

    @property
    def params(self) -> Dict[str, Any]:
        return dict((self._manifest or {}).get("params") or {})

    # ---- browsing --------------------------------------------------------

    def list_sources(self) -> List[SourceInfo]:
        return [
            SourceInfo(
                source_id=entry.get("source_id", ""),
                relpath=entry.get("relpath", ""),
                size_bytes=int(entry.get("size_bytes", 0) or 0),
                mtime_ns=int(entry.get("mtime_ns", 0) or 0),
                channel_names=[
                    channel.get("channel_name", "")
                    for channel in (entry.get("channels") or [])
                ],
                excel_metadata=dict(entry.get("excel_metadata") or {}),
            )
            for entry in ((self._manifest or {}).get("sources") or [])
        ]

    # ---- reading ---------------------------------------------------------

    def read_blocks(self, source_id: str, channel_name: str) -> List[StoredBlock]:
        """
        Every stored block of one channel, in write order.

        Raises KeyError when the source or channel is not in this set -- the
        signal the callers already treat as "skip this one".
        """
        group = self._shard(source_id)[layout.channel_group_key(channel_name)]
        return block_io.read_channel_blocks(group)

    def _shard(self, source_id: str) -> h5py.File:
        shard = self._shards.get(source_id)
        if shard is None:
            path = os.path.join(self._path, layout.shard_name(source_id))
            if not os.path.exists(path):
                raise KeyError(f"Result set '{self.label}' has no shard for source '{source_id}'.")
            shard = h5py.File(path, "r")
            self._shards[source_id] = shard
        return shard
