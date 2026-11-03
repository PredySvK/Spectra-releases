# =====================================================================
# FILE: core/channel_types.py
# =====================================================================
"""
The Channel type vocabulary: which sensor a channel comes from (§1.11, §1.217).

One set of string constants that readers, selection, view models and the GUI
all use, so a typo is an ImportError rather than a filter that silently
matches nothing. The values are stored as they are -- in a project's source
channels, a Save spec's `channel_types`, the result cache -- so they are never
renamed without a migration.

The words name the sensor, not the physical quantity: a microphone channel is
`microphone`, never `sound_pressure`; the quantity is what the axis is titled
(§1.217). `general_dynamic` is the one value for "none of these", also when
nobody classified the channel at all.

`core.units.determine_channel_type` is what assigns them.
"""

from typing import FrozenSet, Tuple

CHANNEL_TYPE_ACCELEROMETER = "accelerometer"
CHANNEL_TYPE_MICROPHONE = "microphone"
CHANNEL_TYPE_TACHO = "tacho"
CHANNEL_TYPE_VOLTAGE = "voltage"
CHANNEL_TYPE_GENERAL_DYNAMIC = "general_dynamic"

CHANNEL_TYPES: Tuple[str, ...] = (
    CHANNEL_TYPE_ACCELEROMETER,
    CHANNEL_TYPE_MICROPHONE,
    CHANNEL_TYPE_TACHO,
    CHANNEL_TYPE_VOLTAGE,
    CHANNEL_TYPE_GENERAL_DYNAMIC,
)

# What a computation may take as its main input. The tacho is never in it: it
# is a rotation signal, bound as the rpm port of Order Tracking and Overall
# Level, and a spectrum of it means nothing (§1.218).
MAIN_INPUT_CHANNEL_TYPES: FrozenSet[str] = frozenset({
    CHANNEL_TYPE_ACCELEROMETER,
    CHANNEL_TYPE_MICROPHONE,
})
