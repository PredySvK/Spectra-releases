"""Translate a palette gesture into a workflow document, without Qt."""
from core.workflow_graph import Workflow
from signal_processing.workflow import build_workflow_with_block
from ._workflow_canvas import build_pinned_workflow
from ._block_move import resolve_block_move


def resolve_block_add(
    workflow: Workflow, block_type: str, source_id: str | None = None,
    position: tuple[float, float] | None = None,
) -> tuple[Workflow, str]:
    """Add defaults, optionally auto-wire, and place a dropped block."""
    edited, block_id = build_workflow_with_block(workflow, block_type, source_id)
    edited = build_pinned_workflow(workflow, edited)
    if position is not None:
        edited = resolve_block_move(edited, block_id, position)
    return edited, block_id
