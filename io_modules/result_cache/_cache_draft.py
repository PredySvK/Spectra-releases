# =====================================================================
# FILE: io_modules/result_cache/_cache_draft.py
# =====================================================================
"""
The disk side of writing one result set, step by step around a
`ResultSetDraft`: create it, finish it with a manifest, swap it in over the
set it replaces, and undo or tidy up after that (#800).

ProjectSession (session/result_sets.py) drives the order, because the whole
transaction also covers the project model and the project save, which do not
belong here. What it no longer has to know is anything about folders: where
a draft is staged, which folder it replaces, and what is renamed back when
the save fails. Every function takes the draft and works out the rest from
`draft.folder` and `draft.final_folder`, so a new set and an overwrite are
driven by the same calls.
"""

import os
import uuid
from typing import Any, Dict, List, Optional

from core.project_model import utc_now
from io_modules.result_cache._cache_folders import (
    discard_retired, remove_tree, restore_retired, swap_in_overwrite,
)
from io_modules.result_cache._cache_layout import params_hash
from io_modules.result_cache._cache_naming import sanitize_result_set_label
from io_modules.result_cache._cache_writer import (
    ResultSetDraft, build_manifest, write_set_manifest,
)

# The staging folder name carries a per-draft random token: resolve_overwrites
# can point two save nodes at the same existing set (audit 02, finding
# S1/1.1), and a shared "<label>.staging" folder meant the second commit
# swapped an empty folder over the first's committed data. Every step below
# works from the draft, so the unique name stays contained. The suffix
# contains a "." -- which sanitize_result_set_label strips from every
# user-chosen label -- so no user-chosen label can ever collide with it.
_STAGING_SUFFIX = ".staging"


def create_draft(cache_dir: str, kind: str, label: str, params: Dict[str, Any],
                 overwrite: bool = False,
                 compression: Optional[str] = None) -> ResultSetDraft:
    """
    Creates the folder a result set is written into and returns its draft.

    A new set is written straight into `cache_dir/<label>`; an overwrite of
    the set named `label` goes to a staging folder beside it, so the existing
    set stays intact until `swap_in_draft`. A new label must already be clean
    (sanitize_result_set_label): ProjectSession sanitises and de-duplicates
    the typed name, and this is the backstop where the folder name is born
    (audit 02 finding 5.1). An overwrite reuses the label of a set that is
    already on disk, so it is not checked again.
    """
    if not overwrite and (not label or sanitize_result_set_label(label) != label):
        raise ValueError(f"Result set name {label!r} is not a safe folder name.")
    final_folder = os.path.join(cache_dir, label)
    if overwrite:
        folder = f"{final_folder}.{uuid.uuid4().hex[:8]}{_STAGING_SUFFIX}"
        remove_tree(folder)
    else:
        folder, final_folder = final_folder, ""
    os.makedirs(folder, exist_ok=True)
    return ResultSetDraft(
        folder=folder, kind=kind, label=label, params=dict(params),
        params_hash=params_hash(params), created_utc=utc_now(),
        compression=compression or None, final_folder=final_folder,
    )


def write_draft_manifest(draft: ResultSetDraft, entries: List[Dict[str, Any]],
                         status: str = "complete", all_channels: bool = False) -> str:
    """
    Finishes a draft: writes its `_set.json` from the shards' manifest entries.

    Until this runs the folder is inert -- every reader treats a folder
    without a manifest as unreadable -- which is what makes a cancelled batch
    harmless. Returns the manifest path.
    """
    return write_set_manifest(draft.folder,
                              build_manifest(draft, entries, status, all_channels))


def swap_in_draft(draft: ResultSetDraft) -> None:
    """
    Puts a staged overwrite in place of the set it replaces; the replaced set
    is retired (renamed aside), not deleted, until `finish_swap_in`. Does
    nothing for a new set, which was written in place.
    """
    if draft.final_folder:
        swap_in_overwrite(draft.final_folder, draft.folder)


def undo_swap_in(draft: ResultSetDraft) -> None:
    """
    Undoes `swap_in_draft` after the commit that followed it failed: the
    retired set is renamed back and the draft's data is discarded. Covers a
    swap that failed partway, and a draft that was never swapped in. Never
    raises -- it runs while the caller is already handling a failure.
    """
    if draft.final_folder:
        restore_retired(draft.final_folder, draft.folder)
    remove_tree(draft.folder)


def finish_swap_in(draft: ResultSetDraft) -> None:
    """Removes the set `swap_in_draft` retired, once the commit has succeeded."""
    if draft.final_folder:
        discard_retired(draft.final_folder)


def discard_draft(draft: ResultSetDraft) -> None:
    """
    Throws a draft's folder away -- a cancelled batch, or one that produced
    nothing. Best-effort: a shard a reader still has open cannot be deleted on
    Windows, and a leftover folder with no manifest is inert.
    """
    remove_tree(draft.folder)
