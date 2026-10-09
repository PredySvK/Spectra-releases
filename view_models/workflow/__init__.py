"""
view_models.workflow -- Workflow graph presentation text, without Qt.

Architecture:
- View-model floor (Floor 3): what should the Workflow panel's tree labels
  and status line say, given a `core.workflow_graph.Workflow` and node/spec
  arguments -- never `self.tree`/`self.lbl_status` (issue #185).
- Status: format_workflow_status, WorkflowStatus -- the "can this run?" line
  and its category; the caller (`gui/workspace/workflow_view.py`) maps the
  category to a stylesheet.
- Node text: format_input_summary, format_node_summary -- the input-node
  selection blurb and the block-node produces/bindings/save/lineage summary.

What does NOT belong here: Qt widgets, `setText`/`setStyleSheet` calls
(gui/), deciding what runs (orchestration/), what project is currently open
(session/), which curves are relevant (selection/).
"""

from ._status import WorkflowStatus, format_workflow_status
from ._summaries import format_input_summary, format_node_summary

__all__ = [
    "WorkflowStatus",
    "format_workflow_status",
    "format_input_summary",
    "format_node_summary",
]
