"""Translate a palette gesture into a workflow document, without Qt."""
from core.workflow_graph import Workflow
from signal_processing.workflow import build_workflow_with_block


def resolve_block_add(
    workflow: Workflow, block_type: str, source_id: str | None = None,
) -> tuple[Workflow, str]:
    """Add defaults and optionally auto-wire; placement is the edit's business."""
    return build_workflow_with_block(workflow, block_type, source_id)
