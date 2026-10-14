# =====================================================================
# FILE: orchestration/batch/_overwrite.py
# =====================================================================
"""
Finding overwrite candidates for save blocks in a workflow.

Pure lookup over the session: for every save block in a workflow graph, checks
whether a result set with identical parameters already exists in the project.

Enforces the invariant that a single existing result set can be claimed by at
most one save block (audit S1/1.1), avoiding multiple drafts staging into the
same result set folder where subsequent commits overwrite each other.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Dict, Set, TYPE_CHECKING

from core.project_model import ResultSetRef
from core.workflow_graph import Workflow
from io_modules.result_cache.cache_layout import result_params_from_block
from signal_processing.workflow import save_block_ids, spec_for

if TYPE_CHECKING:
    from session.project import ProjectSession


def find_overwrite_candidates(session: "ProjectSession", workflow: Workflow | tuple[Workflow, ...]) -> Dict[str, ResultSetRef]:
    """
    Find existing result sets matching the parameters of the save blocks in a workflow.

    Returns `{block_id: existing_result_set}`.

    `session.find_duplicate_result_set` is queried per save block. If two save
    blocks share identical parameters, both query results point to the same existing
    result set ref. Letting both claim it would direct both drafts to the same result
    set folder, where the second commit would wipe the first's shards (audit 02,
    finding S1/1.1). Therefore, a result set may be claimed at most once: the first
    save block gets the duplicate candidate, and subsequent matching blocks do not.
    """
    duplicates: Dict[str, ResultSetRef] = {}
    claimed: Set[str] = set()
    workflows = (workflow,) if isinstance(workflow, Workflow) else workflow
    for chain, block_id in ((chain, block_id) for chain in workflows for block_id in save_block_ids(chain)):
        workflow_block = chain.block(block_id)
        existing = session.find_duplicate_result_set(
            result_params_from_block(chain, block_id),
            kind=spec_for(workflow_block.block_type).produces,
        )
        if existing is not None and existing.id not in claimed:
            duplicates[block_id] = existing
            claimed.add(existing.id)

    return duplicates
