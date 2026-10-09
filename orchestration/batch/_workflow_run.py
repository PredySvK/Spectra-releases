"""
The lifecycle half of a batch run: `run_batch` performs a runnable `BatchPlan`
against a `JobRunner` as one background job (ARCHITECTURE_DECISIONS §1.6, §1.13,
Epic P phases 5 / 7A / 7B). It supersedes the previous run *before* opening any
draft, opens one draft per save node, submits a step per measurement, and
reports the whole run once, through `on_finished`.

The other two thirds of the runner: `_batch_plan` decides what a run would do,
`_source_chain` is the worker-thread body of one step. This is the only batch
path -- all three ribbon tabs and the Workflow tab's Run button come through
`plan_batch` + `run_batch`.

`run_graph`'s `scratch` bag, one per measurement, restores the per-file
`TrackingPlan` the pre-Epic-P controller used to build by hand; the numbers are
pinned by tests/test_order_tracking_runner_parity.py.

No Qt, no window and no app_context: every message this produces is returned as
data, and the thin wrapper in gui/workspace/workflow_run_controller.py owns when
and how to show it.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.jobs import JobRecord, JobState, job_step
from core.workflow_graph import Workflow
from io_modules.result_cache.cache_layout import result_params_from_node
from orchestration.batch._batch_plan import BatchPlan
from orchestration.batch._result_set_sink import ResultSetSink
from orchestration.batch._source_chain import _NodeSavePlan, _run_source_chain
from orchestration.jobs import JobRunner
from signal_processing.workflow import spec_for

#: The job slot a batch holds: a second run supersedes the first rather than
#: racing it into the same result-set folders.
BATCH_SLOT_KEY = "workflow_run"


@dataclass(frozen=True)
class BatchOutcome:
    """
    How a run ended: the label it was started under, whether anything was
    written, the messages to log, and the job's terminal state -- `FAILED` when
    the run never reached the queue at all (no draft could be opened).
    """
    label: str
    written: bool
    messages: Tuple[str, ...]
    state: JobState


# ---- running ----------------------------------------------------------------


@dataclass
class _RunState:
    """
    What the job's callbacks share, built whole *before* `submit`: the port
    allows `on_done` to arrive before `submit` returns (§1.70, contract 2).
    """
    sinks: Dict[str, ResultSetSink]
    entries: List[Any]
    errors: List[str]
    node_errors: Dict[str, List[str]] = field(default_factory=dict)
    # The session and the project file the drafts were opened under. The
    # session is one object that swaps its project on New / Open / Save As, so
    # by the time `on_done` arrives it may name another project; committing
    # then would register the set in a project whose folder does not hold it
    # (#329).
    session: Any = None
    project_path: Optional[str] = None


def _open_save_plan(plan: BatchPlan, workflow: Workflow, session, *, compression) -> tuple:
    """
    Open one result-set draft per save node and pair it with its sink and its
    `_NodeSavePlan`. Returns (sinks, save_plan).

    Its own function because it is the one block that has to unwind itself:
    `begin_result_set` can fail on the second of two save nodes, and the first
    node's draft is a staging folder already on disk. On any failure every draft
    opened so far in this call is aborted and the original OSError/ValueError is
    re-raised for `run_batch` to report.
    """
    sinks: Dict[str, ResultSetSink] = {}
    save_plan: Dict[str, _NodeSavePlan] = {}
    opened: List[object] = []
    for node in plan.save_nodes:
        try:
            draft = session.begin_result_set(
                spec_for(workflow.node(node.node_id).block_type).produces,
                result_params_from_node(workflow, node.node_id), label=node.set_label,
                overwrite_result_set_id=node.overwrite_result_set_id,
                compression=compression,
            )
        except (OSError, ValueError):
            for spent in opened:
                session.abort_result_set(spent)
            raise
        opened.append(draft)
        sinks[node.node_id] = ResultSetSink(
            session, draft, all_channels=node.save.all_channels,
            overwrite_result_set_id=node.overwrite_result_set_id, what=node.sink_what,
        )
        save_plan[node.node_id] = _NodeSavePlan(
            node_id=node.node_id, draft=draft,
            source_ids=set(node.source_ids), save=node.save,
        )
    return sinks, save_plan


def supersede_running_batch(job_runner: JobRunner) -> None:
    """
    Stop whatever batch is running, whether or not this one will replace it.

    Pressing Run always ends the live batch, even when the new run turns out to
    be refused -- that is what the runner did before the plan and the run were
    two halves, and a refusal is not the moment to discover that the old batch
    is still writing.
    """
    job_runner.cancel_slot(BATCH_SLOT_KEY)


def run_batch(plan: BatchPlan, workflow: Workflow, session, job_runner: JobRunner, *,
              compression=None, on_message: Optional[Callable[[str], None]] = None,
              on_finished: Optional[Callable[[BatchOutcome], None]] = None) -> None:
    """
    Perform a runnable `plan`: one job with one step per source file (ADR §1.13,
    §1.6 phases 5 / 7B).

    `on_message` takes the lines the launch itself produces -- the announcement
    of the submitted job, or the one error that stops it from being submitted at
    all. They are delivered *before* `submit`, because `on_done` may arrive
    before `submit` returns (§1.70, contract 2) and would otherwise report the
    finished run above the line announcing it. Everything the run has to say
    afterwards arrives once, through `on_finished`.

    The previous run in this slot is superseded *before* any draft is opened,
    not when `submit` eventually calls `cancel_slot` itself: otherwise the old
    job outlives the new `begin_result_set` calls and its `abort()` then deletes
    the folders the new run is about to write into (audit 02, S1/1.4).

    Only a `runnable` plan may be handed here -- a refused one has already said
    why, in its own messages.
    """
    supersede_running_batch(job_runner)

    try:
        sinks, save_plan = _open_save_plan(plan, workflow, session, compression=compression)
    except (OSError, ValueError) as error:
        _say(on_message, f"ERROR: {plan.what} skipped -- {error}")
        _finish(on_finished, plan, False, [], JobState.FAILED)
        return

    state = _RunState(sinks=sinks, entries=[step.entry for step in plan.steps],
                      errors=list(plan.errors), session=session,
                      project_path=session.path)
    steps = [
        job_step(step.entry.relpath, _run_source_chain, step.entry, step.directory,
                 list(step.channel_labels), workflow, save_plan)
        for step in plan.steps
    ]

    # Last, and after everything the callbacks read has been built: `on_done`
    # may fire inside this call (§1.70, contract 2).
    _say(on_message, plan.submit_message)
    job_runner.submit(
        plan.job_label, steps,
        lane="batch", slot_key=BATCH_SLOT_KEY, cancel_token_keyword="cancel",
        progress_keyword="progress_fn",
        # One unit per channel, so the job reads 12/30 channels, not 0/1 files.
        step_sizes=[max(1, len(step.channel_labels)) for step in plan.steps],
        on_step=lambda payload, index: _on_source_done(state, payload, index),
        on_error=lambda message, index: _on_source_failed(state, message, index),
        on_done=lambda record: _on_run_done(plan, state, record, on_finished),
    )


def _say(on_message: Optional[Callable[[str], None]], message: str) -> None:
    if on_message is not None:
        on_message(message)


# ---- job callbacks (the thread that called submit) --------------------------


def _on_source_done(state: _RunState, payload, index: int) -> None:
    manifest_by_node, errors, node_errors, clipped_nodes = payload
    state.errors.extend(f"{message}" for message in errors)
    for node_id, messages in node_errors.items():
        state.node_errors.setdefault(node_id, []).extend(messages)
    for node_id, entry in manifest_by_node.items():
        sink = state.sinks.get(node_id)
        if sink is not None:
            sink.add(entry, index, f_stop_clipped=node_id in clipped_nodes)


def _on_source_failed(state: _RunState, message: str, index: int) -> None:
    state.errors.append(f"{state.entries[index].relpath}: {message}")


def _on_run_done(plan: BatchPlan, state: _RunState, record: JobRecord,
                 on_finished: Optional[Callable[[BatchOutcome], None]]) -> None:
    what = plan.what
    messages: List[str] = []

    if record.state is not JobState.DONE:
        # Cancelled: each result set would cover an arbitrary subset of what
        # was asked for. The shards already written are deleted rather than
        # committed, so the project never gains a set whose label promises
        # coverage it does not have.
        for sink in state.sinks.values():
            sink.abort()
        # SUPERSEDED is not CANCELLED: a newer run replaced this one, the
        # user never asked for it to stop, and the log must not tell them
        # they cancelled something (audit 02, S3/3.7a, ADR 1.13).
        if record.state is JobState.SUPERSEDED:
            messages.append(f"PROJECT: {what} superseded by a newer run -- "
                            f"nothing was written.")
        else:
            messages.append(f"PROJECT: {what} cancelled -- nothing was written.")
        _finish(on_finished, plan, False, messages, record.state)
        return

    if state.session.path != state.project_path:
        # The user opened, started or Save As'd another project while this
        # ran. The drafts sit in the old project's cache folder, which the
        # session no longer points at: committing would add a set to the new
        # project that names a folder it does not have, and leave the old
        # project an orphan folder it never registered (#329).
        for sink in state.sinks.values():
            sink.abort()
        messages.append(f"PROJECT: {what} finished after the project changed -- "
                        f"nothing was written.")
        _finish(on_finished, plan, False, messages, record.state)
        return

    # dict.fromkeys, not a set: a failure that hit two save nodes is one
    # event and belongs in the log once, in the order it happened.
    owned = dict.fromkeys(
        message for node_messages in state.node_errors.values() for message in node_messages
    )
    for message in [*state.errors, *owned]:
        messages.append(f"ERROR: {what} -- {message}")

    written = False
    for node_id, sink in state.sinks.items():
        # Only this node's own failures downgrade its set. Marking every set
        # "partial" because a sibling node's channel failed made a set that
        # is in fact complete miss the cache forever (audit 02, finding S1/1.11).
        failed = bool(state.errors) or bool(state.node_errors.get(node_id))
        sink_written, sink_messages = sink.finish("partial" if failed else "complete")
        messages.extend(sink_messages)
        written = sink_written or written
    _finish(on_finished, plan, written, messages, record.state)


def _finish(on_finished, plan: BatchPlan, written: bool, messages: List[str],
            state: JobState) -> None:
    if on_finished is not None:
        on_finished(BatchOutcome(label=plan.label, written=written,
                                 messages=tuple(messages), state=state))
