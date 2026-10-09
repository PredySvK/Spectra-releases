"""Pure channel pairing rules over channel identities."""

from typing import Iterable, Optional

from core.models import ChannelIdentity
from selection.channel_identity import format_channel_identity
from selection.source_facets import channel_identity_sort_key


def _sorted(identities: Iterable[ChannelIdentity]) -> list[ChannelIdentity]:
    return sorted(set(identities), key=channel_identity_sort_key)


def resolve_channel_offer(
    measured: Iterable[ChannelIdentity], simulated: Iterable[ChannelIdentity],
    pairs: Iterable[tuple[ChannelIdentity, ChannelIdentity]], remaining_only: bool,
) -> tuple[list[ChannelIdentity], list[ChannelIdentity]]:
    """What the Measured and Simulated lists offer, alphabetically.

    Remaining only splits the sides and drops paired channels; otherwise both
    lists carry every channel of every file, paired ones included.
    """
    measured, simulated = set(measured), set(simulated)
    if not remaining_only:
        everything = _sorted(measured | simulated)
        return everything, list(everything)
    paired = {identity for pair in pairs for identity in pair}
    return _sorted(measured - paired), _sorted(simulated - paired)


def filter_channel_identities(
    identities: Iterable[ChannelIdentity], text: str,
) -> list[ChannelIdentity]:
    """Identities whose displayed text contains `text`, ignoring case."""
    needle = (text or "").casefold()
    return [identity for identity in identities
            if needle in format_channel_identity(identity).casefold()]


def resolve_channel_pair_rejection(
    pair: tuple[ChannelIdentity, ChannelIdentity],
    pairs: Iterable[tuple[ChannelIdentity, ChannelIdentity]],
) -> Optional[str]:
    """Why `pair` cannot join `pairs`, or None when it can."""
    left, right = pair
    if left == right:
        return f"{format_channel_identity(left)} is on both sides"
    used = {identity for existing in pairs for identity in existing}
    for identity in pair:
        if identity in used:
            return f"{format_channel_identity(identity)} already paired (1:1)"
    return None
