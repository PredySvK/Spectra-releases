"""
Which recent projects are still on disk (#773).

`run_recent_project_check` checks every path on the job runner and reports
`on_checked(path, exists)` per path, so the Welcome screen and the Project
ribbon's drop-down mark a missing project from one check, and an unreachable
network share never freezes the GUI thread (#412).

What does not belong here: the recent list as data (core/recent_projects),
its storage (app_context), how a missing row looks (gui/).
"""

from ._recent_project_check import run_recent_project_check

__all__ = [
    "run_recent_project_check",
]
