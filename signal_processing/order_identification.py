"""
Match a measured order against a machine's characteristic orders.

This is what turns a cursor readout of "47.98x" into "2nd-stage gear mesh
(+0.04%)", and what lets the trend flagging say which known source a risen
peak sits on. Pure: it takes the catalogue that
``core.machine_model.MachineModel.characteristic_orders()`` returns and a
value, and returns the best label. No signal, no numpy.

Matching is relative -- a tolerance of 2% is 2% at order 1 and at order 50
alike -- because order spacing grows with order.
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

from core.machine_model import CharacteristicOrder


@dataclass(frozen=True)
class OrderMatch:
    """A characteristic order that a measured value fell close to."""
    characteristic: CharacteristicOrder
    deviation_percent: float  # signed: (measured - expected) / expected * 100


def _deviation_percent(value: float, expected: float) -> Optional[float]:
    """
    Signed percentage deviation of `value` from `expected`, or None when the two
    cannot be compared (an expected order of 0 only matches a value of exactly 0).
    """
    if expected == 0.0:
        return 0.0 if value == 0.0 else None
    return (value - expected) / expected * 100.0


def identify_orders(
    value: float,
    catalog: Sequence[CharacteristicOrder],
    tolerance_percent: float = 2.0,
) -> List[OrderMatch]:
    """
    Every characteristic order within `tolerance_percent` of `value`, closest
    first. Empty when nothing is near -- e.g. an order the machine model does
    not explain.
    """
    matches: List[OrderMatch] = []
    for characteristic in catalog:
        deviation = _deviation_percent(value, characteristic.order)
        if deviation is not None and abs(deviation) <= tolerance_percent:
            matches.append(OrderMatch(characteristic, deviation))

    matches.sort(key=lambda m: abs(m.deviation_percent))
    return matches


def identify_order(
    value: float,
    catalog: Sequence[CharacteristicOrder],
    tolerance_percent: float = 2.0,
) -> Optional[OrderMatch]:
    """The single closest characteristic order within tolerance, or None."""
    matches = identify_orders(value, catalog, tolerance_percent)
    return matches[0] if matches else None
