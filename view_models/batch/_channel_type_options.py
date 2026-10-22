"""The batch channel-type labels -- see the component facade."""

from typing import AbstractSet, FrozenSet, Mapping, Optional

SAVE_CHANNEL_TYPE_OPTIONS: Mapping[str, FrozenSet[str]] = {
    "Acceleration": frozenset({"accelerometer"}),
    "Sound": frozenset({"microphone"}),
    "Acceleration + Sound": frozenset({"accelerometer", "microphone"}),
}


def resolve_channel_types(label: str) -> Optional[FrozenSet[str]]:
    """The sensor types `label` filters to; None for a label not offered."""
    return SAVE_CHANNEL_TYPE_OPTIONS.get(label)


def resolve_channel_type_label(channel_types: AbstractSet[str]) -> Optional[str]:
    """The label whose sensor types are exactly `channel_types`; None if none is."""
    wanted = frozenset(channel_types)
    for label, types in SAVE_CHANNEL_TYPE_OPTIONS.items():
        if types == wanted:
            return label
    return None
