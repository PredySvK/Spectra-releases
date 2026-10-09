# =====================================================================
# FILE: view_models/workflow/_status.py
# =====================================================================
"""
Whether a `Workflow` graph can run and why not -- the text half of
`WorkflowView._refresh_status` (issue #185). Reads only the `workflow` and
an optional `find_selection` lookup passed in, never `self.tree`/
`self.lbl_status`; the caller decides `setStyleSheet` from `WorkflowStatus`.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable, Optional, Tuple

from core.workflow_graph import Workflow
from signal_processing.workflow import save_node_ids, sole_input_node_id, validate_graph


class WorkflowStatus(Enum):
    """What `format_workflow_status` found -- the GUI maps this to a colour,
    never a string comparison on the status text itself."""

    EMPTY = "empty"
    NOT_READY = "not_ready"
    READY = "ready"


def format_workflow_status(
    workflow: Optional[Workflow],
    find_selection: Optional[Callable[[str], object]] = None,
) -> Tuple[WorkflowStatus, str]:
    """The one-line 'can this run?' status and its category.

    `find_selection` mirrors `ProjectSession.find_selection`: given a
    selection name, `None` if it no longer exists. Passed in rather than a
    session object so this stays independent of `session/`.
    """
    if workflow is None:
        return WorkflowStatus.EMPTY, ""
    try:
        validate_graph(workflow)
    except ValueError as exc:
        return WorkflowStatus.NOT_READY, f"⚠  Not ready: {exc}"
    # validate_graph only type-checks the graph. It allows several input
    # nodes ("at least one"), a stale selection name and a save spec that can
    # land on nothing -- all of which Run then rejects or writes nothing for.
    # The status line has to check the same things or "Ready to run" lies
    # (audit 02 finding 2.7).
    try:
        input_id = sole_input_node_id(workflow)
    except ValueError as exc:
        return WorkflowStatus.NOT_READY, f"⚠  Not ready: {exc}"
    input_spec = workflow.node(input_id).input
    if input_spec is None or (not input_spec.whole_pool and not input_spec.selection_name):
        return WorkflowStatus.NOT_READY, "⚠  Not ready: pick what the input node runs over."
    if (not input_spec.whole_pool and find_selection is not None
            and find_selection(input_spec.selection_name) is None):
        return WorkflowStatus.NOT_READY, (
            f"⚠  Not ready: the input selection '{input_spec.selection_name}' "
            "no longer exists."
        )
    save_ids = save_node_ids(workflow)
    if not save_ids:
        return WorkflowStatus.NOT_READY, (
            "⚠  Not ready: tick 'Save this node's output' on at least one block."
        )
    for node_id in save_ids:
        save = workflow.node(node_id).save
        if not save.all_channels and not save.channel_identities:
            return WorkflowStatus.NOT_READY, (
                f"⚠  Not ready: node '{node_id}' saves a result set but has no "
                "channels chosen."
            )
    return WorkflowStatus.READY, f"✔  Ready to run — {len(save_ids)} node(s) saved"
