"""
Block values in display settings -- the one rule that decides which values of a
block a graph shows and whether and how dB applies to them.

The base curve, an added curve, the dB rebuild and the spectrogram all read a
spectral block through ``resolve_block_values`` instead of each carrying their
own "canonical -> display values / squared dB formula" copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from core.block_kinds import KIND_SPECTROGRAM, KIND_SPECTRUM
from core.units import is_squared_format

_DB_FLOOR_AMPLITUDE = 1e-12  # -240 dB
_DB_FLOOR_ENERGY = _DB_FLOOR_AMPLITUDE ** 2


def to_decibels(values: np.ndarray, is_squared: bool) -> np.ndarray:
    """
    The one dB conversion rule for a spectral quantity: a squared
    (power/PSD) format is already energy, so it only needs 10*log10; a linear
    (amplitude) format needs 20*log10 to land on the same dB scale.

    The zero guard is one floor in dB (#695): clipping the raw values at one
    number would floor an amplitude at -240 dB but its energy at -120 dB, so
    a quiet bin jumped 120 dB when only the format was switched.
    """
    floor = _DB_FLOOR_ENERGY if is_squared else _DB_FLOOR_AMPLITUDE
    safe = np.clip(values, floor, None)
    return 10.0 * np.log10(safe) if is_squared else 20.0 * np.log10(safe)


@dataclass(frozen=True)
class BlockValues:
    """
    ``values`` / ``unit``: the linear values to show. ``spectrum_format`` /
    ``amplitude_mode``: the format they are in. ``rescaled``: they were scaled
    on the fly from canonical power (a pre-scaled block is shown as it is).
    ``db_is_squared``: the dB formula, 10*log10 for a squared format.
    """

    values: np.ndarray
    unit: str
    spectrum_format: str
    amplitude_mode: str
    rescaled: bool
    db_is_squared: bool


def resolve_block_values(
    block: Optional[Any], spectrum_format: str, amplitude_mode: str,
) -> Optional[BlockValues]:
    """
    The values of ``block`` in the requested Format x Amplitude, or None when
    ``block`` is not a spectrum -- dB applies to spectra only. A canonical
    block is scaled to the request; a pre-scaled one keeps its own values and
    its dB formula follows the spectrum format it is stored in.
    """
    if block is None or block.kind not in (KIND_SPECTRUM, KIND_SPECTROGRAM):
        return None
    if getattr(block, "is_canonical", False):
        values, unit = block.to_display_values(spectrum_format=spectrum_format, amplitude_mode=amplitude_mode)
        return BlockValues(values, unit, spectrum_format, amplitude_mode,
                           rescaled=True, db_is_squared=is_squared_format(spectrum_format))
    processing = block.processing
    own_format = processing.spectrum_format if processing else "linear"
    own_amplitude = processing.amplitude_mode if processing else "rms"
    return BlockValues(block.values, block.value_unit, own_format, own_amplitude,
                       rescaled=False, db_is_squared=is_squared_format(own_format))
