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
  block, input selection resolution, save blocks), and if so, resolves the input
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
from signal_processing.workflow import workflow_from_configs
from signal_processing.workflow_readiness import (
    ISSUE_INPUT_NOT_CHOSEN,
    ISSUE_INVALID_GRAPH,
    ISSUE_MULTIPLE_INPUTS,
    ISSUE_NO_SAVE_BLOCKS,
    ISSUE_NO_SAVE_CHANNELS,
    ISSUE_SELECTION_MISSING,
    resolve_chain_readiness,
)

from orchestration.batch._label import default_result_set_label

# Refusal reasons for plan_calculate_and_save
REFUSAL_NO_LOADED_FOLDER = "no_loaded_folder"
REFUSAL_NO_MATCHING_CHANNELS = "no_matching_channels"
REFUSAL_NO_CHANNELS_CHOSEN = "no_channels_chosen"

# Refusal reasons for plan_workflow_run
REFUSAL_INVALID_GRAPH = "invalid_graph"
REFUSAL_MULTIPLE_INPUTS = "multiple_inputs_not_supported"
REFUSAL_MISSING_SELECTION = "missing_selection"
REFUSAL_NO_SAVE_BLOCKS = "no_save_blocks"
REFUSAL_NO_SAVE_CHANNELS = "no_save_channels"

_REFUSAL_BY_ISSUE = {
    ISSUE_MULTIPLE_INPUTS: REFUSAL_MULTIPLE_INPUTS,
    ISSUE_INVALID_GRAPH: REFUSAL_INVALID_GRAPH,
    ISSUE_INPUT_NOT_CHOSEN: REFUSAL_MISSING_SELECTION,
    ISSUE_SELECTION_MISSING: REFUSAL_MISSING_SELECTION,
    ISSUE_NO_SAVE_BLOCKS: REFUSAL_NO_SAVE_BLOCKS,
    ISSUE_NO_SAVE_CHANNELS: REFUSAL_NO_SAVE_CHANNELS,
}


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
    - Workflow from config with the SaveSpec on the terminal block
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

    The chain's readiness (`resolve_chain_readiness`) decides: its first issue
    is the refusal. A ready chain gets its input selection resolved (Whole Data
    Pool or a named selection).

    Returns a WorkflowRunPlan with runnable=True and resolved selection, or
    runnable=False with refusal_reason ("invalid_graph",
    "multiple_inputs_not_supported", "missing_selection", "no_save_blocks" or
    "no_save_channels") and message.
    """
    issues = resolve_chain_readiness(workflow, find_selection)
    if issues:
        return WorkflowRunPlan(
            runnable=False, refusal_reason=_REFUSAL_BY_ISSUE[issues[0].code],
            message=issues[0].text,
        )

    input_spec = next(block for block in workflow.blocks if block.is_input).input
    selection = (whole_pool_selection() if input_spec.whole_pool
                 else find_selection(input_spec.selection_name))

    return WorkflowRunPlan(
        selection=selection,
        runnable=True,
        refusal_reason=None,
        message="",
    )
