"""Project-level access to channel_pairing.xlsx."""

import os

from io_modules.channel_pairing import read_channel_pairing, write_channel_pairing
from io_modules.project_store import PAIRING_FILE_NAME, project_folder


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

