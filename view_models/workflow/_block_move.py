"""Resolve a block move into a new workflow document, without Qt."""
from dataclasses import replace

from core.workflow_graph import Workflow


def resolve_block_move(
    workflow: Workflow, block_id: str, position: tuple[float, float],
) -> Workflow:
    """Change layout only; unknown blocks are refused by the document model."""
    if workflow.layout.get(block_id) == position:
        return workflow
    return replace(workflow, layout={**workflow.layout, block_id: position})
