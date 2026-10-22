"""
One Tab cache file: one channel of one open tab, written whole, then never changed.

Layout (HDF5)::

    /                 attrs: format, format_version, channel_name, recipe_json
    /blocks/k0000     attrs: kind   -- one group per block, in Live result order
        b0000/...     the block, written by result_cache.write_channel_group

Each block gets its own group because one channel's Live result may mix kinds
(an order tab with Overall Level holds order cuts and an Overall Level curve),
and `block_io` rebuilds a block for one kind at a time. Blocks <-> HDF5 goes
through `block_io` only: there is no second block format.
"""

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

import h5py

from core.data_block import NVHDataBlock
from io_modules.result_cache import (
    block_from_stored, read_channel_blocks, sanitize_for_filename, write_channel_group,
)

TAB_CACHE_FORMAT = "nvh_tab_cache"
TAB_CACHE_FORMAT_VERSION = 1
TAB_CACHE_SUFFIX = ".h5"

_ATTR_FORMAT = "format"
_ATTR_FORMAT_VERSION = "format_version"
_ATTR_CHANNEL_NAME = "channel_name"
_ATTR_RECIPE_JSON = "recipe_json"
_ATTR_KIND = "kind"
_GROUP_BLOCKS = "blocks"


class TabCacheMiss(Exception):
    """A Tab cache file that cannot stand in for a compute; `str()` says why."""


@dataclass(frozen=True)
class TabCacheContent:
    """What one Tab cache file holds: the channel's blocks and their recipe."""
    blocks: Tuple[NVHDataBlock, ...]
    recipe: Optional[Mapping[str, Any]] = None


def build_tab_cache_name(tab_id: str, channel_name: str) -> str:
    """
    A fresh name for one channel's file, relative to the project's
    `cache/tabs/` folder: ``<tab>/<channel>_<random>.h5``. Never reused for a
    newer result, so a file once written is never rewritten.
    """
    tab = sanitize_for_filename(tab_id or "tab")
    channel = sanitize_for_filename(channel_name or "")
    return f"{tab}/{channel}_{uuid.uuid4().hex[:12]}{TAB_CACHE_SUFFIX}"


def resolve_tab_cache_path(tabs_folder: str, name: Optional[str]) -> Optional[str]:
    """
    Where `name` lives under `tabs_folder`, or None when it does not name a
    Tab cache file inside that folder. The name comes from a project file,
    which anyone can edit -- it must not lead a read or a write anywhere else.
    """
    if not name or not isinstance(name, str) or not name.endswith(TAB_CACHE_SUFFIX):
        return None
    parts = name.replace("\\", "/").split("/")
    if os.path.isabs(name) or any(part in ("", ".", "..") or ":" in part for part in parts):
        return None
    root = os.path.abspath(tabs_folder)
    path = os.path.abspath(os.path.join(root, *parts))
    if os.path.dirname(path) == root or not path.startswith(root + os.sep):
        return None
    return path


def write_tab_cache_file(path: str, blocks: Sequence[NVHDataBlock],
                         recipe: Optional[Mapping[str, Any]] = None) -> str:
    """
    Writes one channel's blocks and their recipe to `path`, whole or not at
    all: the content goes to a sibling temporary file that replaces `path`
    only once it is complete, so a reader -- or a crash mid-write -- never
    sees half a file. Runs on a worker thread.
    """
    if not blocks:
        raise ValueError("a Tab cache file needs at least one block")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.{uuid.uuid4().hex[:8]}.tmp"
    channel_name = blocks[0].source.channel_name or blocks[0].name
    try:
        with h5py.File(temp_path, "w") as handle:
            handle.attrs[_ATTR_FORMAT] = TAB_CACHE_FORMAT
            handle.attrs[_ATTR_FORMAT_VERSION] = TAB_CACHE_FORMAT_VERSION
            handle.attrs[_ATTR_CHANNEL_NAME] = channel_name
            handle.attrs[_ATTR_RECIPE_JSON] = json.dumps(
                dict(recipe) if recipe is not None else None, sort_keys=True, default=str)
            container = handle.create_group(_GROUP_BLOCKS)
            for position, block in enumerate(blocks):
                group = container.create_group(f"k{position:04d}")
                group.attrs[_ATTR_KIND] = block.kind
                write_channel_group(group, channel_name, [block])
            handle.flush()
        os.replace(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    return path


def read_tab_cache_file(path: Optional[str]) -> TabCacheContent:
    """
    The blocks and recipe in the Tab cache file at `path`. Raises
    `TabCacheMiss` -- never anything else -- when the file is missing,
    unreadable, of another format or its blocks do not rebuild: the caller
    then computes the tab from its recipe. Runs on a worker thread.
    """
    if not path:
        raise TabCacheMiss("no file name")
    if not os.path.isfile(path):
        raise TabCacheMiss("file missing")
    try:
        with h5py.File(path, "r") as handle:
            return _read_content(handle)
    except TabCacheMiss:
        raise
    except Exception as error:
        raise TabCacheMiss(f"unreadable: {error}") from error


def _read_content(handle) -> TabCacheContent:
    file_format = _text(handle.attrs.get(_ATTR_FORMAT))
    version = handle.attrs.get(_ATTR_FORMAT_VERSION)
    if file_format != TAB_CACHE_FORMAT:
        raise TabCacheMiss("not a Tab cache file (other format)")
    if version is None or int(version) != TAB_CACHE_FORMAT_VERSION:
        raise TabCacheMiss(f"format version {version}, this release reads {TAB_CACHE_FORMAT_VERSION}")
    container = handle.get(_GROUP_BLOCKS)
    if container is None or not len(container):
        raise TabCacheMiss("no blocks")

    blocks = []
    for key in sorted(container.keys()):
        group = container[key]
        kind = _text(group.attrs.get(_ATTR_KIND))
        stored = read_channel_blocks(group)
        if len(stored) != 1:
            raise TabCacheMiss(f"block {key} is incomplete")
        blocks.append(block_from_stored(stored[0], kind))

    recipe = json.loads(_text(handle.attrs.get(_ATTR_RECIPE_JSON)) or "null")
    return TabCacheContent(blocks=tuple(blocks), recipe=recipe if isinstance(recipe, dict) else None)


def _text(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return "" if raw is None else str(raw)


def read_tab_cache_names(tabs_folder: str) -> List[str]:
    """
    The relative names (``<tab>/<file>.h5``, as a `TraceSpec` saves them) of
    every complete Tab cache file under `tabs_folder`, sorted. A write still
    in progress is a ``.tmp`` file and is no Tab cache file yet; anything not
    exactly two levels down is not ours either. A missing or unreadable folder
    holds none.
    """
    root = os.path.abspath(tabs_folder)
    return sorted(f"{os.path.basename(tab_folder)}/{os.path.basename(path)}"
                  for tab_folder, paths in _tab_cache_files(root) for path in paths)


def remove_unreferenced_tab_cache_files(tabs_folder: str, referenced_names: Iterable[str]) -> None:
    """
    Deletes every Tab cache file under `tabs_folder` that `referenced_names`
    (relative names, as a `TraceSpec` saves them) does not list, and the tab
    folders left empty. Touches only `*.h5` files
    exactly two levels down (``<tab>/<file>.h5``) -- anything else, such as an
    in-flight ``.tmp`` write, stays -- and never leaves `tabs_folder`. A file
    that cannot be removed is skipped: clean-up never raises, so it cannot
    fail a Save.
    """
    root = os.path.abspath(tabs_folder)
    keep = set()
    for name in referenced_names:
        path = resolve_tab_cache_path(root, name)
        if path is not None:
            keep.add(os.path.normcase(path))
    for tab_folder, paths in _tab_cache_files(root):
        for path in paths:
            if os.path.normcase(os.path.abspath(path)) in keep:
                continue
            try:
                os.remove(path)
            except OSError:
                continue
        try:
            os.rmdir(tab_folder)  # only succeeds when empty
        except OSError:
            pass


def _tab_cache_files(root: str) -> Iterator[Tuple[str, List[str]]]:
    """`(tab folder, [complete *.h5 file paths])` for every tab folder under
    `root`; nothing for a folder that is missing or cannot be listed."""
    try:
        tab_folders = [entry.path for entry in os.scandir(root)
                       if entry.is_dir(follow_symlinks=False)]
    except OSError:
        return
    for tab_folder in tab_folders:
        try:
            files = [entry.path for entry in os.scandir(tab_folder)
                     if entry.is_file(follow_symlinks=False)
                     and entry.name.endswith(TAB_CACHE_SUFFIX)]
        except OSError:
            continue
        yield tab_folder, files
