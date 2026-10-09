"""
Where the project's channel pairs live and when they are read or written (#511).

The pairs are the content of `channel_pairing.xlsx` in the project folder:
`read_project_channel_pairing` loads them (creating an empty workbook when the
file is missing), `write_project_channel_pairing` stores an edited table and
`copy_project_channel_pairing` takes the workbook along on a Save As.

What does not belong here: the workbook format (io_modules/channel_pairing),
the dialog (gui/), or the pairs held in memory (session/).
"""

from ._channel_pairing import (
    copy_project_channel_pairing,
    read_project_channel_pairing,
    resolve_channel_pairing_path,
    write_project_channel_pairing,
)

__all__ = [
    "copy_project_channel_pairing",
    "read_project_channel_pairing",
    "resolve_channel_pairing_path",
    "write_project_channel_pairing",
]
