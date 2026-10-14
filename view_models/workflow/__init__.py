"""
view_models.workflow -- Workflow graph presentation text, without Qt.

Architecture:
- View-model floor (Floor 3): what should the Workflow panel's status line
  say, given a `core.workflow_graph.Workflow` -- never `self.lbl_status`
  (issue #185).
- Status: format_workflow_status, WorkflowStatus -- the "can this run?" line
  and its category; the caller (`gui/workspace/workflow_view.py`) maps the
  category to a stylesheet.

What does NOT belong here: Qt widgets, `setText`/`setStyleSheet` calls
(gui/), deciding what runs (orchestration/), what project is currently open
(session/), which curves are relevant (selection/).
"""

from ._status import WorkflowStatus, format_workflow_status
from ._block_move import resolve_block_move
from ._block_add import resolve_block_add
from ._block_delete import resolve_block_delete
from ._wire import resolve_wire_connect, resolve_wire_targets, resolve_wire_disconnect
from ._workflow_canvas import (
    CanvasBlock, CanvasPort, CanvasWire, WorkflowCanvas, build_workflow_canvas,
)

__all__ = [
    "resolve_wire_connect", "resolve_wire_targets", "resolve_wire_disconnect",
    "resolve_block_add",
    "resolve_block_delete",
    "resolve_block_move",
    "CanvasBlock", "CanvasPort", "CanvasWire", "WorkflowCanvas", "build_workflow_canvas",
    "WorkflowStatus",
    "format_workflow_status",
]
