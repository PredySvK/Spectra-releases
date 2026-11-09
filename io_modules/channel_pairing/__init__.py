"""
The `channel_pairing.xlsx` file: the one truth about channel pairs (#511).

`read_channel_pairing` returns the valid pairs in row order plus a warning per
skipped row; `write_channel_pairing` replaces the file atomically, so a file
locked by Excel fails with `PermissionError` and stays as it was.

The project's workbook sits in its Project folder (`resolve_channel_pairing_path`):
`read_project_channel_pairing` loads it, creating an empty workbook when the
file is missing, and `write_project_channel_pairing` stores an edited table.
Save As takes the workbook along with the rest of the Project folder
(orchestration/project_folder).

What does not belong here: the rules of a valid pair (selection/channel_pairing),
the file name (io_modules.project_store), the dialog (gui/), or the pairs held
in memory (session/).
"""

from ._channel_pairing import (
    read_channel_pairing,
    read_project_channel_pairing,
    resolve_channel_pairing_path,
    write_channel_pairing,
    write_project_channel_pairing,
)

__all__ = [
    "read_channel_pairing",
    "read_project_channel_pairing",
    "resolve_channel_pairing_path",
    "write_channel_pairing",
    "write_project_channel_pairing",
]
