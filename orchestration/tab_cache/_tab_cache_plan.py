"""Where a tab's Live result goes into the Tab cache, and where a restore reads it from."""

import dataclasses
from typing import Optional

from io_modules.project_store import tab_cache_folder
from io_modules.tab_cache import build_tab_cache_name, resolve_tab_cache_path


@dataclasses.dataclass(frozen=True)
class TabCacheWrite:
    """One Tab cache file to write: `name` is what the `TraceSpec` saves,
    `path` where the file goes."""
    name: str
    path: str


def plan_tab_cache_write(project_path: Optional[str], tab_id: str, channel_name: str, *,
                         saved_name: Optional[str] = None) -> Optional[TabCacheWrite]:
    """
    The file a channel's newly landed Live result is written to, or None when
    there is nowhere to write it: an Untitled project has no folder yet.

    A new result always gets a new name, so a file once written never
    changes. The one exception is `saved_name` -- the name a restored tab
    saved but whose file could not be read: the recompute takes that name
    over, so the project needs no new Save to find its curves next time.
    """
    if not project_path:
        return None
    folder = tab_cache_folder(project_path)
    if saved_name:
        path = resolve_tab_cache_path(folder, saved_name)
        if path is not None:
            return TabCacheWrite(name=saved_name, path=path)
    name = build_tab_cache_name(tab_id, channel_name)
    return TabCacheWrite(name=name, path=resolve_tab_cache_path(folder, name))


def resolve_tab_cache_read_path(project_path: Optional[str], name: Optional[str]) -> Optional[str]:
    """The file a restore reads a curve from: None without a project folder or
    a saved name, or for a name that would leave the project's Tab cache."""
    if not project_path or not name:
        return None
    return resolve_tab_cache_path(tab_cache_folder(project_path), name)


def build_tab_cache_hit_line(subject: str) -> str:
    """The line for a curve shown from the Tab cache; `subject` is the whole phrase."""
    return f"PROJECT: {subject} loaded from tab cache -- no recompute needed."


def build_tab_cache_miss_line(channel_name: str, reason: str) -> str:
    """The line for a restored curve whose Tab cache file could not stand in for a compute."""
    return (f"PROJECT: tab cache for {channel_name} not used ({reason}) -- "
            f"computing it from its saved recipe.")
