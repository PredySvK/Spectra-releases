"""
io_modules.result_cache -- Result sets on disk (Floor 4, ADR §1.21).

A result set is a folder under `<project>/cache/`: one HDF5 shard per
measurement plus a `_set.json` manifest. Here is how one is written, found,
read back, moved and named.

- Writing: `create_draft` opens a `ResultSetDraft`, the frozen description a
  worker writes into; `write_result_shard` writes one measurement's
  `SourceResult` (its `ChannelBlocks`), `write_draft_manifest` finishes the
  set. An overwrite is staged beside the set it replaces: `swap_in_draft`
  puts it in place, `undo_swap_in` takes it back after a failed commit,
  `finish_swap_in` tidies up after a good one, and `discard_draft` throws a
  draft away. ProjectSession (session/result_sets.py) decides the order.
- Finding: `find_cached_result` answers "is this result already computed?"
  with a `CachedResult`; `find_duplicate_result_set` finds a set computed with
  exactly the same settings. `build_cache_index` / `write_cache_index` keep
  the derived index next to the project file.
- Reading: `ResultCacheReader` and `read_set_manifest` read a set back,
  `read_result_curves` hands Compare the curves of one, and
  `read_channel_blocks` / `write_channel_group` / `block_from_stored` are the
  one way between blocks and HDF5 (the Tab cache uses them too).
- Identity: `params_hash` and `result_params_from_block` are what a set's
  settings are matched by; `FORMAT_VERSION` is the on-disk format.
- Moving: `measure_result_sets`, `copy_result_sets`, `remove_result_sets` and
  `label_folder_exists` serve Save As and the project-folder copy;
  `find_missing_result_set_files` tells Load Result Sets which sets are gone.
- Naming: `sanitize_result_set_label` turns a typed name into a safe folder
  name; `build_result_set_label` and friends derive the default one.

What does NOT belong here: the project's list of result sets and when one is
committed (session/result_sets.py), when a batch writes (orchestration/batch),
and the Tab cache (io_modules.tab_cache) -- a Tab cache file is not a result
set.
"""

from ._block_io import (
    StoredAxis,
    StoredBlock,
    block_from_stored,
    channel_meta_for,
    read_channel_blocks,
    write_channel_group,
)
from ._cache_draft import (
    create_draft,
    discard_draft,
    finish_swap_in,
    swap_in_draft,
    undo_swap_in,
    write_draft_manifest,
)
from ._cache_folders import (
    copy_result_sets,
    find_missing_result_set_files,
    label_folder_exists,
    measure_result_sets,
    remove_result_sets,
)
from ._cache_index import build_cache_index, write_cache_index
from ._cache_layout import FORMAT_VERSION, params_hash, result_params_from_block
from ._cache_lookup import CachedResult, find_cached_result, find_duplicate_result_set
from ._cache_naming import (
    build_channel_component,
    build_kind_result_set_label,
    build_result_set_label,
    sanitize_for_filename,
    sanitize_result_set_label,
)
from ._cache_reader import ResultCacheReader, read_set_manifest
from ._cache_writer import (
    ChannelBlocks,
    ResultSetDraft,
    SourceResult,
    manifest_entry_for,
    write_result_shard,
)
from ._compare_curve_reader import read_result_curves

__all__ = [
    "FORMAT_VERSION",
    "CachedResult",
    "ChannelBlocks",
    "ResultCacheReader",
    "ResultSetDraft",
    "SourceResult",
    "StoredAxis",
    "StoredBlock",
    "block_from_stored",
    "build_cache_index",
    "build_channel_component",
    "build_kind_result_set_label",
    "build_result_set_label",
    "channel_meta_for",
    "copy_result_sets",
    "create_draft",
    "discard_draft",
    "find_cached_result",
    "find_duplicate_result_set",
    "find_missing_result_set_files",
    "finish_swap_in",
    "label_folder_exists",
    "manifest_entry_for",
    "measure_result_sets",
    "params_hash",
    "read_channel_blocks",
    "read_result_curves",
    "read_set_manifest",
    "remove_result_sets",
    "result_params_from_block",
    "sanitize_for_filename",
    "sanitize_result_set_label",
    "swap_in_draft",
    "undo_swap_in",
    "write_cache_index",
    "write_channel_group",
    "write_draft_manifest",
    "write_result_shard",
]
