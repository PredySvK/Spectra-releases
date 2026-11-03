"""
dB reference: what 0 dB means for a quantity, and the one conversion of an
amplitude in dB to the linear amplitude.

A file may state its values in dB ("20*log10(value / reference)"). The reader
turns them into linear amplitude at read, next to the Source amplitude
conversion (core/source_amplitude.py), so they overlay linear curves and the
program's own dB display works on them.
"""

from typing import Optional

import numpy as np

# The usual reference of a linear unit (lower case): acceleration 1e-6 m/s²,
# velocity 1e-9 m/s, sound pressure 20 µPa, force 1e-6 N.
_REFERENCE_OF_UNIT = {
    "m/s²": 1e-6, "m/s^2": 1e-6, "mm/s²": 1e-3, "mm/s^2": 1e-3, "g": 1e-6 / 9.80665,
    "m/s": 1e-9, "mm/s": 1e-6,
    "pa": 20e-6, "mpa": 20e-3, "kpa": 20e-9,
    "n": 1e-6,
}


def resolve_usual_db_reference(unit: str) -> Optional[float]:
    """The usual dB reference of this linear unit, None when the program has none for it."""
    return _REFERENCE_OF_UNIT.get(unit.strip().lower())


def resolve_db_reference(unit: str, stated: float) -> Optional[float]:
    """The reference to use: the one stated (above 0), else the unit's suggestion, else None."""
    return stated if stated > 0 else resolve_usual_db_reference(unit)


def convert_db_to_linear(values_db, reference: float) -> np.ndarray:
    """Linear amplitude of values in dB: reference * 10^(dB / 20)."""
    return reference * np.power(10.0, np.asarray(values_db, dtype=np.float64) / 20.0)

