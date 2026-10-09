# =====================================================================
# FILE: io_modules/pool_ingest_plan.py
# =====================================================================
"""
Turning a raw path selection into the plan a Data Pool ingest runs on.

This is pure path work over the filesystem -- folder discovery, basename
tagging, and locating a parent Metadata.xlsx -- with no Qt and no AppContext.
It lived next to PoolIngestController in gui/ only for proximity; audit 02
(S4 refactor candidate) moved it here, where the rest of the disk-facing
measurement logic already is.
"""

import os

from io_modules.measurement_files import canonical_path, discover_measurement_folders, is_measurement_file


def build_ingest_folder_map(paths) -> dict:
    """
    Turns a mixed selection of folders and files into one job per folder.

    Returns {directory: set of files | None}, where None means the whole
    folder. A folder in the selection beats individual files chosen inside it,
    so picking a folder and one of its files does not quietly narrow the folder
    down to that single file.

    A selected directory is expanded via discover_measurement_folders() into
    every descendant folder that directly holds a measurement (itself
    included) -- a parent-folder pick then behaves exactly like manually
    multi-selecting each of its per-run subfolders (BUGS.md H1/H4). A folder
    with no subfolders and files directly in it still just returns itself, so
    single-folder imports are unchanged.

    Folders are keyed by the spelling they arrived in, not by canonical_path.
    The canonical form is lower-cased, and this dictionary's keys are handed
    on to the project as data roots -- a folder registered once in each form
    is two roots for one folder. Duplicates are still collapsed by comparing
    canonically; the first spelling wins.
    """
    plan: dict = {}
    seen: dict = {}     # canonical folder -> the spelling kept

    def folder_key(directory: str) -> str:
        canonical = canonical_path(directory)
        return seen.setdefault(canonical, directory)

    for path in paths:
        if os.path.isdir(path):
            for folder in discover_measurement_folders(path):
                plan[folder_key(folder)] = None

    for path in paths:
        if not os.path.isfile(path) or not is_measurement_file(path):
            continue
        directory = folder_key(os.path.dirname(path))
        if plan.get(directory, "") is None:
            continue
        plan.setdefault(directory, set()).add(path)

    return plan


def _expansion_children(selected_path: str):
    """Descendant folders discover_measurement_folders() added below selected_path."""
    return [folder for folder in discover_measurement_folders(selected_path) if folder != selected_path]


def derive_auto_tags(paths) -> dict:
    """
    Test-setup label for each folder build_ingest_folder_map() only reached by recursing
    into a selected parent (BUGS.md H2): os.path.basename(folder), e.g.
    "Run 00". A folder the user selected directly is left untagged -- that
    selection is itself the explicit decision, nothing to infer.
    """
    tags = {}
    for path in paths:
        if not os.path.isdir(path):
            continue
        for folder in _expansion_children(path):
            tags[folder] = os.path.basename(folder.rstrip("/\\")) or folder
    return tags


def find_parent_metadata_files(paths) -> dict:
    """
    Metadata.xlsx path for each folder build_ingest_folder_map() only reached by recursing
    into a selected parent (BUGS.md H3): threaded down so a sheet describing
    every run underneath a dataset root is not invisible to the per-run scans.
    """
    parents = {}
    for path in paths:
        if not os.path.isdir(path):
            continue
        candidate = os.path.join(path, "Metadata.xlsx")
        if not os.path.isfile(candidate):
            continue
        for folder in _expansion_children(path):
            parents[folder] = candidate
    return parents
