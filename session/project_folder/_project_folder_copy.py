"""
What a Project folder takes along when the project gets a new folder: a Save
As into another folder and the first save of an Untitled
project (its scan caches, ADR §1.22).

Mixed into ProjectSession like `session/result_sets.py`: the plan reads the
open project's result sets, path and commit count, and `save_as` applies it.
What lies on disk comes in a `ProjectFolderListing` read on a background job;
planning from it never touches the disk (§1.253).

All internal documentation strings and variable labels are standardly written
in English.
"""

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from io_modules.project_folder import ProjectFolderListing
from io_modules.project_store import (
    CACHE_DIR_NAME, adopt_untitled_scan_caches, cache_folder, names_a_cache_subfolder,
    project_files_in, project_folder, scan_cache_folder, tab_cache_folder)
from io_modules.tab_cache import resolve_tab_cache_path

_CHANGED_MEANWHILE = (
    "The project's result sets changed while they were being copied "
    "(a batch run finished). Nothing was saved; try Save As again.")


@dataclass(frozen=True)
class ProjectFolderListingRequest:
    """
    What a Save As to `project_path` must read from disk before it can plan
    the copy, made by `build_project_folder_listing_request`.

    `moves_folder` is False when the save stays in the project's own folder
    or is the first save of an Untitled project: nothing is read and the
    copy is empty. Otherwise `source_path` and `result_set_files` are what
    `read_project_folder_listing` reads, and `fingerprint` is what the
    result sets were when the listing was asked for -- a batch that commits
    or overwrites one while the listing is read or the copy runs makes the
    plan stale, and the Save As is refused rather than name a set the
    listing never saw (§1.253).
    """
    project_path: str
    moves_folder: bool = False
    source_path: str = ""
    result_set_files: Tuple[str, ...] = ()
    fingerprint: Tuple = ()


@dataclass(frozen=True)
class ProjectFolderCopy:
    """
    What a Save As into another folder copies, and what the project then names.

    Built by `build_project_folder_copy` before anything is written. `copies` are
    absolute `(source, destination)` pairs -- the result sets first, then the
    scan caches and the Tab cache files the destination does not have yet; `relabels` is
    `(result_set_id, label, file)` for every result set the new project keeps.
    `fingerprint` is what the result sets were when the listing was asked
    for: a batch that commits or overwrites one while the copy runs makes the
    plan stale, and `save_as` refuses it rather than name a set that was
    never copied. With `keep_result_sets=False` the new project keeps none
    and only the scan caches and the Tab cache are copied.

    `workbook_copies` are the project's own workbooks (`metadata.xlsx`,
    `channel_pairing.xlsx`): small, copied with the rest or -- with nothing in
    `copies` -- on their own before the save. Whatever the user chose for
    result sets, they go along. One the destination already has is kept and
    named in `kept_workbooks`, never overwritten. An empty plan (same folder,
    or a first save) copies nothing and changes nothing.
    """
    project_path: str
    keep_result_sets: bool = True
    copies: Tuple[Tuple[str, str], ...] = ()
    relabels: Tuple[Tuple[str, str, str], ...] = ()
    result_set_bytes: int = 0
    fingerprint: Tuple = ()
    workbook_copies: Tuple[Tuple[str, str], ...] = ()
    kept_workbooks: Tuple[str, ...] = ()

    @property
    def result_set_count(self) -> int:
        return len(self.relabels) if self.keep_result_sets else 0

    @property
    def destinations(self) -> List[str]:
        return [destination for _source, destination in self.copies + self.workbook_copies]


class ProjectFolderMixin:
    """Project folder copy planning and the one-folder-one-project rule, mixed into ProjectSession."""

    # ---- first save of an Untitled project -------------------

    def _carry_untitled_scan_caches(self) -> None:
        """
        Moves the scan caches built while the project was Untitled into its
        own `cache/scan/`, so the first rescan after the save is a cache hit
        rather than a full re-parse.

        After the save, never part of it: a scan cache is rebuilt by the next
        scan, so one that cannot be moved costs time, not data (#775). With a
        cache adopter plugged in (the GUI's background job,
        `orchestration.project_folder.run_untitled_scan_cache_carry`) it runs
        there and a failure reaches the log as a warning; without one (no
        window, so no log) it runs here and a failure is dropped.
        """
        roots = list(self._project.data_roots)
        if self._cache_adopter is not None:
            self._cache_adopter(self._path, roots)
            return
        try:
            adopt_untitled_scan_caches(self._path, roots)
        except OSError:
            pass

    # ---- Save As into another folder ------------------------

    def build_project_folder_listing_request(self, project_path: str) -> ProjectFolderListingRequest:
        """
        Says what a Save As to `project_path` has to read from disk before
        `build_project_folder_copy` can plan it.

        Raises ValueError when the destination folder already holds another
        project -- before anything is read, so the user hears it at once.
        """
        new_path = os.path.abspath(project_path)
        self._refuse_shared_folder(new_path)
        if not self._moves_folder(new_path):
            return ProjectFolderListingRequest(project_path=new_path)
        return ProjectFolderListingRequest(
            project_path=new_path, moves_folder=True, source_path=self._path,
            result_set_files=tuple(rs.file for rs in self._project.result_sets),
            fingerprint=self._result_set_fingerprint())

    def build_project_folder_copy(self, request: ProjectFolderListingRequest,
                                  listing: Optional[ProjectFolderListing] = None,
                                  keep_result_sets: bool = True) -> ProjectFolderCopy:
        """
        Plans what the Save As in `request` has to copy so that the new
        project reads its own results, never another copy's. `listing` is
        what `request` asked to read; it is not needed when the save stays
        in the folder.

        The cache belongs to the folder, and a result set is named relative to
        it -- so a project moved to another folder without its cache would read
        `cache/<label>` there: missing, or worse, a different project's numbers
        under the same label (#674). Each kept set gets a label that is free in
        the destination cache (`_2`, `_3`... as `_unique_label` does), so a
        leftover there is neither overwritten nor adopted.

        Raises ValueError when the result sets changed since the listing was
        asked for (a batch finished meanwhile). Copies nothing and reads
        nothing itself: the copy can be gigabytes and runs on a background
        job; `save_as(project_path, folder_copy=plan)` then commits it.
        """
        if not request.moves_folder:
            return ProjectFolderCopy(project_path=request.project_path)
        if listing is None or os.path.normcase(listing.project_path) != os.path.normcase(
                request.project_path):
            raise ValueError("Saving into another folder needs the listing of its Project folder.")

        new_path = request.project_path
        old_folder = project_folder(request.source_path)
        new_cache = cache_folder(new_path)
        copies: List[Tuple[str, str]] = []
        relabels: List[Tuple[str, str, str]] = []
        result_set_bytes = 0
        if keep_result_sets:
            if request.fingerprint != self._result_set_fingerprint():
                raise ValueError(_CHANGED_MEANWHILE)
            taken = set()
            for result_set in self._project.result_sets:
                label = result_set.label
                n = 2
                while self._destination_label_taken(listing, label, taken):
                    label = f"{result_set.label}_{n}"
                    n += 1
                taken.add(label.casefold())
                on_disk = listing.result_sets.get(result_set.file)
                name = f"{label}.h5" if on_disk is not None and on_disk.is_file else label
                relabels.append((result_set.id, label, os.path.join(CACHE_DIR_NAME, name)))
                # A set whose folder is already gone has nothing to copy; it
                # keeps its fresh label, so it stays missing rather than
                # reading whatever the destination holds under the old one.
                if on_disk is not None:
                    copies.append((os.path.join(old_folder, result_set.file),
                                   os.path.join(new_cache, name)))
                    result_set_bytes += on_disk.size

        old_scan, new_scan = scan_cache_folder(request.source_path), scan_cache_folder(new_path)
        copies.extend((os.path.join(old_scan, name), os.path.join(new_scan, name))
                      for name in listing.scan_cache_names)

        # Every Tab cache file, so the new project's tabs open without a
        # compute. Names are relative to `cache/tabs/`, so they
        # stay valid; kept whatever the user chose for result sets.
        old_tabs, new_tabs = tab_cache_folder(request.source_path), tab_cache_folder(new_path)
        copies.extend((resolve_tab_cache_path(old_tabs, name), resolve_tab_cache_path(new_tabs, name))
                      for name in listing.tab_cache_names)

        workbook_copies, kept_workbooks = [], []
        new_folder = project_folder(new_path)
        for name in listing.workbook_names:
            source, destination = os.path.join(old_folder, name), os.path.join(new_folder, name)
            if name in listing.destination_workbook_names:
                kept_workbooks.append(destination)
            else:
                workbook_copies.append((source, destination))

        return ProjectFolderCopy(
            project_path=new_path, keep_result_sets=keep_result_sets,
            copies=tuple(copies), relabels=tuple(relabels),
            result_set_bytes=result_set_bytes,
            fingerprint=request.fingerprint,
            workbook_copies=tuple(workbook_copies),
            kept_workbooks=tuple(kept_workbooks),
        )

    def _result_set_fingerprint(self) -> Tuple:
        # The commit count, not the refs alone: an overwrite keeps id, label
        # and file, and its timestamp has one-second resolution.
        return (self._result_set_commits,
                tuple((rs.id, rs.file) for rs in self._project.result_sets))

    @staticmethod
    def _destination_label_taken(listing: ProjectFolderListing, label: str, taken) -> bool:
        return (names_a_cache_subfolder(label) or label.casefold() in taken
                or listing.label_taken(label))

    def _moves_folder(self, new_path: str) -> bool:
        """Whether saving to `new_path` leaves the folder the cache lives in."""
        if not self._path:
            return False
        return (os.path.normcase(project_folder(self._path))
                != os.path.normcase(project_folder(new_path)))

    def _apply_project_folder_copy(self, new_path: str,
                               plan: Optional[ProjectFolderCopy]) -> List:
        """
        Points the result sets at their copies for a Save As to `new_path`;
        returns what `_restore_result_sets` needs to undo it.

        Refuses a move between folders that would carry result sets without a
        plan: the refs would name `cache/<label>` in a folder that does not
        hold them (#674).
        """
        snapshot = [list(self._project.result_sets)] + [
            (rs, rs.label, rs.file) for rs in self._project.result_sets]
        if plan is None:
            if self._moves_folder(new_path) and self._project.result_sets:
                raise ValueError(
                    "Saving into another folder needs a plan for the result sets "
                    "(ProjectSession.build_project_folder_copy).")
            return snapshot
        if os.path.normcase(plan.project_path) != os.path.normcase(new_path):
            raise ValueError("The Project folder copy plan was made for a different path.")
        if not plan.keep_result_sets:
            self._project.result_sets = []
            return snapshot
        if self._moves_folder(new_path) and plan.fingerprint != self._result_set_fingerprint():
            raise ValueError(_CHANGED_MEANWHILE)
        by_id = {rs.id: rs for rs in self._project.result_sets}
        for result_set_id, label, file in plan.relabels:
            result_set = by_id.get(result_set_id)
            if result_set is not None:
                result_set.label, result_set.file = label, file
        return snapshot

    def _restore_result_sets(self, snapshot: List) -> None:
        self._project.result_sets = snapshot[0]
        for result_set, label, file in snapshot[1:]:
            result_set.label, result_set.file = label, file

    def _refuse_shared_folder(self, new_path: str) -> None:
        """
        One folder holds one project: projects in a folder share
        its `cache/`, so a second one would read and overwrite the first's
        results. Saving over the open project's own file is just a save.
        """
        if self._path and os.path.normcase(self._path) == os.path.normcase(new_path):
            return
        folder = project_folder(new_path)
        existing = project_files_in(folder)
        if existing:
            raise ValueError(
                f"The folder '{folder}' already holds a project "
                f"({os.path.basename(existing[0])}).\n\n"
                "Projects in one folder would share their computed results, so each "
                "project needs a folder of its own. Choose an empty folder, or remove "
                "that project first."
            )
