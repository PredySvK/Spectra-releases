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
- Properties: build_block_form, BlockForm, BlockFormField and the WIDGET_*
  kinds -- which rows a block's form shows; resolve_block_form_params reads
  the form's entries back as params (#898). build_input_options, InputOptions
  -- what the Input block's selection combo offers. BlockSettingsDraft,
  resolve_block_settings_draft -- unapplied block settings and whether they
  survive a canvas redraw.

What does NOT belong here: Qt widgets, `setText`/`setStyleSheet` calls
(gui/), deciding what runs (orchestration/), what project is currently open
(session/), which curves are relevant (selection/).
"""

from ._block_form import (
    WIDGET_CHECK, WIDGET_CHOICE, WIDGET_DECIMAL, WIDGET_INTEGER, WIDGET_TEXT,
    BlockForm, BlockFormField, build_block_form, resolve_block_form_params,
)
from ._block_settings_draft import BlockSettingsDraft, resolve_block_settings_draft
from ._input_options import InputOptions, build_input_options
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
    "BlockForm", "BlockFormField", "build_block_form", "resolve_block_form_params",
    "WIDGET_CHECK", "WIDGET_CHOICE", "WIDGET_DECIMAL", "WIDGET_INTEGER", "WIDGET_TEXT",
    "InputOptions", "build_input_options",
    "BlockSettingsDraft", "resolve_block_settings_draft",
    "CanvasBlock", "CanvasPort", "CanvasWire", "WorkflowCanvas", "build_workflow_canvas",
    "WorkflowStatus",
    "format_workflow_status",
]
