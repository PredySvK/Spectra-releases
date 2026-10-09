"""Pure companion selection over file, channel and order identities."""

from dataclasses import dataclass
from typing import Iterable

from core.models import ChannelIdentity
from selection.channel_identity import split_channel_base_and_direction


@dataclass(frozen=True)
class CompanionCurve:
    """A channel of a project source at one known order."""

    source_id: str
    channel_label: str
    order: float | None


def resolve_companion_curves(
    plotted: Iterable[CompanionCurve], available: Iterable[CompanionCurve],
    channel_pairs: Iterable[tuple[ChannelIdentity, ChannelIdentity]],
) -> list[CompanionCurve]:
    """Return available partners once, in input order, excluding plotted curves.

    The channel pairs are undirected and hold for every file (#511). An unknown
    order cannot establish a match. Channels are compared by identity, not by
    label: the same sensor carries another reader prefix ("Set #N: ") from file
    to file (#508).
    """
    plotted = set(plotted)
    channels = {edge for left, right in channel_pairs for edge in ((left, right), (right, left))}
    result = []
    for candidate in available:
        if candidate.order is None or candidate in plotted or candidate in result:
            continue
        if any(curve.order == candidate.order
               and (split_channel_base_and_direction(curve.channel_label),
                    split_channel_base_and_direction(candidate.channel_label)) in channels
               for curve in plotted):
            result.append(candidate)
    return result
