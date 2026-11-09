"""
Whether a recent project is still on disk (#773, #941).

`read_project_exists(path)` answers for one project file and returns
`(path, exists)`, the payload orchestration/recent_projects reports per path.
It may block on an unreachable network share, so it is only ever called from
a job.

What does not belong here: when and on which runner the check runs
(orchestration/recent_projects), the recent list as data (core/recent_projects).
"""

from ._project_exists import read_project_exists

__all__ = [
    "read_project_exists",
]
