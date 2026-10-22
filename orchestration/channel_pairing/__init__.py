"""
Where the project's channel pairs live and when they are read or written (#511).

The pairs are the content of `channel_pairing.xlsx` in the project folder:
`read_project_channel_pairing` loads them (creating an empty workbook when the
file is missing) and `write_project_channel_pairing` stores an edited table.
Save As takes the workbook along with the rest of the Project folder
(orchestration/project_folder).

What does not belong here: the workbook format (io_modules/channel_pairing),
the dialog (gui/), or the pairs held in memory (session/).
"""

from ._channel_pairing import (
    read_project_channel_pairing,
    resolve_channel_pairing_path,
    write_project_channel_pairing,
)

__all__ = [
    "read_project_channel_pairing",
    "resolve_channel_pairing_path",
    "write_project_channel_pairing",
]
