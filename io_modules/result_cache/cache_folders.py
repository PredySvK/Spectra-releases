# =====================================================================
# FILE: io_modules/result_cache/cache_folders.py
# =====================================================================
"""
Filesystem side of a result-set commit: create, swap and retire the folder
that backs a `ResultSetRef`.

Split out of `io_modules/project_result_sets.py` (#172): that mixin mixed
disk operations into the same method bodies as the project-state bookkeeping
(`begin_result_set`, `_commit_overwrite`, `_label_is_taken`). The state half
moved to `session/result_sets.py`; this module is the disk half, so it stays
in `io_modules` regardless of which layer calls it.
"""

import os
import shutil
import time

# An overwrite writes its shards next to the set it replaces and swaps the two
# folders at the very end, so the existing result set survives intact until the
# replacement is complete. The retired folder keeps the previous content
# reachable until the swap that follows it has actually succeeded.
_RETIRED_SUFFIX = ".retired"


def remove_tree(path: str) -> None:
    """
    Deletes a result-set folder, best-effort.

    Never raises: on Windows a shard a background lookup still has open cannot
    be deleted, and a leftover folder is inert -- nothing reads a result-set
    folder without a manifest, and the project does not name it.
    """
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def rename_with_retry(source: str, destination: str,
                      attempts: int = 5, delay_s: float = 0.08) -> None:
    """
    Swaps a freshly written result cache in, retrying while a reader holds it.

    Overwriting a result set is not the only thing that touches its files: a
    cache lookup for a dropped channel or a bulk overlay opens the same
    shard on a background worker (io_modules.result_cache.cache_lookup). On
    Windows a rename over something another handle has open fails outright,
    so a lookup that happens to overlap would throw away a batch that took
    minutes to compute. The readers hold a file only for the length of one
    read, so waiting a moment is enough; after the last attempt the error is
    raised and handled by the caller.
    """
    for remaining in range(attempts - 1, -1, -1):
        try:
            os.replace(source, destination)
            return
        except (PermissionError, OSError):
            if remaining == 0:
                raise
            time.sleep(delay_s)


def make_result_set_folder(folder: str) -> None:
    """Creates the folder a result-set draft writes its shards into."""
    os.makedirs(folder, exist_ok=True)


def label_folder_exists(base: str) -> bool:
    """
    Whether a result-set folder already exists on disk at `base`, as either a
    format-2 directory or a format-1 single `.h5` file.
    """
    return os.path.exists(base) or os.path.exists(f"{base}.h5")


def swap_in_overwrite(final_folder: str, draft_folder: str) -> None:
    """
    Swaps a staged draft folder over the result set it replaces.

    The set being overwritten is retired (renamed aside) rather than deleted
    up front, so a failure partway through the swap leaves it recoverable
    instead of gone. `final_folder` may be a format-2 directory or, for a
    format-1 single file, `final_folder + ".h5"` -- either is retired the
    same way, so the swap stays reversible until the very last step and no
    reader loses its file mid-read.
    """
    retired = final_folder + _RETIRED_SUFFIX
    remove_tree(retired)
    if os.path.exists(final_folder):
        rename_with_retry(final_folder, retired)
    elif os.path.exists(final_folder + ".h5"):
        rename_with_retry(final_folder + ".h5", retired + ".h5")
    rename_with_retry(draft_folder, final_folder)


def restore_retired(final_folder: str, draft_folder: str) -> None:
    """
    Undoes `swap_in_overwrite` after the commit that followed it failed.

    Moves the swapped-in draft back to `draft_folder` (for the caller to
    discard) and renames the retired set back to `final_folder`, so the
    project -- which the failed commit left pointing at the old result set --
    names the old data again. Also covers a swap that failed partway: the
    retired set is put back only when nothing occupies `final_folder`, so an
    unrelated leftover `.retired` never replaces a set that was never moved.

    Never raises: it runs while the caller is already handling a failure, and
    a rename that still fails leaves the retired set on disk, not gone.
    """
    retired = final_folder + _RETIRED_SUFFIX
    try:
        if not os.path.exists(draft_folder) and os.path.isdir(final_folder):
            rename_with_retry(final_folder, draft_folder)
        if os.path.exists(final_folder) or os.path.exists(final_folder + ".h5"):
            return
        if os.path.exists(retired):
            rename_with_retry(retired, final_folder)
        elif os.path.exists(retired + ".h5"):
            rename_with_retry(retired + ".h5", final_folder + ".h5")
    except OSError:
        pass


def discard_retired(final_folder: str) -> None:
    """Removes the folder `swap_in_overwrite` retired, once the commit that replaced it has succeeded."""
    retired = final_folder + _RETIRED_SUFFIX
    remove_tree(retired)
    if os.path.exists(retired + ".h5"):
        try:
            os.remove(retired + ".h5")
        except OSError:
            pass
