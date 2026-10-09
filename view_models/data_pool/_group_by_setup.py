# =====================================================================
# FILE: view_models/data_pool/_group_by_setup.py
# =====================================================================
"""
Setup grouping for the Data Pool tree, without Qt (issue #186).

Buckets the pool's loaded runs under their test setup, preserving the order
setups were invented in, dropping setups with no active runs, and placing
unassigned runs in their own bucket at the end.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional

from io_modules.measurement_files import canonical_path

class _UnassignedSetup(str):
    """
    Sentinel for measurements that have not been filed under a test setup.

    Subclasses str so that it formats as 'Unassigned' in labels, logs, and
    tree headings, and satisfies 'UNASSIGNED_SETUP in heading.text(0)', but
    uses identity equality so that a user-defined setup named 'Unassigned'
    does not collide with the unassigned bucket in dictionaries (issue #368).
    """

    def __eq__(self, other: object) -> bool:
        return self is other

    def __ne__(self, other: object) -> bool:
        return self is not other

    def __hash__(self) -> int:
        return id(self)

    def __repr__(self) -> str:
        return "UNASSIGNED_SETUP"


# Shown for measurements the user has not filed under a setup of their own.
# A real node rather than a flat list at the top, so the tree has one shape
# whether or not setups are being used.
UNASSIGNED_SETUP = _UnassignedSetup("Unassigned")


def group_by_setup(
    labels_in_order: Iterable[str],
    loaded_runs: Iterable[Any],
    by_path: Optional[Mapping[str, Any]] = None,
) -> Dict[str, List[Any]]:
    """
    Buckets the pool's runs under their test setup, setups first in the
    order they were invented and the unassigned bucket last.

    Empty setups (a setup every one of whose files has since left the pool)
    are pruned so they do not show as empty headings.
    """
    by_path = by_path or {}
    grouped: Dict[str, List[Any]] = {
        label: [] for label in labels_in_order if label is not UNASSIGNED_SETUP
    }
    unassigned: List[Any] = []

    for run_index in loaded_runs:
        file_path = getattr(run_index, "file_path", "")
        entry = by_path.get(canonical_path(file_path)) if file_path else None
        setup_label = getattr(entry, "setup_label", None) if entry is not None else None
        if setup_label and setup_label is not UNASSIGNED_SETUP:
            grouped.setdefault(setup_label, []).append(run_index)
        else:
            unassigned.append(run_index)

    # A setup every one of whose files has since left the pool would
    # otherwise show as an empty heading.
    result: Dict[str, List[Any]] = {
        label: runs for label, runs in grouped.items() if runs
    }
    if unassigned:
        result[UNASSIGNED_SETUP] = unassigned
    return result
