"""Parse ``## X.Y.Z - YYYY-MM-DD`` sections, their ``- bullet`` lines and ``![alt](path)`` screenshots."""

import re
from dataclasses import dataclass
from pathlib import Path

from core.asset_paths import resource_path

_HEADING = re.compile(r"^##\s+(\S+)\s+-\s+(\d{4}-\d{2}-\d{2})\s*$")
_IMAGE = re.compile(r"^\s*!\[[^\]]*\]\(([^)\s]+)\)\s*$")


@dataclass(frozen=True)
class Change:
    text: str
    images: tuple[str, ...] = ()  # absolute paths of the screenshots under this bullet


@dataclass(frozen=True)
class ChangelogEntry:
    version: str
    date: str
    changes: tuple[Change, ...]


def read_changelog(path: str | None = None) -> list[ChangelogEntry]:
    """Released versions, newest first (file order). Empty when the file is missing.

    A line ``![alt](docs/site/img/x.png)`` belongs to the bullet above it; the path is
    relative to the folder holding ``CHANGELOG.md``.
    """
    file = Path(path or resource_path("CHANGELOG.md"))
    try:
        lines = file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[tuple[str, str, list[list]]] = []
    in_release = False
    for line in lines:
        if line.startswith("## "):
            match = _HEADING.match(line)
            in_release = bool(match)
            if match:
                entries.append((match[1], match[2], []))
        elif in_release and line.startswith("- "):
            entries[-1][2].append([line[2:].strip(), []])
        elif in_release and entries[-1][2] and (image := _IMAGE.match(line)):
            entries[-1][2][-1][1].append(str(file.parent / image[1]))
    return [ChangelogEntry(v, d, tuple(Change(t, tuple(i)) for t, i in c)) for v, d, c in entries]
