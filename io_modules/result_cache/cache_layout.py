# =====================================================================
# FILE: io_modules/result_cache/cache_layout.py
# =====================================================================
"""
On-disk layout of the result cache, in both formats it can read.

cache_writer.py writes this shape, cache_reader.py reads it back; both defer
to this module so the layout is described once.

**Format 2 (current, ADR §1.21).** A result set is a *folder*, one HDF5 shard
per measurement plus a JSON manifest:

    <project>/cache/{label}/
        _set.json                 kind, params, params_hash, label, status,
                                  all_channels, created_utc, sources[]
        {source_id}.h5

    {source_id}.h5:
        / (attrs: format_version, kind, params_json, params_hash, created_utc,
           label, source_id, relpath, size_bytes, mtime_ns,
           excel_metadata_json)
        /{channel_hash}/          (attrs: channel_name, block_meta_json)
            /{block_key}/         (attrs: name, block_params_json)
                axis_0   float32[n0]        (attrs: quantity, unit, label)
                axis_1   float32[n1]        ... one per KindSpec.axis_quantities
                values   float32[n0(, n1)]  (attrs: unit, quantity)

Two properties are worth spelling out, because both were bought deliberately:

  * **How many axes a kind has is not decided here.** It is read from
    core.block_kinds.KINDS, so a new result type stays "one row in the register
    plus one factory" and the cache does not change for it.
  * **A shard is written whole and swapped in with os.replace.** HDF5 has no
    transactions, so writing whole files is the only crash safety there is --
    and a spectrogram batch is gigabytes, which is exactly why the unit written
    whole is one measurement rather than a whole set.

**Format 1 (legacy, read-only).** One .h5 for the entire set, order-cut shaped:

    /sources/{source_id}/{channel_hash}/
        rpm float32[N] · orders float32[K] · amplitude float32[K, N]

Nothing writes it any more. It is still read because recomputing hundreds of
saved order cuts to change a file format would be exactly the loss the cache
exists to prevent; cache_reader.py adapts it to the same block-shaped API.
"""
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from selection.parameter_sets import orders_equal

FORMAT_VERSION = 2
FORMAT_VERSION_LEGACY = 1

# Format 2: a result set on disk
SET_MANIFEST_NAME = "_set.json"
INDEX_NAME = "index.json"
MANIFEST_FORMAT_VERSION = 1

SOURCES_GROUP = "sources"          # format 1 only -- a shard's channels sit at its root

ATTR_FORMAT_VERSION = "format_version"
ATTR_KIND = "kind"
ATTR_PARAMS_JSON = "params_json"
ATTR_PARAMS_HASH = "params_hash"
ATTR_CREATED_UTC = "created_utc"
ATTR_LABEL = "label"

ATTR_SOURCE_ID = "source_id"
ATTR_RELPATH = "relpath"
ATTR_SIZE_BYTES = "size_bytes"
ATTR_MTIME_NS = "mtime_ns"
ATTR_UNIT = "unit"
ATTR_QUANTITY = "quantity"
ATTR_EXCEL_METADATA_JSON = "excel_metadata_json"
ATTR_CHANNEL_NAME = "channel_name"
ATTR_BLOCK_META_JSON = "block_meta_json"
ATTR_BLOCK_PARAMS_JSON = "block_params_json"
ATTR_PROVENANCE_JSON = "provenance_json"
ATTR_NAME = "name"

DATASET_VALUES = "values"
DATASET_AXIS_PREFIX = "axis_"

# Format 1 datasets. Kept because the legacy reader still names them.
DATASET_RPM = "rpm"
DATASET_ORDERS = "orders"
DATASET_AMPLITUDE = "amplitude"


def shard_name(source_id: str) -> str:
    """File name of one measurement's shard inside a result-set folder."""
    return f"{source_id}.h5"


def axis_dataset_name(position: int) -> str:
    return f"{DATASET_AXIS_PREFIX}{position}"


def block_group_key(position: int) -> str:
    """
    Group name for the nth block of a channel.

    Positional rather than derived from the block's params: an order cut is
    identified by {"order": 2.0}, a float, and a float has no stable spelling
    safe for an HDF5 group name. The params live on the group's own
    ATTR_BLOCK_PARAMS_JSON, which is what lookup matches against.
    """
    return f"b{position:04d}"


def dump_attr(value: Any) -> str:
    """A dict or list as the JSON string an HDF5 attribute can hold."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def load_attr(raw: Any) -> Dict[str, Any]:
    """
    The inverse of dump_attr, and never a reason for a read to fail.

    An attribute written before it existed comes back empty, and so does a
    corrupt one: a cache file is derived data, so the worst an unreadable
    attribute may cost is a cache miss, never a crash in the caller that was
    only hoping for a fast hit.
    """
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def params_hash(params: dict) -> str:
    """
    Fingerprint of the parameters actually used for a result set.

    Sorted-key JSON so the same parameters hash the same way regardless of
    dict insertion order -- this is the safety net that catches a result set
    whose label ("order_v01") does not match what it was actually computed
    with.
    """
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def block_params_match(wanted: Mapping[str, Any], stored: Mapping[str, Any]) -> bool:
    """
    Whether a stored block answers a request for `wanted`.

    Only the keys in `wanted` are compared -- a stored block is free to record
    more about itself than the caller asked about. Floats go through
    orders_equal's relative tolerance, because every number in a cache file
    came back through float32: an order the user typed as 2.3 reads back as
    2.2999999523 and an exact == would call them different orders.
    """
    for key, value in wanted.items():
        if key not in stored:
            return False
        other = stored[key]
        if isinstance(value, float) or isinstance(other, float):
            try:
                if not orders_equal(float(value), float(other)):
                    return False
            except (TypeError, ValueError):
                return False
        elif value != other:
            return False
    return True


def result_params_from_node(workflow, node_id: str) -> Dict[str, Any]:
    """
    The params a result set computed at one workflow node is identified by.

    A node's `params` is already a flat mirror of the block's dsp_configs
    dataclass, so this is that dict plus the algorithm version the node was
    authored with. The duplicate check and writing side both use this identity,
    and a historical hash test catches a change that would miss saved results.

    Plus a `lineage` key -- a fingerprint of the subgraph *above* the node --
    when there is one. In a branching graph `spectrum(2048)` and
    `lowpass(500) -> spectrum(2048)` carry the same own-params; without lineage
    they would hash identically and a cache lookup would hand back the wrong
    numbers. `lineage_hash` returns "" when the node is fed only by input nodes,
    so a one-block graph keeps the exact identity today's single step has and no
    already-saved result set becomes a cache miss.
    """
    # io_modules -> signal_processing is allowed; kept local so cache_layout stays cheap to import
    from signal_processing.workflow import identity_params, lineage_hash

    node = workflow.node(node_id)
    # One identity rule, shared with `_ancestor_repr`: display-only params (a
    # spectrogram's colour scale) dropped and missing keys backfilled from the
    # config defaults, so a node authored in the tree hashes the same as the
    # ribbon's `asdict(config)` (audit 02 findings 2.1 / 2.11).
    params = identity_params(node)
    lineage = lineage_hash(workflow, node_id)
    if lineage:
        params["lineage"] = lineage
    return params


def source_group_path(source_id: str) -> str:
    return f"{SOURCES_GROUP}/{source_id}"


def channel_group_key(channel_name: str) -> str:
    """
    HDF5 treats "/" in a group name as a path separator, so a raw channel
    label containing one (e.g. "Engine/Cover +X") would silently split into
    nested groups instead of naming a single channel. Hashing sidesteps every
    HDF5-unsafe character at once; the original label is kept as
    attrs[ATTR_CHANNEL_NAME] so the file still explains itself.
    """
    return hashlib.sha1(channel_name.encode("utf-8")).hexdigest()


def channel_group_path(source_id: str, channel_name: str) -> str:
    return f"{source_group_path(source_id)}/{channel_group_key(channel_name)}"
