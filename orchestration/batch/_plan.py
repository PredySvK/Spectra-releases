# =====================================================================
# FILE: orchestration/batch/_plan.py
# =====================================================================
"""
Planning ribbon Calculate & Save and Workflow-tab Run as data.

Pure functions (no Qt, no AppContext) coordinating:
- `plan_calculate_and_save`: whether a fast-path ribbon batch run can happen
  -- over the Data Pool (checks loaded runs and its sensor types) or over each
  checked saved Selection -- and if so, constructs the workflow, selection,
  and label of every result set it makes.
- `plan_workflow_run`: whether a workflow can run (validates the graph, sole input
  block, input selection resolution, save blocks), and if so, resolves the input
  selection.

Both say "no" the way `BatchPlan` does:
`runnable=False` with `messages` that are the log lines saying why.
"""
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple, Union

from core.channel_types import MAIN_INPUT_CHANNEL_TYPES
from core.measurement_selection import MODE_EXPLICIT, MeasurementSelection
from core.tacho_cleaning import TachoCleaning
from core.workflow_graph import SaveSpec, Workflow
from selection.measurement_selection import (
    SelectionResolution,
    resolve as resolve_selection,
    whole_pool_selection,
)
from selection.source_facets import pool_source_entries
from signal_processing.workflow import build_workflow_with_tacho_cleaning, workflow_from_configs
from signal_processing.workflow_readiness import resolve_chain_readiness

from orchestration.batch._in_pool_sources import resolve_in_pool_sources
from orchestration.batch._label import (
    data_pool_channel_component,
    default_result_set_label,
    selection_result_set_label,
)

CALCULATE_AND_SAVE_WHAT = "Calculate & Save Data"


def _skipped(what: str, why: str) -> Tuple[str, ...]:
    return (f"WARNING: {what} skipped -- {why}",)


@dataclass(frozen=True)
class DataPoolInput:
    """
    The whole Data Pool as a run's input, narrowed to these sensor types. The
    Filter mask is ignored. Only `MAIN_INPUT_CHANNEL_TYPES` are honoured, so a
    request can never name the tacho as main input.
    """
    channel_types: frozenset = MAIN_INPUT_CHANNEL_TYPES


@dataclass(frozen=True)
class SelectionsInput:
    """
    Saved Selections as a run's input, by name: each one is its own result set
    (§1.219). Their channels are narrowed to
    `MAIN_INPUT_CHANNEL_TYPES`, so a rule that lets the tacho through still
    never makes it a main input.
    """
    names: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DataPoolScope:
    """What a `DataPoolInput` covers in the loaded Data Pool."""
    channel_types: frozenset = frozenset()
    measurement_count: int = 0
    channel_count: int = 0


@dataclass(frozen=True)
class SelectionScope:
    """
    What one saved Selection covers in the loaded Data Pool, tacho left out.
    `channel_types` is what the count was narrowed to and what the planned save
    block keeps, so the dialog and the plan read one set of types.
    """
    name: str
    measurement_count: int = 0
    channel_count: int = 0
    channel_types: frozenset = MAIN_INPUT_CHANNEL_TYPES


@dataclass(frozen=True)
class CalculateAndSaveRequest:
    """
    What the user asked a ribbon Calculate & Save run for -- the Compute Result
    Set dialog's answer, handed to the batch as a value (#770).

    It used to travel through QSettings: the dialog wrote it, the ribbon read
    it back, and the only contract was a key name three files had to spell the
    same way. `input` is where the run reads from: the Data Pool or saved
    Selections, never both. `orders` is Order Tracking only; the handler swaps
    it into that tab's config.
    """
    input: Union[DataPoolInput, SelectionsInput] = DataPoolInput()
    orders: Tuple[float, ...] = ()
    custom_label: str = ""


@dataclass(frozen=True)
class CalculateAndSavePlan:
    """The planned outcome of one result set of a Ribbon Calculate & Save request."""
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


def resolve_calculate_and_save_refusal(loaded_runs: Sequence[Any]) -> Tuple[str, ...]:
    """
    The log lines refusing a "Calculate & Save Data" run for what needs no
    source lookup, so the GUI can give them before registering any folder;
    empty when nothing refuses it yet.
    """
    if not loaded_runs:
        return _skipped(CALCULATE_AND_SAVE_WHAT, "no folder is loaded.")
    return ()


def _resolve_in_pool(selection: MeasurementSelection, loaded_runs: Sequence[Any],
                     sources_by_path: Optional[Mapping[str, Any]],
                     schema: Optional[Mapping[str, Any]],
                     channel_types: frozenset) -> SelectionResolution:
    """`selection` resolved over the pool's in-pool sources, time responses only --
    the rule `plan_batch` applies, so a scope counts what the run will compute."""
    return resolve_selection(
        selection, resolve_in_pool_sources(pool_source_entries(loaded_runs, sources_by_path or {})),
        dict(schema or {}), channel_types=channel_types, time_responses_only=True,
    )


def resolve_data_pool_scope(
    data_pool: DataPoolInput,
    loaded_runs: Sequence[Any],
    sources_by_path: Optional[Mapping[str, Any]] = None,
) -> DataPoolScope:
    """
    How many measurements and channels `data_pool` covers in `loaded_runs`.
    An in-memory count over the pool index, no file is read -- the one count
    both the dialog and the run use, so the numbers cannot differ.
    """
    channel_types = frozenset(data_pool.channel_types) & MAIN_INPUT_CHANNEL_TYPES
    resolution = _resolve_in_pool(whole_pool_selection(), loaded_runs, sources_by_path, {}, channel_types)
    return DataPoolScope(channel_types, resolution.measurement_count, resolution.channel_count)


def resolve_selection_scope(
    selection: MeasurementSelection,
    loaded_runs: Sequence[Any],
    sources_by_path: Optional[Mapping[str, Any]] = None,
    schema: Optional[Mapping[str, Any]] = None,
) -> SelectionScope:
    """
    How many measurements and channels a saved Selection covers in the loaded
    Data Pool once narrowed to accelerometer + microphone. Evaluated the way
    a Workflow Run evaluates it (`resolve`), in memory over the pool index --
    the one count both the dialog and the run use.
    """
    resolution = _resolve_in_pool(selection, loaded_runs, sources_by_path, schema,
                                  MAIN_INPUT_CHANNEL_TYPES)
    return SelectionScope(selection.name, resolution.measurement_count, resolution.channel_count,
                          MAIN_INPUT_CHANNEL_TYPES)


def _plan_result_set(block_type: str, config: Any, selection: MeasurementSelection, *,
                     channel_types: frozenset, label: str, custom_label: str,
                     tacho_cleaning: TachoCleaning) -> CalculateAndSavePlan:
    """
    One runnable result set: the workflow with a typed SaveSpec on its terminal
    block (never empty, never the tacho), run over `selection`.

    `tacho_cleaning` is the applied Settings, stamped into the workflow the
    way `plan_workflow_chains` stamps it: the ribbon config does
    not hold it.
    """
    save = SaveSpec(
        all_channels=True,
        channel_types=tuple(sorted(channel_types)),
        label=custom_label,
    )
    workflow = build_workflow_with_tacho_cleaning(workflow_from_configs(
        block_type,
        [(block_type, config)],
        selection_name=selection.name,
        save=save,
    ), tacho_cleaning)
    return CalculateAndSavePlan(
        workflow=workflow, selection=selection, label=custom_label or label, runnable=True,
    )


def _refused(messages: Tuple[str, ...]) -> Tuple[CalculateAndSavePlan, ...]:
    return (CalculateAndSavePlan(runnable=False, messages=messages),)


def _plan_data_pool(block_type: str, config: Any, data_pool: DataPoolInput, custom_label: str, *,
                    tacho_cleaning: TachoCleaning, runs: Sequence[Any],
                    sources_map: Mapping[str, Any]) -> Tuple[CalculateAndSavePlan, ...]:
    scope = resolve_data_pool_scope(data_pool, runs, sources_map)
    if not scope.channel_types:
        return _refused(_skipped(CALCULATE_AND_SAVE_WHAT, "no sensor type chosen."))
    if not scope.channel_count:
        return _refused(_skipped(CALCULATE_AND_SAVE_WHAT, "no matching channels in the loaded folder."))

    selection = MeasurementSelection(
        name="",
        mode=MODE_EXPLICIT,
        source_ids=tuple(entry.id for entry in pool_source_entries(runs, sources_map)),
    )
    selection = replace(selection, name=default_result_set_label(
        workflow_from_configs(block_type, [(block_type, config)]), selection,
        channel_component=data_pool_channel_component(scope.channel_types),
    ))
    return (_plan_result_set(
        block_type, config, selection, channel_types=scope.channel_types,
        label=selection.name, custom_label=custom_label, tacho_cleaning=tacho_cleaning,
    ),)


def _plan_selections(block_type: str, config: Any, selections: SelectionsInput, custom_label: str, *,
                     tacho_cleaning: TachoCleaning, runs: Sequence[Any],
                     sources_map: Mapping[str, Any],
                     find_selection: Callable[[str], Optional[MeasurementSelection]],
                     schema: Optional[Mapping[str, Any]]) -> Tuple[CalculateAndSavePlan, ...]:
    if not selections.names:
        return _refused(_skipped(CALCULATE_AND_SAVE_WHAT, "no Selection chosen."))
    if custom_label and len(selections.names) > 1:
        # The dialog greys the Name field out; one name for several sets
        # would only end in "_2", "_3".
        return _refused(_skipped(CALCULATE_AND_SAVE_WHAT, "a custom name needs a single Selection."))

    plans = []
    for name in selections.names:
        what = f"{CALCULATE_AND_SAVE_WHAT} for Selection '{name}'"
        selection = find_selection(name)
        if selection is None:
            plans.append(CalculateAndSavePlan(
                runnable=False, messages=_skipped(what, "no Selection of that name exists.")))
            continue
        scope = resolve_selection_scope(selection, runs, sources_map, schema)
        if not scope.channel_count:
            plans.append(CalculateAndSavePlan(runnable=False, messages=_skipped(
                what, "no accelerometer or microphone channel of the loaded folder matches it.")))
            continue
        plans.append(_plan_result_set(
            block_type, config, selection, channel_types=scope.channel_types,
            label=selection_result_set_label(
                workflow_from_configs(block_type, [(block_type, config)]), selection),
            custom_label=custom_label, tacho_cleaning=tacho_cleaning,
        ))
    return tuple(plans)


def plan_calculate_and_save(
    block_type: str,
    config: Any,
    request: CalculateAndSaveRequest = CalculateAndSaveRequest(),
    *,
    tacho_cleaning: TachoCleaning,
    loaded_runs: Sequence[Any] = (),
    sources_by_path: Optional[Mapping[str, Any]] = None,
    find_selection: Callable[[str], Optional[MeasurementSelection]] = lambda name: None,
    schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[CalculateAndSavePlan, ...]:
    """
    Plan a fast-path ribbon batch run ("Calculate & Save Data") as pure data:
    one plan for a Data Pool request, one per named Selection for a Selections
    request (in the request's order; overlapping Selections stay separate).

    Every runnable plan carries:
    - SaveSpec with the sensor types (never empty, never the tacho) and label
    - Workflow from config with the SaveSpec on the terminal block
    - MeasurementSelection: a MODE_EXPLICIT snapshot over the pool sources
      for the Data Pool (§1.215), the saved Selection as it is otherwise
    - The label for the result set

    A plan that cannot run has runnable=False and the log lines saying why; an
    empty or unknown Selection refuses only its own plan.

    `find_selection` and `schema` are what a Selection is looked up and
    evaluated by; a Data Pool request needs neither.
    """
    runs = list(loaded_runs)
    refusal = resolve_calculate_and_save_refusal(runs)
    if refusal:
        return _refused(refusal)

    sources_map = sources_by_path or {}
    custom_label = (request.custom_label or "").strip()
    if isinstance(request.input, SelectionsInput):
        return _plan_selections(
            block_type, config, request.input, custom_label, tacho_cleaning=tacho_cleaning,
            runs=runs, sources_map=sources_map, find_selection=find_selection, schema=schema)
    return _plan_data_pool(
        block_type, config, request.input, custom_label, tacho_cleaning=tacho_cleaning,
        runs=runs, sources_map=sources_map)


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
