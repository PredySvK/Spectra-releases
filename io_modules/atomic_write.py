# =====================================================================
# FILE: io_modules/atomic_write.py
# =====================================================================
"""
Atomic text-file writes shared by filesystem-facing io_modules.

`project_store.save_project`, `cache_index.write` and
`cache_writer.write_set_manifest` each grew their own copy of the same
tmp + flush + fsync + os.replace dance. Three copies is three places to fix
when the sequence is wrong, and they had already drifted -- the project writer
skipped deleting its `.tmp` after a failed write, so a failed Save Project left
a `<project>.nvhproject.tmp` lying beside the real file. This is the single
copy they now all call.

Lives in `io_modules/` because it is pure filesystem I/O with no model or Qt
dependency -- the layer where, as `project_store` puts it, "everything that can
fail because of the filesystem lives".
"""
import json
import os
from typing import Any, Callable, Optional, TextIO


def write_text_atomic(path: str, write: Callable[[TextIO], None], *,
                      encoding: Optional[str] = None) -> str:
    """
    Write text through `write` and replace `path` only after it is complete.

    The sibling `.tmp` is flushed and fsynced before `os.replace`, so readers
    see either the previous file or the complete new file. A failed writer or
    replace removes the temporary file and leaves the previous file untouched.
    `encoding=None` uses the platform default, matching `open(path, "w")`.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding=encoding) as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise
    return path


def write_json_atomic(path: str, payload: Any, *, indent: int = 2) -> str:
    """
    Serialise `payload` to JSON at `path` so a reader sees either the whole old
    file or the whole new one, never a truncated middle.

    `default=str` so a stray non-serialisable value (a Path, a datetime) is
    coerced instead of raising mid-write; this matches what the cache writers
    already did and is a no-op for the plain dict/list/str/number payloads the
    project and manifests actually carry.
    """
    return write_text_atomic(
        path,
        lambda handle: json.dump(
            payload, handle, indent=indent, ensure_ascii=False, default=str
        ),
        encoding="utf-8",
    )
