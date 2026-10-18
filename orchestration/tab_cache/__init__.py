"""
Tab cache orchestration: which file a tab's newly landed Live
result goes to, which file a restore reads, and the log lines for both.

`plan_tab_cache_write` names the file for a result that came from a
measurement (a new name every time, except that a restored tab whose file
could not be read takes its saved name over); `resolve_tab_cache_read_path`
turns a saved `TraceSpec.tab_cache_file` back into a path. The read itself
runs in `live_compute.run_live_compute`, the write is
`io_modules.tab_cache.write_tab_cache_file` on a dock task.

An Untitled project has no folder to write to: `HeldTabCacheWrites` keeps
its results in memory under names from `io_modules.tab_cache.build_tab_cache_name` until the
first Save, which writes those the saved tabs name
(`session.tab_cache.build_referenced_tab_cache_names`, #731). Any curve of a tab can be held, not just the base.

What does NOT belong here: the file format (io_modules.tab_cache), deciding
which tabs are computed and scheduling the write (gui/workspace), and the
saved name (session.open_tabs).
"""

from orchestration.tab_cache._held_writes import HeldTabCacheWrite, HeldTabCacheWrites
from orchestration.tab_cache._tab_cache_plan import (
    TabCacheWrite,
    build_tab_cache_hit_line,
    build_tab_cache_miss_line,
    plan_tab_cache_write,
    resolve_tab_cache_read_path,
)

__all__ = [
    "HeldTabCacheWrite",
    "HeldTabCacheWrites",
    "TabCacheWrite",
    "build_tab_cache_hit_line",
    "build_tab_cache_miss_line",
    "plan_tab_cache_write",
    "resolve_tab_cache_read_path",
]
