"""
Project folder -- carrying it along when Save As moves the project to another
folder.

`run_save_as` holds the one order of a Save As: let Tab cache writes land,
plan the Project folder copy, ask about the result sets, copy, save -- all or
nothing. The window's side comes through `SaveAsSteps`.
`run_project_folder_copy` is its background half: copy on a job, then save.
`run_untitled_scan_cache_carry` moves an Untitled project's scan caches in
after its first save; a failure is a log warning, never a failed save.

What does not belong here: the Save As dialogs (gui/), what the copy plan holds
and the project mutation (session/), the file copying (io_modules/).
"""

from ._copy import ProjectFolderCopyOutcome, run_project_folder_copy
from ._save_as import SaveAsSteps, run_save_as
from ._scan_cache_carry import run_untitled_scan_cache_carry

__all__ = [
    "ProjectFolderCopyOutcome",
    "SaveAsSteps",
    "run_project_folder_copy",
    "run_save_as",
    "run_untitled_scan_cache_carry",
]
