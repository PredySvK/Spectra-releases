"""
What a Save As into another folder finds on disk before it plans the copy
(ADR §1.191).

Read once, off the GUI thread: sizing the result sets walks every shard, so
the time grows with the project. The plan is then worked out from the
listing alone, without touching the disk again.

All internal documentation strings and variable labels are standardly written
in English.
"""

import os
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Mapping, Optional, Tuple

from core.jobs import CancelToken
from io_modules.project_store import (
    PROJECT_WORKBOOK_NAMES, cache_folder, project_folder, scan_cache_folder, tab_cache_folder)
from io_modules.result_cache import measure_result_sets
from io_modules.tab_cache import read_tab_cache_names, resolve_tab_cache_path


@dataclass(frozen=True)
class ResultSetOnDisk:
    """A result set the source folder still holds: a format-1 single `.h5` file or a folder."""
    is_file: bool
    size: int


@dataclass(frozen=True)
class ProjectFolderListing:
    """
    What lies in the open project's Project folder and in the destination of
    a Save As, read before anything is copied.

    `result_sets` is keyed by the result set's `file` (relative to the
    Project folder, as the project names it); one that is gone from disk is
    absent. `destination_cache_names` are the names directly under the
    destination `cache/`, casefolded -- a label is taken when it or
    `<label>.h5` is among them. `scan_cache_names` and `tab_cache_names` are
    the source files the destination does not hold yet; `workbook_names` the
    project workbooks beside the source project and
    `destination_workbook_names` the ones the destination already has.
    """
    source_path: str
    project_path: str
    result_sets: Mapping[str, ResultSetOnDisk] = field(default_factory=dict)
    destination_cache_names: FrozenSet[str] = frozenset()
    scan_cache_names: Tuple[str, ...] = ()
    tab_cache_names: Tuple[str, ...] = ()
    workbook_names: Tuple[str, ...] = ()
    destination_workbook_names: FrozenSet[str] = frozenset()

    def label_taken(self, label: str) -> bool:
        """Whether the destination `cache/` already holds `label`, as a folder or a `.h5` file."""
        return (label.casefold() in self.destination_cache_names
                or f"{label}.h5".casefold() in self.destination_cache_names)


def read_project_folder_listing(source_path: str, project_path: str,
                                result_set_files: Iterable[str],
                                cancel_token: Optional[CancelToken] = None) -> ProjectFolderListing:
    """
    Reads what a Save As from `source_path` to `project_path` (both project
    files) needs to plan the copy. `result_set_files` are the open project's
    result sets, named relative to its folder. Stops between result sets
    when `cancel_token` is cancelled (JobCancelled).
    """
    source_folder = project_folder(source_path)
    result_sets = {}
    for file in result_set_files:
        if cancel_token is not None:
            cancel_token.raise_if_cancelled()
        path = os.path.join(source_folder, file)
        if os.path.exists(path):
            result_sets[file] = ResultSetOnDisk(is_file=os.path.isfile(path),
                                                size=measure_result_sets([path]))

    destination_folder = project_folder(project_path)
    return ProjectFolderListing(
        source_path=os.path.abspath(source_path),
        project_path=os.path.abspath(project_path),
        result_sets=result_sets,
        destination_cache_names=frozenset(
            name.casefold() for name in _names_in(cache_folder(project_path))),
        scan_cache_names=_scan_caches_to_copy(source_path, project_path),
        tab_cache_names=_tab_caches_to_copy(source_path, project_path),
        workbook_names=tuple(name for name in PROJECT_WORKBOOK_NAMES
                             if os.path.isfile(os.path.join(source_folder, name))),
        destination_workbook_names=frozenset(
            name for name in PROJECT_WORKBOOK_NAMES
            if os.path.exists(os.path.join(destination_folder, name))),
    )


def _names_in(folder: str) -> Tuple[str, ...]:
    try:
        return tuple(os.listdir(folder))
    except OSError:
        return ()


def _scan_caches_to_copy(source_path: str, project_path: str) -> Tuple[str, ...]:
    old_scan, new_scan = scan_cache_folder(source_path), scan_cache_folder(project_path)
    return tuple(name for name in sorted(_names_in(old_scan))
                 if os.path.isfile(os.path.join(old_scan, name))
                 and not os.path.exists(os.path.join(new_scan, name)))


def _tab_caches_to_copy(source_path: str, project_path: str) -> Tuple[str, ...]:
    """
    Every complete Tab cache file the destination does not have. A write
    still in progress is not listed: Save As waits for those first.
    """
    new_tabs = tab_cache_folder(project_path)
    names = []
    for name in read_tab_cache_names(tab_cache_folder(source_path)):
        destination = resolve_tab_cache_path(new_tabs, name)
        if destination is not None and not os.path.exists(destination):
            names.append(name)
    return tuple(names)
