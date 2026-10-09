# core/recent_projects.py
"""
The recent-projects list as data: one entry per project the user has opened.

Here in core/ because it is pure structure -- no filesystem, no clock, no Qt.
The list is stored in QSettings by the application shell (app_context), shown in
the Project ribbon and on the Welcome screen; all three go through this model so
a bare list of path strings never creeps back in.

`last_opened` is a UTC ISO-8601 string supplied by the caller (see ADR: clocks
live in the shell, not the data). It may be empty -- entries migrated from the
old format, which was just a JSON array of paths, have no timestamp.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

# How many entries the list keeps.
RECENT_PROJECT_LIMIT = 10


@dataclass(frozen=True)
class RecentProject:
    path: str
    last_opened: str = ""  # UTC ISO-8601, or "" when unknown

    @property
    def display_name(self) -> str:
        """The project's name without folder or extension -- what a person calls it."""
        base = os.path.basename(self.path.rstrip("/\\"))
        stem, _ext = os.path.splitext(base)
        return stem or base or self.path

    def to_entry(self) -> dict:
        return {"path": self.path, "last_opened": self.last_opened}

    @classmethod
    def from_entry(cls, entry) -> Optional["RecentProject"]:
        """Tolerates both the current dict form and the old bare-path-string form."""
        if isinstance(entry, str):
            return cls(path=entry) if entry else None
        if isinstance(entry, dict) and entry.get("path"):
            return cls(path=str(entry["path"]), last_opened=str(entry.get("last_opened", "")))
        return None


def parse_recent(raw) -> List[RecentProject]:
    """
    Reads the stored JSON string into a list of entries.

    Anything unparseable -- wrong type, broken JSON, not a list -- comes back
    empty rather than raising: a corrupt setting must not stop the app opening.
    """
    if not raw:
        return []
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(stored, list):
        return []

    out: List[RecentProject] = []
    for entry in stored:
        parsed = RecentProject.from_entry(entry)
        if parsed is not None:
            out.append(parsed)
    return out


def serialize_recent(entries: List[RecentProject]) -> str:
    return json.dumps([e.to_entry() for e in entries[:RECENT_PROJECT_LIMIT]])


def promote(entries: List[RecentProject], path: str, now: str) -> List[RecentProject]:
    """
    Returns the list with `path` moved to the front and stamped `now`.

    De-duplicated case-insensitively (Windows), so reopening a project the user
    already has does not leave a second row for it in a different spelling.
    """
    if not path:
        return list(entries)
    target = os.path.abspath(path)
    key = os.path.normcase(target)
    remaining = [e for e in entries if os.path.normcase(os.path.abspath(e.path)) != key]
    return [RecentProject(path=target, last_opened=now)] + remaining
