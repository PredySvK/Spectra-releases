"""
Channel pairing for the selection floor: which measured channel is compared with
which simulated one (#511).

Pure logic over `ChannelIdentity` values: what each side of the Pairing tab
offers, how a search narrows it, and whether a pair may join a table of pairs
(1:1, no channel against itself).

What does not belong here: the `channel_pairing.xlsx` file (io_modules/), the
dialog (gui/), or the project's in-memory pairs (session/).
"""

from ._channel_pairing import (
    filter_channel_identities,
    resolve_channel_offer,
    resolve_channel_pair_rejection,
)

__all__ = [
    "filter_channel_identities",
    "resolve_channel_offer",
    "resolve_channel_pair_rejection",
]
