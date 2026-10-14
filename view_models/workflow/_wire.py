"""Resolve manual wire gestures without requiring a runnable workflow."""
from core.workflow_graph import Workflow, with_block_replaced
from signal_processing.workflow import (
    BLOCKS, build_workflow_with_wire, build_workflow_without_wire, resolve_wire_refusal,
)
from ._workflow_canvas import build_pinned_workflow


def resolve_wire_connect(
    workflow: Workflow, source_id: str, target_id: str, port_name: str,
) -> tuple[Workflow, str]:
    """Return the edited graph, or the unchanged graph and a short refusal reason.

    Only `resolve_wire_refusal` is asked: missing required inputs and other
    run-time readiness conditions are allowed while authoring.
    """
    reason = resolve_wire_refusal(workflow, source_id, target_id, port_name)
    if reason:
        return workflow, reason
    edited = build_workflow_with_wire(workflow, source_id, target_id, port_name)
    # A port is either wired or channel-bound, never both. Palette blocks
    # start with default extra-port bindings; a manual wire supersedes that.
    target = workflow.block(target_id)
    if port_name in target.bindings:
        edited = with_block_replaced(edited, target_id,
            bindings={name: binding for name, binding in target.bindings.items()
                      if name != port_name})
    if edited.wires == workflow.wires and edited.blocks == workflow.blocks:
        return workflow, ""
    return build_pinned_workflow(workflow, edited), ""


def resolve_wire_targets(workflow: Workflow, source_id: str) -> dict[tuple[str, str], str]:
    """Every input port's refusal reason for a wire from `source_id` ("" = accepts)."""
    return {(block.block_id, port.name): resolve_wire_refusal(
                workflow, source_id, block.block_id, port.name)
            for block in workflow.blocks
            if (spec := BLOCKS.get(block.block_type)) is not None
            for port in spec.inputs}


def resolve_wire_disconnect(
    workflow: Workflow, target_id: str, port_name: str,
) -> Workflow:
    """Remove the wire feeding one input, however it names the port."""
    if target_id not in workflow.block_ids:
        return workflow
    edited = build_workflow_without_wire(workflow, target_id, port_name)
    if edited is workflow:
        return workflow
    return build_pinned_workflow(workflow, edited)
