"""
From a discovery snapshot to the folder map and parent Metadata.xlsx an ingest plan carries.

`discover_selection_tree` (io_modules) says what is on disk; the decisions
live here: one job per folder and which inherit a parent Metadata.xlsx.
Nothing here touches the disk, so the tree is walked once per selected
folder however many maps are built from it (#667, T7).
"""

import os

from io_modules.measurement_files import canonical_path, is_measurement_file
from io_modules.pool_ingest_plan import SelectionTree


def build_ingest_folder_map(paths, tree: SelectionTree) -> dict:
    """
    One job per folder: {directory: set of files | None}, None meaning the
    whole folder.

    A folder in the selection beats individual files chosen inside it, so
    picking a folder and one of its files does not quietly narrow the folder
    down to that single file. A selected directory stands for every
    descendant folder that directly holds a measurement (itself included), so
    a parent-folder pick behaves like multi-selecting each per-run subfolder.

    Folders are keyed by the spelling they arrived in, not by canonical_path:
    the keys become data roots, and a folder registered once in each spelling
    is two roots for one folder. Duplicates collapse canonically; the first
    spelling wins.
    """
    plan: dict = {}
    seen: dict = {}     # canonical folder -> the spelling kept

    def folder_key(directory: str) -> str:
        return seen.setdefault(canonical_path(directory), directory)

    for selected in tree.selected:
        for folder in selected.folders:
            plan[folder_key(folder)] = None

    for path in paths:
        if not os.path.isfile(path) or not is_measurement_file(path):
            continue
        directory = folder_key(os.path.dirname(path))
        if plan.get(directory, "") is None:
            continue
        plan.setdefault(directory, set()).add(path)

    return plan


def _reached_by_recursion(selected):
    """The folders below a picked folder; the picked folder itself was chosen, not reached."""
    return [folder for folder in selected.folders if folder != selected.path]


def find_parent_metadata_files(tree: SelectionTree) -> dict:
    """
    Metadata.xlsx of the picked parent, for each folder only reached by
    recursing into it, so a sheet describing every run underneath a dataset
    root is not invisible to the per-run scans. Later picks overwrite earlier.
    """
    parents = {}
    for selected in tree.selected:
        if selected.parent_sheet is None:
            continue
        for folder in _reached_by_recursion(selected):
            parents[folder] = selected.parent_sheet
    return parents
