"""
Where the project's source entries sit on this machine, in memory.

``SourceLocation`` is a snapshot answering both directions -- path to entry and
entry to path -- keyed by ``canonical_path``, so the same file in any spelling
(slashes, case, ``..`` segments) finds the same entry. Reading the root
directories off disk happens once, when a snapshot is made on a worker
(``read_root_directories``); every lookup afterwards is a dictionary read.
The pool's own path to run lookup is ``DataPool.run_lookup``; the two share
only the key.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence

from core.project_model import DataRoot, SourceEntry
from io_modules.measurement_files import canonical_path
from io_modules.project_store import resolve_root_in

__all__ = ["SourceLocation", "build_source_location"]


@dataclass(frozen=True)
class SourceLocation:
    """Immutable path <-> source entry snapshot. Do not mutate the maps."""

    entries_by_path: Mapping[str, SourceEntry] = field(default_factory=dict)
    paths_by_entry_id: Mapping[str, str] = field(default_factory=dict)

    def entry_for_path(self, path: str) -> Optional[SourceEntry]:
        """The entry for a file in any spelling, or None if the project does not know it."""
        if not path:
            return None
        return self.entries_by_path.get(canonical_path(path))

    def path_for_entry(self, entry_id: str) -> Optional[str]:
        """The entry's canonical path on this machine, or None if its root cannot be found."""
        return self.paths_by_entry_id.get(entry_id)

    def entry_for_run(self, run) -> Optional[SourceEntry]:
        """The entry of a loaded run, by the run's ``file_path``."""
        return self.entry_for_path(getattr(run, "file_path", ""))


def build_source_location(roots: Sequence[DataRoot], sources: Sequence[SourceEntry],
                          root_directories: Mapping[str, Optional[str]]) -> SourceLocation:
    """
    Snapshot of every source whose root resolves. Touches no disk: pass the
    ``read_root_directories`` result a worker took. When two roots reach the
    same file the first root wins.
    """
    sources_by_root: Dict[str, list] = {}
    for entry in sources:
        sources_by_root.setdefault(entry.root_id, []).append(entry)

    entries_by_path: Dict[str, SourceEntry] = {}
    paths_by_entry_id: Dict[str, str] = {}
    for root in roots:
        directory = resolve_root_in(root_directories, root)
        if directory is None:
            continue
        for entry in sources_by_root.get(root.id, ()):
            path = canonical_path(os.path.join(directory, entry.relpath))
            if entries_by_path.setdefault(path, entry) is entry:
                paths_by_entry_id.setdefault(entry.id, path)
    return SourceLocation(entries_by_path, paths_by_entry_id)
