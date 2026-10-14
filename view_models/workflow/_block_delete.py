"""Translate block deletion into a workflow document, without Qt."""
from collections.abc import Iterable

from core.workflow_graph import Workflow, without_block
from ._workflow_canvas import build_pinned_workflow


def resolve_block_delete(workflow: Workflow, block_ids: Iterable[str]) -> Workflow:
    """Remove selected blocks together with incident wires and layout entries.

    The remaining blocks keep where they were drawn, even if never moved.
    """
    doomed = set(block_ids) & set(workflow.block_ids)
    if not doomed:
        return workflow
    edited = workflow
    for block_id in doomed:
        edited = without_block(edited, block_id)
    return build_pinned_workflow(workflow, edited)
