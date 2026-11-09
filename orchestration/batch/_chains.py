"""Plan the runs of one start -- workflow chains or Compute Result Set's result
sets -- as one shape, settle their overwrite targets, and run them in sequence.

Both entry points end in the same series of `WorkflowChainBatch`: a graph and
its complete `BatchPlan`, every save block's overwrite target already decided.
Nothing here stops a running batch; `run_batch` does that when the first new
run is submitted, before it opens a draft.
"""
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, TYPE_CHECKING

from core.jobs import CancelToken, JobState
from core.measurement_selection import MeasurementSelection
from core.tacho_cleaning import TachoCleaning
from core.workflow_graph import Workflow, resolve_workflow_chains
from io_modules.result_cache import params_hash
from ._overwrite import (
    OverwriteCandidate, UpcomingResultSet, UpcomingTarget, _save_key, find_overwrite_candidates_by_workflow,
)
from ._plan import CALCULATE_AND_SAVE_WHAT, CalculateAndSavePlan, WorkflowRunPlan, plan_workflow_run
from ._batch_plan import BatchPlan, plan_batch
from ._workflow_run import BatchOutcome, run_batch
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
    """
    One planned run: a graph paired with its complete batch plan. A start of
    either entry point is a series of these -- the chains of a workflow, or the
    result sets of a Compute Result Set.
    """
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


def plan_result_set_batches(plans: Sequence[CalculateAndSavePlan], *, sources: Sequence[Any],
                            schema: Mapping[str, Any], project_path: Optional[str],
                            data_roots: Sequence[Any],
                            what: str = CALCULATE_AND_SAVE_WHAT) -> tuple[WorkflowChainBatch, ...]:
    """
    Complete the runnable result sets of a Compute Result Set into the shape a
    Workflow run has. A refused `CalculateAndSavePlan` has no graph to pair, so
    it is left out -- its messages are the caller's to log.
    """
    return tuple(
        WorkflowChainBatch(plan.workflow, plan_batch(
            plan.workflow, plan.selection, sources=sources, schema=schema,
            project_path=project_path, data_roots=data_roots, label=plan.label, what=what,
        ))
        for plan in plans if plan.runnable
    )


def resolve_overwrite_candidates(session: "ProjectSession", chains: Sequence[WorkflowChainBatch], *,
                                 upcoming: Sequence[UpcomingResultSet] = ()
                                 ) -> tuple[Dict[str, OverwriteCandidate], ...]:
    """
    `{block_id: candidate}` per planned run, in order: the saved result set it
    duplicates, or else one a running or waiting Batch run (`upcoming`,
    `BatchRuns.upcoming_result_sets`) will write (#967). A refused run gets an
    empty dict: it will not write, so nobody is asked about its duplicates.
    Kept apart per run because Compute Result Set's graphs share block ids; a
    set is still claimed at most once across them all.
    """
    runnable = [chain for chain in chains if chain.batch.runnable]
    found = iter(find_overwrite_candidates_by_workflow(
        session, tuple(chain.workflow for chain in runnable), upcoming))
    return tuple(next(found) if chain.batch.runnable else {} for chain in chains)


def _with_save_blocks(chain: WorkflowChainBatch, aim: Callable[[Any], Any]) -> WorkflowChainBatch:
    """`chain` with every save block passed through `aim`."""
    return replace(chain, batch=replace(chain.batch, save_blocks=tuple(
        aim(block) for block in chain.batch.save_blocks)))


def apply_overwrites(chains: Sequence[WorkflowChainBatch],
                     candidates: Sequence[Mapping[str, OverwriteCandidate]]) -> tuple[WorkflowChainBatch, ...]:
    """
    The planned runs with each save block named in its own run's `candidates`
    pointed at that result set -- the answer "Overwrite". A saved set is named
    by its id; an upcoming one by `overwrite_upcoming`, turned into an id when
    the run starts (`resolve_upcoming_overwrites`). One mapping per run, as
    `resolve_overwrite_candidates` returns them; a block not named keeps the
    target it was planned with.
    """
    if len(chains) != len(candidates):
        raise ValueError("one overwrite mapping per planned run")

    def aimed_by(found: Mapping[str, OverwriteCandidate]):
        def aim(block):
            candidate = found.get(block.block_id)
            if candidate is None:
                return block
            return replace(block, overwrite_result_set_id=candidate.result_set_id,
                           overwrite_upcoming=candidate.upcoming)
        return aim

    return tuple(chain if not found else _with_save_blocks(chain, aimed_by(found))
                 for chain, found in zip(chains, candidates))


def build_upcoming_result_sets(chains: Sequence[WorkflowChainBatch], *, series: int, note: str,
                               ended: frozenset = frozenset()) -> tuple[UpcomingResultSet, ...]:
    """
    The result sets the runnable runs of one Batch run (key `series`) will
    write, in run order -- the runs at the indices in `ended` left out, they
    have written already or never will (#967).
    """
    upcoming = []
    for index, chain in enumerate(chains):
        if not chain.batch.runnable or index in ended:
            continue
        for block in chain.batch.save_blocks:
            kind, params = _save_key(chain.workflow, block.block_id)
            upcoming.append(UpcomingResultSet(kind, params_hash(params), block.set_label, note,
                                              UpcomingTarget(series, index, block.block_id)))
    return tuple(upcoming)


def resolve_upcoming_overwrites(chains: Sequence[WorkflowChainBatch], written: Mapping[UpcomingTarget, str]
                                ) -> tuple[tuple[WorkflowChainBatch, ...], tuple[str, ...]]:
    """
    At the start of a Batch run, point every save block aimed at an upcoming
    set (`overwrite_upcoming`) at the id that run wrote -- `written`, from the
    runs' `BatchOutcome.written_ids`. When it wrote nothing (failed, cancelled,
    interrupted), the block saves as a new set and one log line says so;
    nobody is asked (#967). Returns the runs and the log lines.
    """
    messages = []

    def aim(block):
        if block.overwrite_upcoming is None:
            return block
        result_set_id = written.get(block.overwrite_upcoming)
        if result_set_id is None:
            messages.append(f"PROJECT: {block.sink_what} -- the result set it was to overwrite was "
                            f"never written; saving it as a new result set.")
        return replace(block, overwrite_result_set_id=result_set_id, overwrite_upcoming=None)

    resolved = tuple(chain if not any(block.overwrite_upcoming for block in chain.batch.save_blocks)
                     else _with_save_blocks(chain, aim) for chain in chains)
    return resolved, tuple(messages)


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


#: Why a run never started, as its "not started -- ..." log line says it.
_SUPERSEDED_WHY = "superseded by a newer run"
_PROJECT_CHANGED_WHY = "the project changed"


@dataclass(frozen=True)
class _ProjectStamp:
    """
    The project a run was started under. The session is one object that swaps
    its project on New / Open and its path on Save As, so "is this still that
    project?" compares both -- in this one place, for a sequence between its
    chains and for a Batch run waiting its turn (§1.238, §1.266).
    """
    project: Any
    path: Optional[str]

    @classmethod
    def of(cls, session: "ProjectSession") -> "_ProjectStamp":
        return cls(session.project, session.path)

    def changed_in(self, session: "ProjectSession") -> bool:
        return session.project is not self.project or session.path != self.path


def _unstarted_outcome(chain: WorkflowChainBatch, state: JobState, why: str) -> BatchOutcome:
    return BatchOutcome(chain.batch.label, False,
                        (f"PROJECT: {chain.batch.what} not started -- {why}.",), state)


def _report_unstarted(chains: Sequence[WorkflowChainBatch], state: JobState, why: str,
                      on_finished: Optional[Callable[[BatchOutcome], None]]) -> None:
    """
    One outcome per run of a series that never reached the job runner: a
    refused run `FAILED` as it would have at its start, every other run "not
    started" with `why`.
    """
    _report_each(on_finished, [
        _unstarted_outcome(chain, state, why) if chain.batch.runnable
        else BatchOutcome(chain.batch.label, False, (), JobState.FAILED)
        for chain in chains
    ])


def run_chain_batches(chains: tuple[WorkflowChainBatch, ...], session: "ProjectSession", job_runner: JobRunner, *,
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
    the token stops not-yet-submitted chains. The running batch is stopped only
    when the first chain of this sequence is submitted (`run_batch`), so a
    sequence in which every chain was refused leaves it running.
    """
    cancel = cancel or CancelToken()
    pending = iter(chain for chain in chains if chain.batch.runnable)
    started_under = _ProjectStamp.of(session)
    advancing = False
    waiting = False
    stopped_by: Optional[JobState] = None

    def resolve_stop() -> Optional[tuple[JobState, str]]:
        if cancel.is_cancelled or stopped_by is JobState.SUPERSEDED:
            return JobState.SUPERSEDED, _SUPERSEDED_WHY
        if stopped_by is JobState.CANCELLED:
            return JobState.CANCELLED, "the run before it was cancelled"
        if started_under.changed_in(session):
            return JobState.CANCELLED, _PROJECT_CHANGED_WHY
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
                waiting = True
                try:
                    run_batch(chain.batch, chain.workflow, session, job_runner,
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
