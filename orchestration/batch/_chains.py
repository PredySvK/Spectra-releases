"""Plan derived workflow chains and run their batches sequentially."""
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Optional, Sequence, TYPE_CHECKING

from core.jobs import CancelToken, JobState
from core.measurement_selection import MeasurementSelection
from core.workflow_graph import Workflow, resolve_workflow_chains
from ._plan import WorkflowRunPlan, plan_workflow_run
from ._batch_plan import BatchPlan, plan_batch
from ._workflow_run import BatchOutcome, run_batch, supersede_running_batch
from orchestration.jobs import JobRunner

if TYPE_CHECKING:
    from session.project import ProjectSession


@dataclass(frozen=True)
class WorkflowChainPlan:
    """A derived chain and its resolved Input selection or refusal."""
    workflow: Workflow
    run: WorkflowRunPlan


@dataclass(frozen=True)
class WorkflowChainBatch:
    """A derived graph paired with its complete batch plan."""
    workflow: Workflow
    batch: BatchPlan


def plan_workflow_chains(workflow: Workflow, find_selection: Callable[[str], Optional[MeasurementSelection]], *,
                         block_id: Optional[str] = None) -> tuple[WorkflowChainPlan, ...]:
    """Plan all chains, or just the chain containing the selected block."""
    if block_id is not None:
        workflow.block(block_id)  # Reject a stale selection rather than run all.
    return tuple(
        WorkflowChainPlan(chain, plan_workflow_run(chain, find_selection))
        for chain in resolve_workflow_chains(workflow)
        if block_id is None or block_id in chain.block_ids
    )


def plan_chain_batches(chains: tuple[WorkflowChainPlan, ...], *, sources: Sequence[Any],
                       schema: Mapping[str, Any], project_path: Optional[str],
                       data_roots: Sequence[Any]) -> tuple[WorkflowChainBatch, ...]:
    """Resolve every runnable chain against the pool before duplicate lookup."""
    batches = []
    for chain in chains:
        workflow = chain.workflow
        what = f"Run workflow '{workflow.name}'"
        if not chain.run.runnable:
            batch = BatchPlan(workflow.name, what, False,
                              messages=(f"WARNING: {what} skipped -- {chain.run.message}",))
        else:
            assert chain.run.selection is not None
            batch = plan_batch(
                workflow, chain.run.selection, sources=sources, schema=schema,
                project_path=project_path, data_roots=data_roots,
                label=workflow.name, what=what,
            )
        batches.append(WorkflowChainBatch(workflow, batch))
    return tuple(batches)


def run_chain_batches(chains: tuple[WorkflowChainBatch, ...], session: "ProjectSession", job_runner: JobRunner, *,
                      overwrite_by_block: Optional[Mapping[str, str]] = None,
                      compression=None, on_message: Optional[Callable[[str], None]] = None,
                      on_finished: Optional[Callable[[BatchOutcome], None]] = None,
                      cancel: Optional[CancelToken] = None) -> None:
    """Submit the next chain only after the previous chain has finished.

    Cancellation, supersession and project changes stop the remaining chains.
    Immediate callbacks are supported without recursive growth of the call stack.
    Owners replacing a sequence cancel its token before starting the new sequence;
    the job slot stops the active batch, while the token stops not-yet-submitted chains.
    """
    supersede_running_batch(job_runner)
    cancel = cancel or CancelToken()
    pending = iter(chain for chain in chains if chain.batch.runnable)
    project = session.project
    path = session.path
    advancing = False
    waiting = False
    stopped = False

    def advance() -> None:
        nonlocal advancing, waiting, stopped
        if advancing:
            return
        advancing = True
        try:
            while not waiting and not stopped and not cancel.is_cancelled:
                if session.project is not project or session.path != path:
                    stopped = True
                    return
                chain = next(pending, None)
                if chain is None:
                    return
                batch = replace(chain.batch, save_blocks=tuple(
                    replace(block, overwrite_result_set_id=(overwrite_by_block or {}).get(block.block_id))
                    for block in chain.batch.save_blocks
                ))
                waiting = True
                run_batch(batch, chain.workflow, session, job_runner,
                          compression=compression, on_message=on_message, on_finished=finished)
        finally:
            advancing = False

    def finished(outcome: BatchOutcome) -> None:
        nonlocal waiting, stopped
        waiting = False
        stopped = outcome.state in (JobState.CANCELLED, JobState.SUPERSEDED)
        try:
            if on_finished is not None:
                on_finished(outcome)
        finally:
            advance()

    advance()
