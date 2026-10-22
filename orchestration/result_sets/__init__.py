"""
Result-set orchestration: decide which cached curves a dock may read, and read
them onto it.

This floor turns project state into a read plan and reports decisions that need
the GUI's involvement, such as a curve-count confirmation. Once the GUI has
confirmed the plan, ``run_result_set_load`` runs the whole Load Result Sets
job: pending bookkeeping, plan order, error and Cancel cleanup, adoption of
live curves and the summary line. The GUI only draws the finished curves.
Carrying result sets along on Save As is `orchestration.project_folder`.

What does not belong here: Qt dialogs and dock widgets (gui/), project/session
mutation (session/), or HDF5 reading itself (io_modules/).
"""

from orchestration.result_sets._load_plan import (
    ResultSetLoadPlan,
    plan_result_set_load,
)
from orchestration.result_sets._load_run import run_result_set_load

__all__ = [
    "ResultSetLoadPlan",
    "plan_result_set_load",
    "run_result_set_load",
]
