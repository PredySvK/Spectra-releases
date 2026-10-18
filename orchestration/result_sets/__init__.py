"""
Result-set orchestration: decide which cached curves a dock may read, and carry
result sets along when Save As moves the project to another folder.

This floor turns project state into a read plan and reports decisions that need
the GUI's involvement, such as a curve-count confirmation. For Save As it
orders the work -- copy on a background job, then save, all or nothing
(ADR §1.173) -- without copying files or asking questions itself.

What does not belong here: Qt dialogs and dock state (gui/), project/session
mutation (session/), or HDF5 reading and file copying (io_modules/).
"""

from orchestration.result_sets._copy import ResultSetCopyOutcome, run_result_set_copy
from orchestration.result_sets._load_plan import (
    ResultSetLoadPlan,
    plan_result_set_load,
)

__all__ = [
    "ResultSetCopyOutcome",
    "ResultSetLoadPlan",
    "plan_result_set_load",
    "run_result_set_copy",
]
