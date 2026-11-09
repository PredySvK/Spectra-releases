"""
io_modules.project_folder -- What lies in a Project folder before a Save As (Floor 4, ADR §1.191).

`read_project_folder_listing` reads, on a background job, everything a Save
As into another folder needs to know from disk: which of the open project's
result sets are still there and how large they are, its scan caches, Tab
cache and workbooks, and what the destination folder already holds. The
answer is a `ProjectFolderListing`; `ResultSetOnDisk` is one result set in it.

What does NOT belong here: what the copy then takes and how it names it
(session.project_folder), when it runs and in which order
(orchestration.project_folder), and the copying itself
(io_modules.result_cache).
"""

from ._project_folder_listing import (
    ProjectFolderListing,
    ResultSetOnDisk,
    read_project_folder_listing,
)

__all__ = [
    "ProjectFolderListing",
    "ResultSetOnDisk",
    "read_project_folder_listing",
]
