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
from signal_processing.workflow import save_block_ids
from signal_processing.workflow_readiness import resolve_workflow_readiness


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
    statuses = [(chain.name, *_format_chain_status(chain, issues))
                for chain, issues in resolve_workflow_readiness(workflow, find_selection)]
    if len(statuses) == 1:
        return statuses[0][1:]
    ready = sum(status is WorkflowStatus.READY for _, status, _ in statuses)
    refused = [f"{name}: {text}" for name, status, text in statuses if status is not WorkflowStatus.READY]
    text = ("✔  " if ready else "⚠  ") + f"{ready}/{len(statuses)} chains ready. Run executes ready chains sequentially."
    if refused:
        text += "\n" + "\n".join(refused)
    return (WorkflowStatus.READY if ready else WorkflowStatus.NOT_READY), text


def _format_chain_status(chain: Workflow, issues) -> Tuple[WorkflowStatus, str]:
    if issues:
        return WorkflowStatus.NOT_READY, f"⚠  Not ready: {issues[0].text}"
    return WorkflowStatus.READY, f"✔  Ready to run — {len(save_block_ids(chain))} block(s) saved"
