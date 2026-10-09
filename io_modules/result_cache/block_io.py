# =====================================================================
# FILE: io_modules/result_cache/block_io.py
# =====================================================================
"""
The one mapping between an NVHDataBlock and its HDF5 form (ADR §1.21).

Two levels, on purpose:

  * `StoredBlock` -- arrays plus the attributes that came with them, and
    nothing else. The Compare tab wants curves, not blocks; and the legacy
    format-1 reader can honestly produce this much without inventing the
    SpectralProcessing that format 1 never stored.
  * `block_from_stored()` -- a real NVHDataBlock, for the callers that plot or
    post-process a cached result.

Nothing here branches on `kind`. How many axes a kind has comes from
core.block_kinds.KINDS, and the block is rebuilt through
NVHDataBlock.from_stored, so adding a result type stays one row in the
register plus one factory -- the cache does not learn about it.

Why io_modules/ and not core/: this is serialisation to HDF5. core/ is pure
data with no I/O, and h5py may not appear there.
"""
from dataclasses import dataclass, field, fields, replace
from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from core.block_kinds import spec_for
from core.data_block import (
    Acquisition, Axis, NVHDataBlock, Provenance, SourceRef, SpectralProcessing,
)
from io_modules.result_cache import cache_layout as layout
from io_modules.result_cache.cache_layout import dump_attr, load_attr
from selection.channel_identity import strip_order_overlay_prefix


@dataclass
class StoredAxis:
    values: np.ndarray
    unit: str
    quantity: str
    label: str = ""


@dataclass
class StoredBlock:
    """One block as it came off disk, before anyone decides to rebuild it."""
    name: str
    axes: List[StoredAxis]
    values: np.ndarray
    value_unit: str
    value_quantity: str = ""
    # What identifies this block within its channel, e.g. {"order": 2.0}.
    # Empty for kinds that produce one block per channel.
    params: Dict[str, Any] = field(default_factory=dict)
    # Channel-level description shared by every block of the channel: what
    # sensor it is, how it was recorded, what DSP settings produced it.
    meta: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)


def flat_asdict(instance) -> Dict[str, Any]:
    """A flat dataclass as a JSON-safe dict (these have no nested dataclasses)."""
    return {f.name: getattr(instance, f.name) for f in fields(instance)}


def _build(dataclass_type, data: Optional[Mapping[str, Any]]):
    """
    Reconstructs a flat dataclass, ignoring keys it does not have.

    Tolerant on purpose: a cache file written by a build whose Acquisition had
    one more field must still be readable, and must not take down the read with
    an unexpected-keyword TypeError.
    """
    if not data:
        return None
    known = {f.name for f in fields(dataclass_type)}
    return dataclass_type(**{k: v for k, v in data.items() if k in known})


def _build_source_ref(data: Optional[Mapping[str, Any]]) -> Optional[SourceRef]:
    """
    The stored SourceRef, its channel name without an "O:1 " overlay tag.

    A result set computed after an order overlay had stamped that tag onto the
    channel's shared metadata saved it inside the block's source. The tag is no
    longer written (#160); it is peeled off here so a curve loaded from such a
    set is re-dropped under the channel's real name.
    """
    source = _build(SourceRef, data)
    if source is None:
        return None
    return replace(source, channel_name=strip_order_overlay_prefix(source.channel_name))


def channel_meta_for(block: NVHDataBlock) -> Dict[str, Any]:
    """
    Everything a channel's blocks share, so a shard explains itself without
    the project that wrote it (the promise cache_layout's docstring makes).
    """
    return {
        "channel_type": block.channel_type,
        "value_quantity": block.value_quantity,
        "acquisition": flat_asdict(block.acquisition),
        "processing": flat_asdict(block.processing) if block.processing is not None else None,
        "source": flat_asdict(block.source),
        "metadata": dict(block.metadata),
    }


def write_channel_group(group, channel_name: str, blocks: List[NVHDataBlock],
                        compression: Optional[str] = None) -> None:
    """
    Writes one channel's blocks into an already-created HDF5 group.

    `compression` is None, "gzip" or "lzf" -- a per-project setting, not a
    property of the format: h5py decompresses transparently, so a file written
    either way reads back identically and the reader never asks.
    """
    group.attrs[layout.ATTR_CHANNEL_NAME] = channel_name
    group.attrs[layout.ATTR_BLOCK_META_JSON] = dump_attr(channel_meta_for(blocks[0]))

    for position, block in enumerate(blocks):
        block_group = group.create_group(layout.block_group_key(position))
        block_group.attrs[layout.ATTR_NAME] = block.name
        block_group.attrs[layout.ATTR_BLOCK_PARAMS_JSON] = dump_attr(dict(block.provenance.params))
        block_group.attrs[layout.ATTR_PROVENANCE_JSON] = dump_attr({
            "step": block.provenance.step,
            "parents": list(block.provenance.parents),
            "algorithm_version": block.provenance.algorithm_version,
        })

        for position_axis, axis in enumerate(block.axes):
            axis_dset = block_group.create_dataset(
                layout.axis_dataset_name(position_axis),
                data=np.asarray(axis.values, dtype=np.float64),
            )
            axis_dset.attrs[layout.ATTR_UNIT] = axis.unit
            axis_dset.attrs[layout.ATTR_QUANTITY] = axis.quantity
            axis_dset.attrs[layout.ATTR_LABEL] = axis.label

        values = np.asarray(block.values, dtype=np.float32)
        values_dset = group_create_values(block_group, values, compression)
        values_dset.attrs[layout.ATTR_UNIT] = block.value_unit
        values_dset.attrs[layout.ATTR_QUANTITY] = block.value_quantity


def group_create_values(block_group, values: np.ndarray, compression: Optional[str]):
    """
    Creates the `values` dataset, chunked when it is a map.

    A 2-D result (a spectrogram) is chunked whether or not it is compressed:
    HDF5 requires chunking before any filter can be applied, and chunking is
    also what will let Epic 3 read a zoomed-in window without pulling the whole
    map into memory. A 1-D curve is small enough that a contiguous dataset is
    the cheaper choice.
    """
    kwargs: Dict[str, Any] = {}
    if values.ndim == 2:
        kwargs["chunks"] = (values.shape[0], max(1, min(64, values.shape[1])))
    if compression:
        if not kwargs.get("chunks"):
            kwargs["chunks"] = True
        kwargs["compression"] = compression
        if compression == "gzip":
            kwargs["compression_opts"] = 4
    return block_group.create_dataset(layout.DATASET_VALUES, data=values, **kwargs)


def read_channel_blocks(group) -> List[StoredBlock]:
    """Every block of one channel group, in the order they were written."""
    meta = load_attr(group.attrs.get(layout.ATTR_BLOCK_META_JSON, ""))
    blocks: List[StoredBlock] = []

    for key in sorted(group.keys()):
        block_group = group[key]
        values_dset = block_group[layout.DATASET_VALUES]

        axes: List[StoredAxis] = []
        position = 0
        while layout.axis_dataset_name(position) in block_group:
            axis_dset = block_group[layout.axis_dataset_name(position)]
            axes.append(StoredAxis(
                values=axis_dset[()],
                unit=axis_dset.attrs.get(layout.ATTR_UNIT, ""),
                quantity=axis_dset.attrs.get(layout.ATTR_QUANTITY, ""),
                label=axis_dset.attrs.get(layout.ATTR_LABEL, ""),
            ))
            position += 1

        blocks.append(StoredBlock(
            name=block_group.attrs.get(layout.ATTR_NAME, ""),
            axes=axes,
            values=values_dset[()],
            value_unit=values_dset.attrs.get(layout.ATTR_UNIT, ""),
            value_quantity=values_dset.attrs.get(layout.ATTR_QUANTITY, ""),
            params=load_attr(block_group.attrs.get(layout.ATTR_BLOCK_PARAMS_JSON, "")),
            meta=meta,
            provenance=load_attr(block_group.attrs.get(layout.ATTR_PROVENANCE_JSON, "")),
        ))
    return blocks


def block_from_stored(stored: StoredBlock, kind: str) -> NVHDataBlock:
    """
    Rebuilds a full NVHDataBlock from what was stored.

    Raises ValueError (from block_kinds.validate) if the file does not describe
    a coherent block of `kind` -- a truncated axis or a spectrum that lost its
    processing is a corrupt cache entry, and the caller should recompute rather
    than plot it.
    """
    meta = stored.meta or {}
    provenance = stored.provenance or {}
    spec = spec_for(kind)

    axes = tuple(
        Axis(values=axis.values, unit=axis.unit,
             quantity=axis.quantity or quantity.split("|")[0], label=axis.label)
        for axis, quantity in zip(stored.axes, spec.axis_quantities)
    )
    return NVHDataBlock.from_stored(
        name=stored.name, kind=kind, axes=axes, values=stored.values,
        value_unit=stored.value_unit,
        value_quantity=stored.value_quantity or meta.get("value_quantity", ""),
        channel_type=meta.get("channel_type", "unknown"),
        acquisition=_build(Acquisition, meta.get("acquisition")),
        processing=_build(SpectralProcessing, meta.get("processing")),
        source=_build_source_ref(meta.get("source")),
        provenance=Provenance(
            step=provenance.get("step", ""),
            parents=tuple(provenance.get("parents") or ()),
            params=dict(stored.params),
            algorithm_version=provenance.get("algorithm_version"),
        ),
        metadata=meta.get("metadata") or {},
    )
