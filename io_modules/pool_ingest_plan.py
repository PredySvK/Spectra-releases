# =====================================================================
# FILE: io_modules/pool_ingest_plan.py
# =====================================================================
"""
Reading what a raw path selection holds on disk, once.

This is pure path work over the filesystem -- walking each selected folder and
listing its measurement files -- with no Qt and no AppContext. It answers
"what is there" and nothing else: which folders become jobs, which get an
auto-tag and which inherit a parent Metadata.xlsx is decided from this
snapshot by orchestration.data_pool (#667, T7). The tree is walked once per
selected folder; a network drive pays for every extra walk.
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from io_modules.measurement_files import canonical_path, discover_measurement_files


@dataclass(frozen=True)
class SelectedFolder:
    """
    One folder the user picked and what lies at or below it.

    `folders` are the directories at or below `path` that directly hold a
    measurement, sorted, `path` itself included when it does. `parent_sheet` is
    the Metadata.xlsx sitting directly in `path`, if any.
    """

    path: str
    folders: Tuple[str, ...]
    parent_sheet: Optional[str] = None


@dataclass(frozen=True)
class SelectionTree:
    """
    The discovery snapshot of a path selection.

    `selected` lists the picked folders in selection order. `files` maps the
    canonical form of every walked folder that holds measurements to those files
    (sorted), so the later scan of the same folder does not list it again.
    `walked` is every walked folder once, as spelled on the way there: the keys
    of `files` only look folders up and are never a path to open.
    `selected_files` are the paths in the selection that are files, as spelled
    and in selection order, so the plan never asks the disk what a path is.
    `templates` are the Import templates that recognised measurements in the
    walk (None: the installed ones), so every later question about the same
    selection is answered by the same templates.
    """

    selected: Tuple[SelectedFolder, ...] = ()
    files: Dict[str, Tuple[str, ...]] = None
    walked: Tuple[str, ...] = ()
    selected_files: Tuple[str, ...] = ()
    templates: Optional[Tuple[Any, ...]] = None

    def __post_init__(self):
        if self.files is None:
            object.__setattr__(self, "files", {})

    def files_in(self, directory: str) -> Tuple[str, ...]:
        """The measurement files directly in `directory`, listing it only if the walk never saw it."""
        found = self.files.get(canonical_path(directory))
        if found is None:
            found = tuple(discover_measurement_files(directory, self.templates))
        return found


def discover_selection_tree(paths, templates: Optional[Tuple[Any, ...]] = None) -> SelectionTree:
    """
    Walks every selected directory once and returns what it found.

    Files in `paths` need no walk; they are only noted as files. `templates`
    recognise generic-suffix measurements (`is_measurement_file`).
    """
    files: Dict[str, Tuple[str, ...]] = {}
    walked = []
    selected = []
    selected_files = []
    for path in paths:
        if os.path.isfile(path):
            selected_files.append(path)
            continue
        if not os.path.isdir(path):
            continue
        folders = []
        for dirpath, _dirnames, _filenames in os.walk(path):
            key = canonical_path(dirpath)
            if key not in files:
                files[key] = tuple(discover_measurement_files(dirpath, templates))
                walked.append(dirpath)
            if files[key]:
                folders.append(dirpath)
        sheet = os.path.join(path, "Metadata.xlsx")
        selected.append(SelectedFolder(
            path, tuple(sorted(folders)), sheet if os.path.isfile(sheet) else None))
    return SelectionTree(tuple(selected), files, tuple(walked), tuple(selected_files), templates)
