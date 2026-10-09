# =====================================================================
# FILE: orchestration/batch/_plan.py
# =====================================================================
"""
Planning ribbon Calculate & Save and Workflow-tab Run as data.

Pure functions (no Qt, no AppContext) coordinating:
- `plan_calculate_and_save`: whether a fast-path ribbon batch run can happen
  (checks loaded runs, channel types, chosen channels), and if so, constructs the
  workflow, selection, and label; otherwise returns the refusal reason.
- `plan_workflow_run`: whether a workflow can run (validates the graph, sole input
  node, input selection resolution, save nodes), and if so, resolves the input
  selection; otherwise returns the refusal reason and error message.
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
from signal_processing.workflow import (
    save_node_ids,
    sole_input_node_id,
    validate_graph,
    workflow_from_configs,
)

from orchestration.batch._label import default_result_set_label

# Refusal reasons for plan_calculate_and_save
REFUSAL_NO_LOADED_FOLDER = "no_loaded_folder"
REFUSAL_NO_MATCHING_CHANNELS = "no_matching_channels"
REFUSAL_NO_CHANNELS_CHOSEN = "no_channels_chosen"

# Refusal reasons for plan_workflow_run
REFUSAL_INVALID_GRAPH = "invalid_graph"
REFUSAL_NOT_SOLE_INPUT = "not_sole_input"
REFUSAL_MISSING_SELECTION = "missing_selection"
REFUSAL_NO_SAVE_NODES = "no_save_nodes"


@dataclass(frozen=True)
class CalculateAndSavePlan:
    """The planned outcome of a Ribbon Calculate & Save request."""
    workflow: Optional[Workflow] = None
    selection: Optional[MeasurementSelection] = None
    label: str = ""
    runnable: bool = True
    refusal_reason: Optional[str] = None

    @property
    def is_refused(self) -> bool:
        return not self.runnable


@dataclass(frozen=True)
class WorkflowRunPlan:
    """The planned outcome of a Workflow tab Run request."""
    selection: Optional[MeasurementSelection] = None
    runnable: bool = True
    refusal_reason: Optional[str] = None
    message: str = ""

    @property
    def is_refused(self) -> bool:
        return not self.runnable


def resolve_calculate_and_save_refusal(
    loaded_runs: Sequence[Any],
    all_channels: bool,
    picked_identities: Iterable[Tuple[str, Optional[str]]],
) -> Optional[str]:
    """
    The refusals of a "Calculate & Save Data" run that need no source
    lookup, so the GUI can give them before registering any folder.
    """
    if not loaded_runs:
        return REFUSAL_NO_LOADED_FOLDER
    if not all_channels and not set(picked_identities):
        return REFUSAL_NO_CHANNELS_CHOSEN
    return None


def plan_calculate_and_save(
    block_type: str,
    config: Any,
    *,
    loaded_runs: Sequence[Any] = (),
    channel_types: Optional[Iterable[str]] = None,
    all_channels: bool = True,
    picked_identities: Iterable[Tuple[str, Optional[str]]] = (),
    sources_by_path: Optional[Mapping[str, Any]] = None,
    custom_label: str = "",
) -> CalculateAndSavePlan:
    """
    Plan a fast-path ribbon batch run ("Calculate & Save Data") as pure data.

    Decides whether the run can proceed given the loaded files and channel scope.
    If valid, constructs:
    - SaveSpec with channel scope and custom label
    - Workflow from config with the SaveSpec on the terminal node
    - MeasurementSelection in MODE_EXPLICIT over the pool sources
    - The label for the result set

    Returns a CalculateAndSavePlan with runnable=True and the built objects,
    or runnable=False with refusal_reason ("no_loaded_folder", "no_matching_channels",
    or "no_channels_chosen").
    """
    runs = list(loaded_runs)
    picked_identities = set(picked_identities)
    refusal = resolve_calculate_and_save_refusal(runs, all_channels, picked_identities)
    if refusal is not None:
        return CalculateAndSavePlan(runnable=False, refusal_reason=refusal)

    sources_map = sources_by_path or {}
    available = channel_identities_by_type(
        runs, set(channel_types) if channel_types is not None else None, sources_map,
    )
    if not available:
        return CalculateAndSavePlan(
            runnable=False,
            refusal_reason=REFUSAL_NO_MATCHING_CHANNELS,
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
        refusal_reason=None,
    )


def plan_workflow_run(
    workflow: Workflow,
    find_selection: Callable[[str], Optional[MeasurementSelection]],
) -> WorkflowRunPlan:
    """
    Plan a Workflow-tab Run as pure data.

    Validates graph connectivity and ports, ensures exactly one input node,
    resolves the input node's selection (Whole Data Pool or named selection),
    and verifies at least one node has a SaveSpec.

    Returns a WorkflowRunPlan with runnable=True and resolved selection, or
    runnable=False with refusal_reason ("invalid_graph", "not_sole_input",
    "missing_selection", or "no_save_nodes") and message.
    """
    try:
        validate_graph(workflow)
    except ValueError as exc:
        return WorkflowRunPlan(
            runnable=False,
            refusal_reason=REFUSAL_INVALID_GRAPH,
            message=str(exc),
        )

    try:
        input_id = sole_input_node_id(workflow)
    except ValueError as exc:
        return WorkflowRunPlan(
            runnable=False,
            refusal_reason=REFUSAL_NOT_SOLE_INPUT,
            message=str(exc),
        )

    input_node = workflow.node(input_id)
    input_spec = input_node.input
    if input_spec is not None and input_spec.whole_pool:
        selection = whole_pool_selection()
    else:
        selection_name = input_spec.selection_name if input_spec else ""
        selection = find_selection(selection_name) if selection_name else None

    if selection is None:
        return WorkflowRunPlan(
            runnable=False,
            refusal_reason=REFUSAL_MISSING_SELECTION,
            message=(
                "Pick what the input node runs over first "
                "('Whole Data Pool', or a saved selection)."
            ),
        )

    if not save_node_ids(workflow):
        return WorkflowRunPlan(
            runnable=False,
            refusal_reason=REFUSAL_NO_SAVE_NODES,
            message="Tick 'Save this node's output' on at least one block first.",
        )

    return WorkflowRunPlan(
        selection=selection,
        runnable=True,
        refusal_reason=None,
        message="",
    )
