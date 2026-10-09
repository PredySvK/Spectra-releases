"""
The planning half of a batch run: `plan_batch` decides *what* a run over a
MeasurementSelection would do -- it validates the graph, resolves the selection,
maps data roots and works out each save node's scope. It touches no disk and no
queue, and it says "no" as data: a refusal is a `BatchPlan` with
`runnable=False` whose messages already spell out why (ARCHITECTURE_DECISIONS
§1.71). `save_channel_types` hands the save nodes' type scope down to
`resolve()` so an `all_channels` selection never feeds the measurement's own
tacho in as a vibration channel.

No Qt, no window and no app_context.
"""
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Set, Tuple

from core.measurement_selection import MeasurementSelection
from core.workflow_graph import SaveSpec, Workflow
from io_modules.project_store import resolve_root
from selection.measurement_selection import (
    resolve as resolve_selection,
    resolve_save_sources,
)
from signal_processing.workflow import check_versions, save_node_ids, validate_graph


@dataclass(frozen=True)
class PlannedSaveNode:
    """
    One save node as the plan sees it: everything decided before a draft exists
    -- which measurements it covers, what its result set will be called, which
    existing set (if any) it replaces.

    `sink_what` is the name the sink puts in its own messages: the run's `what`
    when one node saves, and `what '<set label>'` when several do, so two
    "Saved result set" lines are not left to be told apart by the set they name.
    """
    node_id: str
    set_label: str
    overwrite_result_set_id: Optional[str]
    source_ids: frozenset
    save: SaveSpec
    sink_what: str


@dataclass(frozen=True)
class BatchStep:
    """One measurement's worth of work: the file, where it lives, its channels."""
    entry: Any
    directory: str
    channel_labels: Tuple[str, ...]


@dataclass(frozen=True)
class BatchPlan:
    """
    What a run would do -- or why it will not happen -- as data.

    `messages` are the log lines the caller emits in order, the refusal
    included: a plan that is not `runnable` ends its messages with the line
    saying so, so the caller logs the same list either way and then looks at one
    flag. That is what keeps "the selection resolved to no runs" a decision of
    this floor rather than of whoever draws the window.
    """
    label: str
    what: str
    runnable: bool
    messages: Tuple[str, ...] = ()
    save_nodes: Tuple[PlannedSaveNode, ...] = ()
    steps: Tuple[BatchStep, ...] = ()
    #: Failures known before the job starts (a file whose data folder is gone).
    #: They ride along to the end and are reported with the run's own errors.
    errors: Tuple[str, ...] = ()
    #: The line announcing the submitted job, emitted by `run_batch`.
    submit_message: str = ""

    @property
    def job_label(self) -> str:
        # Short on purpose: the status strip is narrow (#469). The log keeps
        # the full "Calculate & Save Data" wording.
        return f"Compute '{self.label}'"


def save_channel_types(workflow: Workflow) -> Optional[Set[str]]:
    """
    The channel types the run has to read at all: the union of the save nodes'
    `SaveSpec.channel_types`, or None as soon as one node imposes no constraint.

    None is "every type", so one unconstrained save node widens the run back to
    everything -- narrowing on the union would silently drop channels that node
    asked to keep. This is what stops an `all_channels` selection from feeding
    the tacho in as a vibration channel (`resolve`'s `channel_types`).
    """
    types: Set[str] = set()
    for node_id in save_node_ids(workflow):
        node_types = workflow.node(node_id).save.channel_types
        if not node_types:
            return None
        types.update(node_types)
    return types or None


def _refused(label: str, what: str, messages: List[str]) -> BatchPlan:
    return BatchPlan(label=label, what=what, runnable=False, messages=tuple(messages))


def plan_batch(workflow: Workflow, selection: MeasurementSelection, *,
               sources: Sequence[Any], schema: Mapping[str, Any],
               project_path: Optional[str], data_roots: Sequence[Any],
               label: str, what: str = "Run workflow",
               overwrite_by_node: Optional[Mapping[str, str]] = None) -> BatchPlan:
    """
    Decide what a run over `selection` would do, without touching a queue or a
    draft folder.

    `sources` is the project's whole SourceEntry list -- which of them are in
    the pool is this floor's rule, not the caller's. `schema` is the pool's
    merged master schema (the metadata facets a save node may filter on), and
    `project_path` with `data_roots` is what turns a root id into a folder on
    this machine.

    `overwrite_by_node` maps a save node id to the id of the result set that
    node's output should replace in place. A node absent from it starts a fresh
    set. A branching graph with two save nodes can overwrite one and keep the
    other -- there is no `single_save` gate on overwrite, that was a silent trap
    (the second save node's overwrite id was dropped).

    `what` is what the user pressed, for the log and the job title. The Workflow
    tab's Run button leaves the default; the ribbon fast path passes
    "Calculate & Save Data" so a batch does not report itself under a name that
    appears nowhere in the UI the user was looking at.
    """
    overwrite_by_node = overwrite_by_node or {}

    try:
        validate_graph(workflow)
    except ValueError as error:
        return _refused(label, what, [f"ERROR: {what} skipped -- {error}"])

    save_ids = save_node_ids(workflow)
    if not save_ids:
        return _refused(label, what, [f"ERROR: {what} skipped -- no node is marked to save."])

    messages = [f"WARNING: {what} -- {warning}" for warning in check_versions(workflow)]

    candidates = [entry for entry in sources if entry.in_pool]
    resolution = resolve_selection(
        selection, candidates, schema, channel_types=save_channel_types(workflow),
        time_responses_only=True,
    )
    messages.append(f"SYSTEM: {what} over {resolution.describe()}.")
    for relpath in resolution.skipped_non_time_sources:
        messages.append(f"SYSTEM: {what} -- {relpath}: Imported results skipped (not time responses).")
    for note in resolution.unevaluable_constraints:
        messages.append(f"WARNING: {what} -- {note}")
    if resolution.leaf_count == 0:
        messages.append(f"WARNING: {what} skipped -- the selection resolved to no runs.")
        return _refused(label, what, messages)

    directory_by_root = {}
    for root in data_roots:
        resolved = resolve_root(project_path, root)
        if resolved is not None:
            directory_by_root[root.id] = resolved

    # Only decides the default label ("<label>" vs "<label> - <node_id>"),
    # never overwrite -- that is per node now.
    single_save = len(save_ids) == 1
    save_nodes: List[PlannedSaveNode] = []
    for node_id in save_ids:
        node = workflow.node(node_id)
        kept = resolve_save_sources(node.save, resolution.sources, schema)
        set_label = node.save.label or (label if single_save else f"{label} - {node_id}")
        sink_what = what if single_save else f"{what} '{set_label}'"
        for note in kept.unevaluable_constraints:
            messages.append(f"WARNING: {sink_what} -- {note}")
        save_nodes.append(PlannedSaveNode(
            node_id=node_id, set_label=set_label,
            overwrite_result_set_id=overwrite_by_node.get(node_id),
            source_ids=frozenset(source.id for source in kept.sources), save=node.save,
            sink_what=sink_what,
        ))

    wanted_ids = set().union(*(node.source_ids for node in save_nodes))
    errors: List[str] = []
    steps: List[BatchStep] = []
    for entry in resolution.sources:
        if entry.id not in wanted_ids:
            continue    # filtered out of every save node by its facet
        directory = directory_by_root.get(entry.root_id)
        if directory is None:
            errors.append(f"{entry.relpath}: its data folder is not available")
            continue
        steps.append(BatchStep(
            entry=entry, directory=directory,
            channel_labels=tuple(resolution.channels_by_source[entry.id]),
        ))

    if not steps:
        # Decided here rather than after the drafts are open: nothing is on disk
        # yet, so a run that cannot happen never creates a staging folder only
        # to delete it again.
        messages.append(
            f"WARNING: {what} skipped -- no source file to run "
            f"(none located, or every one filtered out by a node's save filter)."
        )
        return _refused(label, what, messages)

    set_count = f"{len(save_ids)} result set(s)" if not single_save else "1 result set"
    return BatchPlan(
        label=label, what=what, runnable=True, messages=tuple(messages),
        save_nodes=tuple(save_nodes), steps=tuple(steps), errors=tuple(errors),
        submit_message=(f"PROJECT: {what} '{label}' over {len(steps)} file(s) "
                        f"-> {set_count}..."),
    )
