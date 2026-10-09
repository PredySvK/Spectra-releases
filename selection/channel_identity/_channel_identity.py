"""
Internal implementation of channel identity parsing.
"""
import re
from typing import Any, Iterable, Mapping, Optional, Tuple

_LEADING_TAG_RE = re.compile(r"^(Set|Col)\s*#\d+(\s*\[[^\]]*\])?:\s*", re.IGNORECASE)
_TIME_FOR_RE = re.compile(r"^(Time|Signal)\s+for\s+", re.IGNORECASE)
_DIRECTION_SUFFIX_RE = re.compile(r"[:_]\s*[+-]?([XYZxyz])$")
_ORDER_OVERLAY_PREFIX_RE = re.compile(r"^(O:[^\s]+\s+)+", re.IGNORECASE)


def split_channel_base_and_direction(raw_label: str) -> Tuple[str, Optional[str]]:
    """
    Strips a reader's bookkeeping prefix ("Set #5: Time for ", "Col #2
    [ACCELEROMETER]: ") and, if the label ends in a direction marker
    (":+X", "_Y", ...), splits it off. A label with no recognisable marker
    (every ASC channel, e.g. "Channel_1") comes back with direction=None --
    that is not a parse failure, ASC just does not encode direction.
    """
    label = str(raw_label).strip()
    label = _LEADING_TAG_RE.sub("", label)
    label = _TIME_FOR_RE.sub("", label).strip()

    match = _DIRECTION_SUFFIX_RE.search(label)
    if match:
        direction = match.group(1).upper()
        base = label[:match.start()].strip()
        return base, direction

    return label, None


def format_channel_identity(identity: Tuple[str, Optional[str]]) -> str:
    """Sensor and direction apart, no brackets or sign: `ACC1:1  X` (Pairing tab, Channel facet)."""
    base, direction = identity
    return f"{base}  {direction}" if direction else base


def strip_order_overlay_prefix(label: str) -> str:
    """
    Peels the "O:1 " tag (or a stack of them, "O:2 O:1 Time for X...") off a
    channel name read back from disk. An order overlay used to stamp it onto
    the channel's shared ChannelMetadata.name; nothing writes it any more
    (#160), so only saved data can still carry one -- call this where such
    data is read, not on a name held in memory.
    """
    return _ORDER_OVERLAY_PREFIX_RE.sub("", str(label))


def strip_reader_label_prefix(label: str) -> str:
    """
    Strips the reader's bookkeeping prefix ("Set #5: ", "Col #2 [ACCELEROMETER]: ").
    """
    return _LEADING_TAG_RE.sub("", str(label).strip()).strip()


def _stripped_identity_matches(label: str, name: str, clean_target: str) -> bool:
    return (strip_reader_label_prefix(label) == clean_target
            or bool(name) and strip_reader_label_prefix(name) == clean_target)


def is_channel_name_unique(clean_target: str,
                            channel_identities: Iterable[Tuple[str, str]]) -> bool:
    """
    Whether at most one channel among `channel_identities` (label, name pairs,
    one per physical channel) shares `clean_target` as its stripped identity.

    A file can hold two channels with the same name (two "Mic" columns in one
    ASC export). When that happens, a stripped-name fallback must not fire --
    it cannot tell the columns apart, so a correction filed under one column's
    exact reader label would otherwise leak onto the other (#423). Unknown
    (no channels supplied) is treated as unique: nothing here contradicts it.
    """
    matches = sum(
        1 for label, name in channel_identities
        if _stripped_identity_matches(label, name, clean_target)
    )
    return matches <= 1


def resolve_stripped_override(channel_label: str,
                               channel_identities: Iterable[Tuple[str, str]]) -> Optional[str]:
    """
    Which channel (by its key in `channel_identities`) an override filed
    under `channel_label` belongs to, or None if it belongs to none of them.

    An exact key match always wins. Failing that, the stripped-name fallback
    (for a correction filed under the plain name while the channel is keyed
    by the reader's "Set #N: "/"Col #N: " label, or vice versa) only fires
    when exactly one channel in `channel_identities` shares that stripped
    identity -- two same-named channels must not both claim a correction
    meant for just one of them (#423).
    """
    identities = list(channel_identities)
    for key, _ in identities:
        if key == channel_label:
            return key

    clean_target = strip_reader_label_prefix(channel_label)
    if not is_channel_name_unique(clean_target, identities):
        return None

    for key, name in identities:
        if _stripped_identity_matches(key, name, clean_target):
            return key
    return None



def build_channel_key(file_path: str, channel_index: Any) -> Tuple[str, int]:
    """
    The one hashable key that tells a channel of a file from every other one.

    A file can hold two channels with the same name (two "Mic" columns in one
    ASC export), so the name is never part of it: the reader's channel index
    is the only fact every caller -- a drop descriptor, a curve's meta_ref, a
    stored block's source -- carries for both of them (#426, #428).
    """
    return str(file_path), int(channel_index)


def resolve_channel_at_index(channels: Mapping[str, Any],
                             channel_index: Any) -> Optional[Tuple[str, Any]]:
    """
    The (label, channel) pair of a run's `available_channels` at
    `channel_index`, or None if no channel sits there. Looked up by index,
    never by name, for the same reason as build_channel_key.
    """
    wanted = int(channel_index)
    return next(((label, meta) for label, meta in channels.items()
                 if meta.index == wanted), None)
