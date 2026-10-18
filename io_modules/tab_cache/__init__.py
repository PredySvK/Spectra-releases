"""
io_modules.tab_cache -- The Tab cache on disk (Floor 4, ADR §1.178).

The curves an open tab got from measurements, kept under `<project>/cache/tabs/`
(`project_store.tab_cache_folder`) so a reopened project shows them without
recomputing. One file per channel of a tab, named by `build_tab_cache_name`
(``<tab>/<channel>_<random>.h5``, the name a `TraceSpec` saves), written whole
by `write_tab_cache_file` and then never changed; `read_tab_cache_file` gives
the blocks back or raises `TabCacheMiss` with the reason;
`read_tab_cache_names` lists the complete files (what a Save As copies) and
`remove_unreferenced_tab_cache_files` deletes what no saved tab names. `resolve_tab_cache_path`
is the one way from a saved name to a path, and refuses names that leave the
folder. Blocks <-> HDF5 goes through `result_cache.block_io` only.

What does NOT belong here: deciding which tabs go into the Tab cache or when a
file is written (gui/workspace), the saved name itself (session.open_tabs),
and result sets (io_modules.result_cache) -- a Tab cache file is not one.
"""

from ._tab_cache_file import (
    TabCacheContent,
    TabCacheMiss,
    build_tab_cache_name,
    read_tab_cache_file,
    read_tab_cache_names,
    remove_unreferenced_tab_cache_files,
    resolve_tab_cache_path,
    write_tab_cache_file,
)

__all__ = [
    "TabCacheContent",
    "TabCacheMiss",
    "build_tab_cache_name",
    "read_tab_cache_file",
    "read_tab_cache_names",
    "remove_unreferenced_tab_cache_files",
    "resolve_tab_cache_path",
    "write_tab_cache_file",
]
