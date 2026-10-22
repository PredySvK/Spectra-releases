"""
session.project_folder -- what a Save As into another folder takes along (Floor 3, ADR §1.173).

`ProjectFolderCopy` is the copy plan `ProjectSession.build_project_folder_copy`
builds before anything is written; `ProjectFolderMixin` gives ProjectSession
that method and the one-folder-one-project rule its `save_as` applies.

What does NOT belong here: copying files (io_modules.result_cache) or when the
copy runs and in which order (orchestration.project_folder).
"""

from ._project_folder_copy import ProjectFolderCopy, ProjectFolderMixin

__all__ = ["ProjectFolderCopy", "ProjectFolderMixin"]
