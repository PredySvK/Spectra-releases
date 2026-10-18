"""
session.tab_cache -- which Tab cache files a saved project still points at (Floor 3, ADR §1.178).

`build_referenced_tab_cache_names` reads the open tabs a project saved and
returns every Tab cache file name any of their curves names. Everything under
`cache/tabs/` outside that set is garbage; deleting it is `io_modules.tab_cache`.

What does NOT belong here: touching the disk (io_modules.tab_cache), or when
the clean-up runs (ProjectSession's open and save).
"""

from ._referenced_names import build_referenced_tab_cache_names

__all__ = ["build_referenced_tab_cache_names"]
