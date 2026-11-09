"""
The reference a file's dB values are relative to, and the one conversion of an
amplitude in dB to the linear amplitude. The usual reference of a unit is
core.units' (shared with the program's own dB display).

A file may state its values in dB ("20*log10(value / reference)"). The reader
turns them into linear amplitude at read, next to the Source amplitude
conversion (core/source_amplitude.py), so they overlay linear curves and the
program's own dB display works on them.
"""

from typing import Optional

import numpy as np

from core.units import resolve_usual_db_reference


def resolve_source_db_reference(unit: str, stated: float) -> Optional[float]:
    """The reference to use: the one stated (above 0), else the unit's suggestion, else None."""
    return stated if stated > 0 else resolve_usual_db_reference(unit)


def convert_db_to_linear(values_db, reference: float) -> np.ndarray:
    """Linear amplitude of values in dB: reference * 10^(dB / 20)."""
    return reference * np.power(10.0, np.asarray(values_db, dtype=np.float64) / 20.0)

