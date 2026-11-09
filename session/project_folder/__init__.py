"""
session.project_folder -- what a Save As into another folder takes along (Floor 3, ADR §1.173).

`ProjectSession.build_project_folder_listing_request` says what has to be read from
disk first (a `ProjectFolderListingRequest`); `build_project_folder_copy`
then works out the copy plan, a `ProjectFolderCopy`, from the
`ProjectFolderListing` alone -- before anything is written and without
touching the disk (§1.253). `ProjectFolderMixin` gives ProjectSession those
methods and the one-folder-one-project rule its `save_as` applies.

What does NOT belong here: reading the folders and copying files
(io_modules.project_folder, io_modules.result_cache) or when that runs and in
which order (orchestration.project_folder).
"""

from ._project_folder_copy import (
    ProjectFolderCopy,
    ProjectFolderListingRequest,
    ProjectFolderMixin,
)

__all__ = ["ProjectFolderCopy", "ProjectFolderListingRequest", "ProjectFolderMixin"]
