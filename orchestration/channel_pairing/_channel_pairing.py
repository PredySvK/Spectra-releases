"""Project-level access to channel_pairing.xlsx."""

import os
import shutil

from io_modules.channel_pairing import (
    PAIRING_FILE_NAME, read_channel_pairing, write_channel_pairing)
from io_modules.project_store import project_folder


def resolve_channel_pairing_path(project_path: str) -> str:
    return os.path.join(project_folder(project_path), PAIRING_FILE_NAME)


def read_project_channel_pairing(project_path: str):
    """Return (pairs, warnings); a missing workbook is created empty.

    An OSError creating it (read-only folder) is not fatal: no pairs.
    """
    path = resolve_channel_pairing_path(project_path)
    if not os.path.isfile(path):
        try:
            write_channel_pairing(path, [])
        except OSError:
            pass
        return [], []
    return read_channel_pairing(path)


def write_project_channel_pairing(project_path: str, pairs) -> None:
    """Store `pairs`; raises PermissionError while Excel holds the file open."""
    write_channel_pairing(resolve_channel_pairing_path(project_path), pairs)


def copy_project_channel_pairing(old_project_path: str, new_project_path: str) -> None:
    """Take the workbook along on a Save As into another folder.

    No workbook to take, or one already in the new folder, leaves both as they are.
    """
    source = resolve_channel_pairing_path(old_project_path)
    target = resolve_channel_pairing_path(new_project_path)
    if source != target and os.path.isfile(source) and not os.path.exists(target):
        shutil.copy2(source, target)
