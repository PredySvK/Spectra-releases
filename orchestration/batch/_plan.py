# =====================================================================
# FILE: orchestration/batch/_plan.py
# =====================================================================
"""
Planning ribbon Calculate & Save and Workflow-tab Run as data.

Pure functions (no Qt, no AppContext) coordinating:
- `plan_calculate_and_save`: whether a fast-path ribbon batch run can happen
  (checks loaded runs, channel types, chosen channels), and if so, constructs the
  workflow, selection, and label.
- `plan_workflow_run`: whether a workflow can run (validates the graph, sole input
  block, input selection resolution, save blocks), and if so, resolves the input
  selection.

Both say "no" the way `BatchPlan` does:
`runnable=False` with `messages` that are the log lines saying why.
"""
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Tuple

from core.measurement_selection import MODE_EXPLICIT, MeasurementSelection
from core.filter_card_config import COLUMN_CHANNEL, COLUMN_DIRECTION
from core.workflow_graph import SaveSpec, Workflow
from selection.measurement_selection import (
    channel_identities_by_type,
    whole_pool_selection,
)
from selection.source_facets import EMPTY_FACET_VALUE, channel_identity_sort_key, pool_source_entries
from signal_processing.workflow import workflow_from_configs
from signal_processing.workflow_readiness import resolve_chain_readiness

from orchestration.batch._label import default_result_set_label

CALCULATE_AND_SAVE_WHAT = "Calculate & Save Data"


def _skipped(what: str, why: str) -> Tuple[str, ...]:
    return (f"WARNING: {what} skipped -- {why}",)


@dataclass(frozen=True)
class CalculateAndSaveRequest:
    """
    What the user asked a ribbon Calculate & Save run for -- the Compute Result
    Set dialog's answer, handed to the batch as a value (#770).

    It used to travel through QSettings: the dialog wrote it, the ribbon read
    it back, and the only contract was a key name three files had to spell the
    same way. `channel_types=None` means any type. `orders` is Order Tracking
    only; the handler swaps it into that tab's config.
    """
    channel_types: Optional[frozenset] = None
    all_channels: bool = True
    picked_identities: frozenset = frozenset()
    orders: Tuple[float, ...] = ()
    custom_label: str = ""


@dataclass(frozen=True)
class CalculateAndSavePlan:
    """The planned outcome of a Ribbon Calculate & Save request."""
    workflow: Optional[Workflow] = None
    selection: Optional[MeasurementSelection] = None
    label: str = ""
    runnable: bool = True
    messages: Tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowRunPlan:
    """The planned outcome of a Workflow tab Run request."""
    selection: Optional[MeasurementSelection] = None
    runnable: bool = True
    messages: Tuple[str, ...] = ()


def resolve_calculate_and_save_refusal(
    loaded_runs: Sequence[Any],
    all_channels: bool,
    picked_identities: Iterable[Tuple[str, Optional[str]]],
) -> Tuple[str, ...]:
    """
    The log lines refusing a "Calculate & Save Data" run for what needs no
    source lookup, so the GUI can give them before registering any folder;
    empty when nothing refuses it yet.
    """
    if not loaded_runs:
        return _skipped(CALCULATE_AND_SAVE_WHAT, "no folder is loaded.")
    if not all_channels and not set(picked_identities):
        return _skipped(CALCULATE_AND_SAVE_WHAT, "no channels chosen. Use 'Choose…' first.")
    return ()


def plan_calculate_and_save(
    block_type: str,
    config: Any,
    request: CalculateAndSaveRequest = CalculateAndSaveRequest(),
    *,
    loaded_runs: Sequence[Any] = (),
    sources_by_path: Optional[Mapping[str, Any]] = None,
) -> CalculateAndSavePlan:
    """
    Plan a fast-path ribbon batch run ("Calculate & Save Data") as pure data.

    Decides whether the run can proceed given the loaded files and the
    request's channel scope.
    If valid, constructs:
    - SaveSpec with channel scope and custom label
    - Workflow from config with the SaveSpec on the terminal block
    - MeasurementSelection in MODE_EXPLICIT over the pool sources
    - The label for the result set

    Returns a CalculateAndSavePlan with runnable=True and the built objects,
    or runnable=False with the log lines saying why.
    """
    runs = list(loaded_runs)
    channel_types = request.channel_types
    all_channels = request.all_channels
    picked_identities = set(request.picked_identities)
    custom_label = request.custom_label
    refusal = resolve_calculate_and_save_refusal(runs, all_channels, picked_identities)
    if refusal:
        return CalculateAndSavePlan(runnable=False, messages=refusal)

    sources_map = sources_by_path or {}
    available = channel_identities_by_type(
        runs, set(channel_types) if channel_types is not None else None, sources_map,
    )
    if not available:
        return CalculateAndSavePlan(
            runnable=False,
            messages=_skipped(CALCULATE_AND_SAVE_WHAT, "no matching channels in the loaded folder."),
        )

    if all_channels:
        wanted = {
            (base, direction)
            for base, directions in available.items()
            for direction in directions
        }
    else:
        wanted = picked_identities

    identities = tuple(sorted(wanted, key=channel_identity_sort_key))

    column_values = {
        COLUMN_CHANNEL: tuple(sorted({base for base, _ in identities})),
        COLUMN_DIRECTION: tuple(sorted({direction or EMPTY_FACET_VALUE for _, direction in identities})),
    }
    workflow_draft = workflow_from_configs(block_type, [(block_type, config)])
    draft_selection = MeasurementSelection(
        name="",
        mode=MODE_EXPLICIT,
        source_ids=(),
        column_values=column_values,
    )
    derived_label = default_result_set_label(
        workflow_draft, draft_selection, total_available_bases=len(available)
    )

    pool_entries = pool_source_entries(runs, sources_map)
    selection = MeasurementSelection(
        name=derived_label,
        mode=MODE_EXPLICIT,
        source_ids=tuple(entry.id for entry in pool_entries),
        channel_identities=None if all_channels else identities,
    )

    stripped_custom_label = (custom_label or "").strip()
    save = SaveSpec(
        all_channels=all_channels,
        channel_identities=identities,
        channel_types=tuple(sorted(channel_types or ())),
        label=stripped_custom_label,
    )
    final_workflow = workflow_from_configs(
        block_type,
        [(block_type, config)],
        selection_name=selection.name,
        save=save,
    )

    final_label = (
        stripped_custom_label
        or selection.name
        or default_result_set_label(final_workflow, selection)
    )

    return CalculateAndSavePlan(
        workflow=final_workflow,
        selection=selection,
        label=final_label,
        runnable=True,
    )


def plan_workflow_run(
    workflow: Workflow,
    find_selection: Callable[[str], Optional[MeasurementSelection]],
    *,
    what: str = "Run workflow",
) -> WorkflowRunPlan:
    """
    Plan a Workflow-tab Run as pure data.

    The chain's readiness (`resolve_chain_readiness`) decides: its first issue
    is the refusal. A ready chain gets its input selection resolved (Whole Data
    Pool or a named selection).

    Returns a WorkflowRunPlan with runnable=True and resolved selection, or
    runnable=False with the log line saying why; `what` is the run it names.
    """
    issues = resolve_chain_readiness(workflow, find_selection)
    if issues:
        return WorkflowRunPlan(runnable=False, messages=_skipped(what, issues[0].text))

    input_spec = next(block for block in workflow.blocks if block.is_input).input
    selection = (whole_pool_selection() if input_spec.whole_pool
                 else find_selection(input_spec.selection_name))

    return WorkflowRunPlan(selection=selection, runnable=True)
