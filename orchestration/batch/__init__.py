"""Batch workflow orchestration.

This component owns batch use cases and their persistence sinks. It must not
contain Qt widgets, GUI controllers, or presentation concerns.
"""

from ._label import default_result_set_label
from ._overwrite import OverwriteCandidate, UpcomingResultSet, find_overwrite_candidates_by_workflow
from ._plan import (
    CALCULATE_AND_SAVE_WHAT,
    CalculateAndSavePlan,
    CalculateAndSaveRequest,
    DataPoolInput,
    DataPoolScope,
    SelectionScope,
    SelectionsInput,
    WorkflowRunPlan,
    resolve_data_pool_scope,
    resolve_selection_scope,
    plan_calculate_and_save,
    resolve_calculate_and_save_refusal,
    plan_workflow_run,
)
from ._result_set_sink import ResultSetSink
from ._batch_plan import BatchPlan, plan_batch
from ._workflow_run import BatchOutcome, run_batch
from ._chains import (
    WorkflowChainPlan, WorkflowChainBatch, plan_workflow_chains,
    plan_chain_batches, plan_result_set_batches, resolve_overwrite_candidates,
    apply_overwrites, run_chain_batches,
)
from ._batch_runs import BatchRuns, WaitingBatchRun

__all__ = [
    "BatchOutcome",
    "BatchRuns",
    "WaitingBatchRun",
    "OverwriteCandidate",
    "UpcomingResultSet",
    "WorkflowChainPlan",
    "WorkflowChainBatch",
    "plan_workflow_chains",
    "plan_chain_batches",
    "plan_result_set_batches",
    "resolve_overwrite_candidates",
    "apply_overwrites",
    "run_chain_batches",
    "BatchPlan",
    "CALCULATE_AND_SAVE_WHAT",
    "CalculateAndSavePlan",
    "CalculateAndSaveRequest",
    "DataPoolInput",
    "DataPoolScope",
    "resolve_data_pool_scope",
    "SelectionScope",
    "SelectionsInput",
    "resolve_selection_scope",
    "ResultSetSink",
    "WorkflowRunPlan",
    "default_result_set_label",
    "find_overwrite_candidates_by_workflow",
    "plan_batch",
    "plan_calculate_and_save",
    "resolve_calculate_and_save_refusal",
    "plan_workflow_run",
    "run_batch",
]
