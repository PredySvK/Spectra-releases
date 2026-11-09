# =====================================================================
# FILE: orchestration/batch/_in_pool_sources.py
# =====================================================================
"""
Which measurements a batch run may read at all -- the one list both the
Compute Result Set dialog's counts and `plan_batch` start from, so the number
shown before a run and the number the plan logs cannot differ.
"""
from typing import List, Sequence

from core.project_model import SourceEntry


def resolve_in_pool_sources(sources: Sequence[SourceEntry]) -> List[SourceEntry]:
    """The `SourceEntry`s of `sources` that are in the Data Pool (a folder outside it is not)."""
    return [entry for entry in sources if entry.in_pool]
