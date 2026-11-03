"""The one order of a project swap: read, discard, install, restore, refresh."""

from typing import Optional, Protocol

from core.project_model import NVHProject
from io_modules.project_store import ProjectFormatError

# What a project file that cannot be opened raises from read_project_file.
_UNREADABLE = (OSError, ValueError, ProjectFormatError)


class ProjectSwapSteps(Protocol):
    """What a project swap needs from the window; the GUI handler implements it."""

    def read_project_file(self, project_path: str) -> NVHProject:
        """The stored project, read without touching the open one. Raises when unreadable."""

    def report_unreadable(self, project_path: str, error: Exception) -> None:
        """Tells the user the file could not be opened."""

    def cancel_scan(self) -> None: ...
    def close_analysis_tabs(self) -> None: ...
    def empty_data_pool(self) -> None: ...

    def install_project(self, project_path: Optional[str], project: Optional[NVHProject]) -> None:
        """Puts the incoming project in the session; both None for a new Untitled one."""

    def restore_data_pool(self) -> None: ...
    def restore_filter_state(self) -> None: ...
    def restore_open_tabs(self) -> None: ...

    def add_data_folder(self, folder: str) -> None:
        """Puts a dropped folder in the Data Pool and starts its background ingest."""

    def refresh_window(self, project_path: Optional[str]) -> None:
        """Title, recent list, panels and the view, once the incoming project is in place."""


def run_project_swap(steps: ProjectSwapSteps, project_path: Optional[str] = None,
                     *, data_folder: Optional[str] = None) -> bool:
    """
    Replaces the open project with a new Untitled one (no path) or the one
    stored at `project_path`. Returns False, having changed nothing, when that
    file cannot be read. A `data_folder` (a folder dropped on the window, #772)
    joins the Data Pool once the incoming project is in place.

    The file is read before anything of the outgoing project is touched -- so
    a failed open leaves its tabs, Data Pool and filters in place -- and
    synchronously: one small file the user just picked (§1.137). The folder
    scan the Data Pool restore starts stays in the background.
    """
    project = None
    if project_path is not None:
        try:
            project = steps.read_project_file(project_path)
        except _UNREADABLE as error:
            steps.report_unreadable(project_path, error)
            return False

    # Discard the outgoing project: the same three steps for New and Open.
    steps.cancel_scan()
    steps.close_analysis_tabs()
    steps.empty_data_pool()

    steps.install_project(project_path, project)

    steps.restore_data_pool()
    # Resets and restores the Filter panel in one call (§1.90, #372).
    steps.restore_filter_state()
    steps.restore_open_tabs()
    if data_folder is not None:
        steps.add_data_folder(data_folder)

    steps.refresh_window(project_path)
    return True
