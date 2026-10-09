# =====================================================================
# FILE: orchestration/batch/_overwrite.py
# =====================================================================
"""
Finding overwrite candidates for save nodes in a workflow (ADR §1.6, §1.21).

Pure lookup over the session: for every save node in a workflow graph, checks
whether a result set with identical parameters already exists in the project.

Enforces the invariant that a single existing result set can be claimed by at
most one save node (audit S1/1.1), avoiding multiple drafts staging into the
same result set folder where subsequent commits overwrite each other.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Dict, Set, TYPE_CHECKING

from core.project_model import ResultSetRef
from core.workflow_graph import Workflow
from io_modules.result_cache.cache_layout import result_params_from_node
from signal_processing.workflow import save_node_ids, spec_for

if TYPE_CHECKING:
    from session.project import ProjectSession


def find_overwrite_candidates(session: "ProjectSession", workflow: Workflow) -> Dict[str, ResultSetRef]:
    """
    Find existing result sets matching the parameters of the save nodes in a workflow.

    Returns `{node_id: existing_result_set}`.

    `session.find_duplicate_result_set` is queried per save node. If two save
    nodes share identical parameters, both query results point to the same existing
    result set ref. Letting both claim it would direct both drafts to the same result
    set folder, where the second commit would wipe the first's shards (audit 02,
    finding S1/1.1). Therefore, a result set may be claimed at most once: the first
    save node gets the duplicate candidate, and subsequent matching nodes do not.
    """
    duplicates: Dict[str, ResultSetRef] = {}
    claimed: Set[str] = set()
    for node_id in save_node_ids(workflow):
        node = workflow.node(node_id)
        existing = session.find_duplicate_result_set(
            result_params_from_node(workflow, node_id),
            kind=spec_for(node.block_type).produces,
        )
        if existing is not None and existing.id not in claimed:
            duplicates[node_id] = existing
            claimed.add(existing.id)

    return duplicates
