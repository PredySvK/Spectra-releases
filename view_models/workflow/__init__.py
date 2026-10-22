"""
view_models.workflow -- Workflow graph presentation text, without Qt.

Architecture:
- View-model floor (Floor 3): what should the Workflow panel's status line
  say, given a `core.workflow_graph.Workflow` -- never `self.lbl_status`
  (issue #185).
- Status: format_workflow_status, WorkflowStatus -- the "can this run?" line
  and its category; the caller (`gui/workspace/workflow_view.py`) maps the
  category to a stylesheet.
- Workflow edit: resolve_workflow_edit, WorkflowEditResult and the edit values
  (BlockMove, BlockAdd, BlockDelete, WireConnect, WireDisconnect,
  BlockSettingsApply, InputChoice) -- the one door from a canvas or Properties
  gesture to the document; `resolve_wire_targets` only previews.

What does NOT belong here: Qt widgets, `setText`/`setStyleSheet` calls
(gui/), deciding what runs (orchestration/), what project is currently open
(session/), which curves are relevant (selection/).
"""

from ._status import WorkflowStatus, format_workflow_status
from ._wire import resolve_wire_targets
from ._workflow_edit import (
    BlockAdd, BlockDelete, BlockMove, BlockSettingsApply, InputChoice,
    WireConnect, WireDisconnect, WorkflowEdit, WorkflowEditResult, resolve_workflow_edit,
)
from ._workflow_canvas import (
    CanvasBlock, CanvasPort, CanvasWire, WorkflowCanvas, build_workflow_canvas,
)

__all__ = [
    "resolve_workflow_edit", "WorkflowEdit", "WorkflowEditResult",
    "BlockAdd", "BlockDelete", "BlockMove", "BlockSettingsApply", "InputChoice",
    "WireConnect", "WireDisconnect",
    "resolve_wire_targets",
    "CanvasBlock", "CanvasPort", "CanvasWire", "WorkflowCanvas", "build_workflow_canvas",
    "WorkflowStatus",
    "format_workflow_status",
]
