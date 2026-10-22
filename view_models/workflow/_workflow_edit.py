"""Resolve one workflow edit into a new workflow document, without Qt.

The one door from a canvas or Properties gesture to the document:
refusals, the no-change check and pinning of drawn positions live here, so a
new gesture cannot forget any of them (#582).
"""
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from core.workflow_graph import INPUT_BLOCK_TYPE, InputSpec, SaveSpec, Workflow, with_block_replaced
from signal_processing.workflow import BLOCKS, resolve_block_params
from ._block_add import resolve_block_add
from ._block_delete import resolve_block_delete
from ._block_move import resolve_block_move
from ._wire import resolve_wire_connect, resolve_wire_disconnect
from ._workflow_canvas import build_pinned_workflow


@dataclass(frozen=True)
class BlockMove:
    block_id: str
    position: tuple[float, float]


@dataclass(frozen=True)
class BlockAdd:
    """`source_id` is auto-wired when compatible; `position` places a dropped block."""
    block_type: str
    source_id: str | None = None
    position: tuple[float, float] | None = None


@dataclass(frozen=True)
class BlockDelete:
    block_ids: tuple[str, ...]


@dataclass(frozen=True)
class WireConnect:
    source_id: str
    target_id: str
    port_name: str


@dataclass(frozen=True)
class WireDisconnect:
    """Every `(target_id, port_name)` loses its wire in one edit."""
    ports: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class BlockSettingsApply:
    """The Properties form's params and save spec, written together."""
    block_id: str
    params: Mapping[str, Any] = field(default_factory=dict)
    save: SaveSpec | None = None


@dataclass(frozen=True)
class InputChoice:
    block_id: str
    input: InputSpec


WorkflowEdit = (BlockMove | BlockAdd | BlockDelete | WireConnect | WireDisconnect
                | BlockSettingsApply | InputChoice)


@dataclass(frozen=True)
class WorkflowEditResult:
    """`workflow` is the very same object when nothing changed or the edit is refused.

    `refusal` is empty when accepted. After a change the caller selects
    `selected_block_id`, or keeps its own selection when `keeps_selection`.
    """
    workflow: Workflow
    refusal: str = ""
    selected_block_id: str | None = None
    keeps_selection: bool = False


def _structure_changed(before: Workflow, edited: Workflow) -> bool:
    return edited.block_ids != before.block_ids or edited.wires != before.wires


def _refused(workflow: Workflow, reason: str) -> WorkflowEditResult:
    return WorkflowEditResult(workflow, refusal=reason)


def _resolve(workflow: Workflow, edit: WorkflowEdit) -> WorkflowEditResult:
    """Apply one edit; pinning is left to `resolve_workflow_edit`."""
    if isinstance(edit, BlockMove):
        if edit.block_id not in workflow.block_ids:
            return _refused(workflow, f"Block '{edit.block_id}' is not in this workflow.")
        return WorkflowEditResult(resolve_block_move(workflow, edit.block_id, edit.position),
                                  selected_block_id=edit.block_id)
    if isinstance(edit, BlockAdd):
        if edit.block_type != INPUT_BLOCK_TYPE and edit.block_type not in BLOCKS:
            return _refused(workflow, f"Unknown block type '{edit.block_type}'.")
        edited, block_id = resolve_block_add(workflow, edit.block_type, edit.source_id)
        if edit.position is not None:
            edited = resolve_block_move(edited, block_id, edit.position)
        return WorkflowEditResult(edited, selected_block_id=block_id)
    if isinstance(edit, BlockDelete):
        return WorkflowEditResult(resolve_block_delete(workflow, edit.block_ids))
    if isinstance(edit, WireConnect):
        edited, reason = resolve_wire_connect(
            workflow, edit.source_id, edit.target_id, edit.port_name)
        if reason:
            return _refused(workflow, reason)
        return WorkflowEditResult(edited, selected_block_id=edit.target_id)
    if isinstance(edit, WireDisconnect):
        edited = workflow
        for target_id, port_name in edit.ports:
            edited = resolve_wire_disconnect(edited, target_id, port_name)
        return WorkflowEditResult(edited, keeps_selection=True)
    if isinstance(edit, BlockSettingsApply):
        if edit.block_id not in workflow.block_ids:
            return _refused(workflow, f"Block '{edit.block_id}' is not in this workflow.")
        block = workflow.block(edit.block_id)
        if block.is_input:
            return _refused(workflow, "An Input block has no block settings.")
        if block.block_type not in BLOCKS:
            return _refused(workflow, f"Unknown block type '{block.block_type}'.")
        params = resolve_block_params(block.block_type, edit.params)
        if dict(block.params) == params and block.save == edit.save:
            return WorkflowEditResult(workflow, selected_block_id=edit.block_id)
        return WorkflowEditResult(
            with_block_replaced(workflow, edit.block_id, params=params, save=edit.save),
            selected_block_id=edit.block_id)
    if isinstance(edit, InputChoice):
        if edit.block_id not in workflow.block_ids:
            return _refused(workflow, f"Block '{edit.block_id}' is not in this workflow.")
        block = workflow.block(edit.block_id)
        if not block.is_input:
            return _refused(workflow, "Only an Input block chooses a selection.")
        if block.input == edit.input:
            return WorkflowEditResult(workflow, selected_block_id=edit.block_id)
        return WorkflowEditResult(with_block_replaced(workflow, edit.block_id, input=edit.input),
                                  selected_block_id=edit.block_id)
    raise TypeError(f"Not a workflow edit: {edit!r}")


def resolve_workflow_edit(workflow: Workflow, edit: WorkflowEdit) -> WorkflowEditResult:
    """Accept `edit` as a new document, or refuse it with a short reason.

    When blocks or wires change, every surviving block stays where it was
    drawn; moves and settings leave the layout to the edit itself.
    """
    result = _resolve(workflow, edit)
    if result.workflow is workflow or not _structure_changed(workflow, result.workflow):
        return result
    return replace(result, workflow=build_pinned_workflow(workflow, result.workflow))
