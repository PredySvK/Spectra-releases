"""The batch channel-type labels -- see the component facade."""

from typing import AbstractSet, FrozenSet, Mapping, Optional

from core.channel_types import (
    CHANNEL_TYPE_ACCELEROMETER,
    CHANNEL_TYPE_MICROPHONE,
    MAIN_INPUT_CHANNEL_TYPES,
)

SAVE_CHANNEL_TYPE_OPTIONS: Mapping[str, FrozenSet[str]] = {
    "Accelerometer": frozenset({CHANNEL_TYPE_ACCELEROMETER}),
    "Microphone": frozenset({CHANNEL_TYPE_MICROPHONE}),
    "Accelerometer + Microphone": MAIN_INPUT_CHANNEL_TYPES,
}


# The Compute Result Set dialog's combo over the Data Pool. "All" is both
# sensors -- never the tacho, voltage or unclassified channels.
DATA_POOL_TYPE_OPTIONS: Mapping[str, FrozenSet[str]] = {
    "All": MAIN_INPUT_CHANNEL_TYPES,
    "Accelerometer": frozenset({CHANNEL_TYPE_ACCELEROMETER}),
    "Microphone": frozenset({CHANNEL_TYPE_MICROPHONE}),
}
DEFAULT_DATA_POOL_TYPE = "All"


def resolve_data_pool_types(label: str) -> FrozenSet[str]:
    """The sensor types the Data Pool combo's `label` stands for; All for an unknown one."""
    return DATA_POOL_TYPE_OPTIONS.get(label, DATA_POOL_TYPE_OPTIONS[DEFAULT_DATA_POOL_TYPE])


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
