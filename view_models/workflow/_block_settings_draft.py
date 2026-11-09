"""Block settings typed into Properties and not applied yet, and when they survive."""
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from core.workflow_graph import SaveSpec, Workflow
from signal_processing.workflow import BLOCKS


@dataclass(frozen=True)
class BlockSettingsDraft:
    """Everything above Apply for one block: the form's entries (as
    `resolve_block_form_params` takes them) and the Save settings."""
    block_id: str
    entries: Mapping[str, Any]
    save: Optional[SaveSpec]


def resolve_block_settings_draft(draft: Optional[BlockSettingsDraft], workflow: Optional[Workflow],
                                 block_id: Optional[str]) -> Optional[BlockSettingsDraft]:
    """
    `draft` when the Properties panel is about to show its block again after the
    canvas was redrawn, otherwise None.

    A draft belongs to the block it was typed on: it survives a redraw that keeps
    that block on screen -- a move, an added or deleted other block, a wire --
    and ends when another block is shown or the block is gone. Undo, Redo and
    Apply end it too; the caller does not pass one then.
    """
    if draft is None or workflow is None or block_id != draft.block_id:
        return None
    if block_id not in workflow.block_ids:
        return None
    block = workflow.block(block_id)
    if block.is_input or block.block_type not in BLOCKS:
        return None
    return draft
