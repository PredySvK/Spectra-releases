"""Plan derived workflow chains and run their batches sequentially."""
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Optional, Sequence, TYPE_CHECKING

from core.jobs import CancelToken, JobState
from core.measurement_selection import MeasurementSelection
from core.tacho_cleaning import TachoCleaning
from core.workflow_graph import Workflow, resolve_workflow_chains
from ._plan import WorkflowRunPlan, plan_workflow_run
from ._batch_plan import BatchPlan, plan_batch
from ._workflow_run import BatchOutcome, run_batch, supersede_running_batch
from orchestration.jobs import JobRunner
from signal_processing.workflow import build_workflow_with_tacho_cleaning

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


def _what(workflow: Workflow) -> str:
    return f"Run workflow '{workflow.name}'"


def plan_workflow_chains(workflow: Workflow, find_selection: Callable[[str], Optional[MeasurementSelection]], *,
                         tacho_cleaning: TachoCleaning,
                         block_id: Optional[str] = None) -> tuple[WorkflowChainPlan, ...]:
    """Plan all chains, or just the chain containing the selected block.

    `tacho_cleaning` is the applied Settings: every chain runs, and is
    identified, with it, as the live computation is.
    """
    if block_id is not None:
        workflow.block(block_id)  # Reject a stale selection rather than run all.
    workflow = build_workflow_with_tacho_cleaning(workflow, tacho_cleaning)
    return tuple(
        WorkflowChainPlan(chain, plan_workflow_run(chain, find_selection, what=_what(chain)))
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
        what = _what(workflow)
        if not chain.run.runnable:
            batch = BatchPlan(workflow.name, what, False, messages=chain.run.messages)
        else:
            assert chain.run.selection is not None
            batch = plan_batch(
                workflow, chain.run.selection, sources=sources, schema=schema,
                project_path=project_path, data_roots=data_roots,
                label=workflow.name, what=what,
            )
        batches.append(WorkflowChainBatch(workflow, batch))
    return tuple(batches)


def _report_each(on_finished: Optional[Callable[[BatchOutcome], None]],
                 outcomes: Sequence[BatchOutcome]) -> None:
    """Deliver all outcomes; a broken listener must not swallow the later ones."""
    if on_finished is None:
        return
    first_error = None
    for outcome in outcomes:
        try:
            on_finished(outcome)
        except Exception as error:
            first_error = first_error or error
    if first_error is not None:
        raise first_error


def _unstarted_outcome(chain: WorkflowChainBatch, state: JobState, why: str) -> BatchOutcome:
    return BatchOutcome(chain.batch.label, False,
                        (f"PROJECT: {chain.batch.what} not started -- {why}.",), state)


def run_chain_batches(chains: tuple[WorkflowChainBatch, ...], session: "ProjectSession", job_runner: JobRunner, *,
                      overwrite_by_block: Optional[Mapping[str, str]] = None,
                      compression=None, on_message: Optional[Callable[[str], None]] = None,
                      on_finished: Optional[Callable[[BatchOutcome], None]] = None,
                      cancel: Optional[CancelToken] = None) -> None:
    """Submit the next chain only after the previous chain has finished.

    `on_finished` hears exactly one outcome per chain, so a listener
    waiting for a run never has to infer its end from the state of another:

    - a refused chain reports `FAILED` before the first submit, with no messages
      of its own -- the plan's messages were for whoever planned it to log;
    - a chain that ran reports what `run_batch` reports;
    - a chain never started reports the cause that stopped the sequence, with
      `written=False` and a log line: `SUPERSEDED` (token, or a superseded
      predecessor) or `CANCELLED` (a cancelled predecessor, a project change).

    Immediate callbacks are supported without recursive growth of the call stack.
    Owners replacing a sequence cancel its token before starting the new sequence;
    the job slot stops the active batch, while the token stops not-yet-submitted chains.

    `overwrite_by_block` replaces every save block's overwrite target; None
    keeps the targets the batches were planned with.
    """
    supersede_running_batch(job_runner)
    cancel = cancel or CancelToken()
    pending = iter(chain for chain in chains if chain.batch.runnable)
    project = session.project
    path = session.path
    advancing = False
    waiting = False
    stopped_by: Optional[JobState] = None

    def resolve_stop() -> Optional[tuple[JobState, str]]:
        if cancel.is_cancelled or stopped_by is JobState.SUPERSEDED:
            return JobState.SUPERSEDED, "superseded by a newer run"
        if stopped_by is JobState.CANCELLED:
            return JobState.CANCELLED, "the run before it was cancelled"
        if session.project is not project or session.path != path:
            return JobState.CANCELLED, "the project changed"
        return None

    def advance() -> None:
        nonlocal advancing, waiting
        if advancing:
            return
        advancing = True
        listener_error = None
        try:
            while not waiting:
                stop = resolve_stop()
                if stop is not None:
                    _report_each(on_finished, [_unstarted_outcome(chain, *stop) for chain in pending])
                    break
                chain = next(pending, None)
                if chain is None:
                    break
                batch = chain.batch if overwrite_by_block is None else replace(chain.batch, save_blocks=tuple(
                    replace(block, overwrite_result_set_id=overwrite_by_block.get(block.block_id))
                    for block in chain.batch.save_blocks
                ))
                waiting = True
                try:
                    run_batch(batch, chain.workflow, session, job_runner,
                              compression=compression, on_message=on_message, on_finished=finished)
                except Exception as error:
                    if waiting:  # run_batch itself failed: no outcome was reported.
                        raise
                    # A listener failed on an immediate outcome; the rest still report.
                    listener_error = listener_error or error
        finally:
            advancing = False
        if listener_error is not None:
            raise listener_error

    def finished(outcome: BatchOutcome) -> None:
        nonlocal waiting, stopped_by
        waiting = False
        stopped_by = outcome.state if outcome.state in (JobState.CANCELLED, JobState.SUPERSEDED) else None
        try:
            _report_each(on_finished, [outcome])
        finally:
            advance()

    try:
        _report_each(on_finished, [BatchOutcome(chain.batch.label, False, (), JobState.FAILED)
                                   for chain in chains if not chain.batch.runnable])
    finally:
        advance()
