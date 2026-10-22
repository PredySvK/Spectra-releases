"""
Tab cache orchestration: which file a tab's newly landed Live
result goes to, which file a restore reads, and the log lines for both.

`TabCacheFiles` owns the Tab cache file name of every curve of an open tab,
under one key per curve (`TabCacheCurve`: the tab plus its base curve or a
dropped channel's channel key); the capture of the open tabs for a Save takes
the names from it. It also decides and starts every write: with a project
folder on a dock task, while Untitled it holds the write until the first Save,
and it handles a failed write and a closed tab.

`plan_tab_cache_write` names the file for a result that came from a
measurement (a new name every time, except that a restored tab whose file
could not be read takes its saved name over); `resolve_tab_cache_read_path`
turns a saved `TraceSpec.tab_cache_file` back into a path. The read itself
runs in `live_compute.run_live_compute`, the write is
`io_modules.tab_cache.write_tab_cache_file` on a dock task.

An Untitled project has no folder to write to: `TabCacheFiles` keeps
its results (`HeldTabCacheWrites`, private to it) in memory under names from `io_modules.tab_cache.build_tab_cache_name` until the
first Save, which writes those the saved tabs name
(`session.tab_cache.build_referenced_tab_cache_names`, #731). Any curve of a tab can be held, not just the base.

What does NOT belong here: the file format (io_modules.tab_cache), deciding
which tabs are computed (gui/workspace), and the
saved `TraceSpec` shape (session.open_tabs).
"""

from orchestration.tab_cache._tab_cache_plan import (
    TabCacheWrite,
    build_tab_cache_hit_line,
    build_tab_cache_miss_line,
    plan_tab_cache_write,
    resolve_tab_cache_read_path,
)
from orchestration.tab_cache._tab_cache_files import TabCacheCurve, TabCacheFiles

__all__ = [
    "TabCacheCurve",
    "TabCacheFiles",
    "TabCacheWrite",
    "build_tab_cache_hit_line",
    "build_tab_cache_miss_line",
    "plan_tab_cache_write",
    "resolve_tab_cache_read_path",
]
