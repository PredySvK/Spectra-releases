# =====================================================================
# FILE: io_modules/result_cache/cache_reader.py
# =====================================================================
"""
Lazy reader for a result set, in either on-disk format (ADR §1.21).

Read-only, and deliberately split into a cheap browse step (which sources,
which channels are in this result set) and a per-channel fetch that actually
loads array data -- listing a result set should not mean loading every channel
of every source into memory. In format 2 the browse step reads `_set.json` and
opens no HDF5 file at all.

**The whole cost of still supporting format 1 is one adapter in this file.**
`_read_legacy_blocks` turns the old rpm/orders/amplitude[K, N] shape into the
same StoredBlock list format 2 yields, so every caller above this module sees
blocks and never learns that two formats exist. Nothing writes format 1 any
more; it is read because recomputing hundreds of saved order cuts to change a
file layout would be precisely the loss the cache exists to prevent.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import h5py
import numpy as np

from core.block_kinds import PARAM_ORDER
from core.data_block import SpectralProcessing
from core.project_model import normalize_result_kind
from io_modules.result_cache import block_io
from io_modules.result_cache import cache_layout as layout
from io_modules.result_cache.block_io import StoredAxis, StoredBlock


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
    """
    Opens a result set for the lifetime of a `with` block.

    `path` is a folder (format 2) or a single .h5 (format 1); which one it is
    is decided here rather than asked of the caller, so the two live callers --
    the Compare tab's read plan and cache lookup -- do not each grow a branch.
    """

    def __init__(self, path: str):
        self._path = path
        self._is_folder = os.path.isdir(path)
        self._handle: Optional[h5py.File] = None          # format 1
        self._shards: Dict[str, h5py.File] = {}           # format 2, opened lazily
        self._manifest: Optional[Dict[str, Any]] = None

    def __enter__(self) -> "ResultCacheReader":
        if self._is_folder:
            self._manifest = read_set_manifest(self._path)
            if self._manifest is None:
                raise OSError(f"Result set '{self._path}' has no readable {layout.SET_MANIFEST_NAME}.")
        else:
            self._handle = h5py.File(self._path, "r")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        for shard in self._shards.values():
            shard.close()
        self._shards.clear()
        self._manifest = None

    # ---- what this set is ------------------------------------------------

    @property
    def format_version(self) -> int:
        return layout.FORMAT_VERSION if self._is_folder else layout.FORMAT_VERSION_LEGACY

    @property
    def kind(self) -> str:
        raw = (self._manifest or {}).get("kind") if self._is_folder \
            else self._handle.attrs.get(layout.ATTR_KIND, "")
        return normalize_result_kind(raw) if raw else ""

    @property
    def label(self) -> str:
        if self._is_folder:
            return (self._manifest or {}).get("label", "")
        return self._handle.attrs.get(layout.ATTR_LABEL, "")

    @property
    def params_hash(self) -> str:
        if self._is_folder:
            return (self._manifest or {}).get("params_hash", "")
        return self._handle.attrs.get(layout.ATTR_PARAMS_HASH, "")

    @property
    def created_utc(self) -> str:
        if self._is_folder:
            return (self._manifest or {}).get("created_utc", "")
        return self._handle.attrs.get(layout.ATTR_CREATED_UTC, "")

    @property
    def params(self) -> Dict[str, Any]:
        if self._is_folder:
            return dict((self._manifest or {}).get("params") or {})
        return layout.load_attr(self._handle.attrs.get(layout.ATTR_PARAMS_JSON, ""))

    # ---- browsing --------------------------------------------------------

    def list_sources(self) -> List[SourceInfo]:
        if self._is_folder:
            return self._list_sources_from_manifest()
        return self._list_sources_legacy()

    def _list_sources_from_manifest(self) -> List[SourceInfo]:
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

    def _list_sources_legacy(self) -> List[SourceInfo]:
        group = self._handle.get(layout.SOURCES_GROUP)
        if group is None:
            return []

        infos = []
        for source_id in group.keys():
            source_group = group[source_id]
            # A result set written before this attribute existed, or a corrupt
            # one -- neither should stop the rest of the file from being
            # browsable (load_attr returns {} rather than raising).
            excel_metadata = layout.load_attr(
                source_group.attrs.get(layout.ATTR_EXCEL_METADATA_JSON, "")
            )
            # Group keys are a hash of the channel name (see
            # cache_layout.channel_group_key), not the name itself -- the
            # original label lives on each group's ATTR_CHANNEL_NAME attribute.
            channel_names = [
                source_group[key].attrs.get(layout.ATTR_CHANNEL_NAME, key)
                for key in source_group.keys()
            ]
            infos.append(SourceInfo(
                source_id=source_id,
                relpath=source_group.attrs.get(layout.ATTR_RELPATH, ""),
                size_bytes=int(source_group.attrs.get(layout.ATTR_SIZE_BYTES, 0)),
                mtime_ns=int(source_group.attrs.get(layout.ATTR_MTIME_NS, 0)),
                channel_names=channel_names,
                excel_metadata=excel_metadata,
            ))
        return infos

    # ---- reading ---------------------------------------------------------

    def read_blocks(self, source_id: str, channel_name: str) -> List[StoredBlock]:
        """
        Every stored block of one channel, in write order.

        Raises KeyError when the source or channel is not in this set -- the
        same signal the callers already treat as "skip this one", including for
        a file whose on-disk layout predates the channel-name hashing.
        """
        if self._is_folder:
            group = self._shard(source_id)[layout.channel_group_key(channel_name)]
            return block_io.read_channel_blocks(group)
        return self._read_legacy_blocks(source_id, channel_name)

    def _shard(self, source_id: str) -> h5py.File:
        shard = self._shards.get(source_id)
        if shard is None:
            path = os.path.join(self._path, layout.shard_name(source_id))
            if not os.path.exists(path):
                raise KeyError(f"Result set '{self.label}' has no shard for source '{source_id}'.")
            shard = h5py.File(path, "r")
            self._shards[source_id] = shard
        return shard

    def _read_legacy_blocks(self, source_id: str, channel_name: str) -> List[StoredBlock]:
        """
        Format 1's single amplitude[K, N] matrix as one StoredBlock per order.

        The SpectralProcessing rebuilt here is not invented: format 1 only ever
        held order cuts, every producer of which computed them with
        amplitude_mode "rms" (see result_blocks.compute_order_cuts), and the
        window, spectrum format and FFT size are in the file's own params.
        """
        group_path = layout.channel_group_path(source_id, channel_name)
        channel_group = self._handle[group_path]
        amplitude_dset = channel_group[layout.DATASET_AMPLITUDE]

        rpm_axis = channel_group[layout.DATASET_RPM][()]
        orders = channel_group[layout.DATASET_ORDERS][()]
        amplitude = amplitude_dset[()]
        unit = amplitude_dset.attrs.get(layout.ATTR_UNIT, "")

        params = self.params
        processing = SpectralProcessing(
            window_type=params.get("window_type", ""), amplitude_mode="rms",
            spectrum_format=params.get("spectrum_format", ""),
            fft_size=params.get("fft_size"),
        )
        meta = {
            "channel_type": "unknown",      # format 1 did not store it
            "value_quantity": "amplitude",
            "processing": block_io.flat_asdict(processing),
        }

        return [
            StoredBlock(
                name=f"Order {float(order):g} [{channel_name}]",
                axes=[StoredAxis(values=rpm_axis, unit="RPM", quantity="rpm", label="Speed")],
                values=np.asarray(amplitude[index]),
                value_unit=unit, value_quantity="amplitude",
                params={PARAM_ORDER: float(order)},
                meta=meta,
                provenance={"step": "compute_order_cuts", "parents": (), "algorithm_version": None},
            )
            for index, order in enumerate(orders.tolist())
        ]
