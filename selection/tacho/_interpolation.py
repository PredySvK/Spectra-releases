from dataclasses import dataclass
from typing import Optional, Tuple

from core.channel_types import CHANNEL_TYPE_TACHO
from core.models import READING_WAVEFORM, resolve_channel_reading

from ._tacho import find_tacho_channel

# Two rates closer than this count as one: a real file's header can be off by that much.
RATE_TOLERANCE = 0.01


@dataclass(frozen=True)
class TachoInterpolation:
    """A Tacho interpolation that applies to a file: its tacho and the channel rates it is carried onto."""

    tacho_name: str
    tacho_rate: float
    channel_rates: Tuple[float, ...]


def read_channel_rate(channel_meta) -> float:
    """The sampling rate a channel declares, 0.0 when it declares none."""
    rate = float(getattr(channel_meta, "sampling_rate", 0.0) or 0.0)
    if rate > 0.0:
        return rate
    step = float(getattr(channel_meta, "abscissa_inc", 0.0) or 0.0)
    return 1.0 / step if step > 0.0 else 0.0


def tacho_interpolates(tacho_rate: float, channel_rate: float) -> bool:
    """True when a tacho of `tacho_rate` has to be interpolated onto a channel of `channel_rate`."""
    if tacho_rate <= 0.0 or channel_rate <= 0.0:
        return False
    return abs(tacho_rate - channel_rate) / max(tacho_rate, channel_rate) > RATE_TOLERANCE


def find_tacho_interpolation(run_index, channel_names=None) -> Optional[TachoInterpolation]:
    """The Tacho interpolation a file needs, or ``None``.

    None when the file has no tacho or the tacho shares the rate of every time
    channel (within 1 %). Imported results are not time channels and do not count.
    `channel_names` limits the channels looked at (a batch step's own).
    """
    tacho = find_tacho_channel(run_index)
    if tacho is None:
        return None
    tacho_rate = read_channel_rate(tacho)
    rates = []
    for meta in getattr(run_index, "available_channels", {}).values():
        if getattr(meta, "type", None) == CHANNEL_TYPE_TACHO or resolve_channel_reading(meta) != READING_WAVEFORM:
            continue
        if channel_names is not None and meta.name not in channel_names:
            continue
        rate = read_channel_rate(meta)
        if tacho_interpolates(tacho_rate, rate) and not any(not tacho_interpolates(rate, seen) for seen in rates):
            rates.append(rate)
    if not rates:
        return None
    return TachoInterpolation(tacho.name, tacho_rate, tuple(sorted(rates)))
