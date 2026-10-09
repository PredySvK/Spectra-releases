"""
Result-set loading orchestration: decide which cached curves a dock may read.

This floor turns project state into a read plan and reports decisions that need
the GUI's involvement, such as a curve-count confirmation.  It does not read
cache files, submit jobs, or ask questions.

What does not belong here: Qt dialogs and dock state (gui/), project/session
mutation (session/), or HDF5 reading (io_modules/).
"""

from orchestration.result_sets._load_plan import (
    ResultSetLoadPlan,
    plan_result_set_load,
)

__all__ = [
    "ResultSetLoadPlan",
    "plan_result_set_load",
]
