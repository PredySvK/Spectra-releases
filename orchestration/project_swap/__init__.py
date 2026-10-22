"""
Project swap -- replacing the open project with another (#771).

`run_project_swap` holds the one order every swap runs in -- New, Open (also
Open recent and the project opened at startup) and a dropped data folder:
read the file, discard the outgoing project, install the incoming one,
restore, refresh. A file that cannot be read changes nothing. The window's
side of each step comes through `ProjectSwapSteps`.

What does not belong here: the "Save changes?" question, the file dialog and
the "already open in another window" check (they come before a swap, in
gui/), and the reading and installing themselves (session/).
"""

from ._project_swap import ProjectSwapSteps, run_project_swap

__all__ = [
    "ProjectSwapSteps",
    "run_project_swap",
]
