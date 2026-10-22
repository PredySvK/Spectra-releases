"""
The `channel_pairing.xlsx` file: the one truth about channel pairs (#511).

`read_channel_pairing` returns the valid pairs in row order plus a warning per
skipped row; `write_channel_pairing` replaces the file atomically, so a file
locked by Excel fails with `PermissionError` and stays as it was.

What does not belong here: the rules of a valid pair (selection/channel_pairing)
or where the file lives (its name: io_modules.project_store; its path:
orchestration/channel_pairing).
"""

from ._channel_pairing import read_channel_pairing, write_channel_pairing

__all__ = ["read_channel_pairing", "write_channel_pairing"]
