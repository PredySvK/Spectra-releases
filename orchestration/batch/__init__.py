"""Batch workflow orchestration.

This component owns batch use cases and their persistence sinks. It must not
contain Qt widgets, GUI controllers, or presentation concerns.
"""

from ._label import default_result_set_label
from ._overwrite import find_overwrite_candidates
from ._plan import (
    REFUSAL_INVALID_GRAPH,
    REFUSAL_MISSING_SELECTION,
    REFUSAL_NO_CHANNELS_CHOSEN,
    REFUSAL_NO_LOADED_FOLDER,
    REFUSAL_NO_MATCHING_CHANNELS,
    REFUSAL_NO_SAVE_BLOCKS,
    REFUSAL_NO_SAVE_CHANNELS,
    REFUSAL_MULTIPLE_INPUTS,
    CalculateAndSavePlan,
    WorkflowRunPlan,
    plan_calculate_and_save,
    resolve_calculate_and_save_refusal,
    plan_workflow_run,
)
from ._result_set_sink import ResultSetSink
from ._batch_plan import BatchPlan, plan_batch
from ._workflow_run import BatchOutcome, run_batch, supersede_running_batch
from ._chains import (
    WorkflowChainPlan, WorkflowChainBatch, plan_workflow_chains,
    plan_chain_batches, run_chain_batches,
)

__all__ = [
    "BatchOutcome",
    "WorkflowChainPlan",
    "WorkflowChainBatch",
    "plan_workflow_chains",
    "plan_chain_batches",
    "run_chain_batches",
    "BatchPlan",
    "CalculateAndSavePlan",
    "REFUSAL_INVALID_GRAPH",
    "REFUSAL_MISSING_SELECTION",
    "REFUSAL_NO_CHANNELS_CHOSEN",
    "REFUSAL_NO_LOADED_FOLDER",
    "REFUSAL_NO_MATCHING_CHANNELS",
    "REFUSAL_NO_SAVE_BLOCKS",
    "REFUSAL_NO_SAVE_CHANNELS",
    "REFUSAL_MULTIPLE_INPUTS",
    "ResultSetSink",
    "WorkflowRunPlan",
    "default_result_set_label",
    "find_overwrite_candidates",
    "plan_batch",
    "plan_calculate_and_save",
    "resolve_calculate_and_save_refusal",
    "plan_workflow_run",
    "run_batch",
    "supersede_running_batch",
]
