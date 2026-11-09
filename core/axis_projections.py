# =====================================================================
# FILE: core/axis_projections.py
# =====================================================================
"""
Register of exact X-axis projections between quantities -- pure data rules,
no I/O, no Qt, same shape and same place as core/block_kinds.py.

A dock has one X domain; a curve whose native quantity differs from it is
drawn only if a registered projection can get it there (ARCHITECTURE_DECISIONS
§1.30). Identity (from == to) is always possible and needs no entry. Today's
only cross entry is order-cut -> frequency: a curve plotted against rpm at a
fixed order o sits at f = o * rpm / 60, point for point, no interpolation.

The same place says how an axis is shown: XAxisDisplay (label, unit, X axis
unit scale) and AxisScreenRule, the one native -> screen rule (scale, then
log10 on a Logarithmic axis, §1.276) with its inverse and the lower edge
of a Logarithmic X axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from core.block_kinds import PARAM_ORDER


@dataclass(frozen=True)
class Projection:
    """One registered way to re-express an X array in another quantity.

    ``required_params`` names the keys ``params`` (a trace's ``compute_spec``)
    must carry for ``transform`` to be applicable -- an order cut only knows
    its own frequency at a given rpm once the order it was extracted at is
    known.
    """

    required_params: Tuple[str, ...]
    transform: Callable[[np.ndarray, Dict[str, Any]], np.ndarray]


def _rpm_to_frequency(values: np.ndarray, params: Dict[str, Any]) -> np.ndarray:
    order = float(params[PARAM_ORDER])
    return values * order / 60.0


_REGISTRY: Dict[Tuple[str, str], Projection] = {
    ("rpm", "frequency"): Projection(
        required_params=(PARAM_ORDER,),
        transform=_rpm_to_frequency,
    ),
}

# Bottom-axis (label, unit) per quantity -- render() reads this off the dock's
# X domain rather than whatever the first-plotted curve happened to set, so
# the axis stays correct after the domain changes underneath it.
QUANTITY_AXIS_LABELS: Dict[str, Tuple[str, str]] = {
    "time": ("Time", "s"),
    "frequency": ("Frequency", "Hz"),
    "rpm": ("Speed", "RPM"),
}


def can_project(from_quantity: str, to_quantity: str, params: Dict[str, Any]) -> bool:
    """Whether a curve natively in ``from_quantity`` can be shown against
    ``to_quantity`` -- identity is free, anything else needs a registered,
    exact projection whose required params are all present in ``params``."""
    if from_quantity == to_quantity:
        return True
    projection = _REGISTRY.get((from_quantity, to_quantity))
    if projection is None:
        return False
    return all(key in params for key in projection.required_params)


def project_x(
    values: np.ndarray, from_quantity: str, to_quantity: str, params: Dict[str, Any]
) -> np.ndarray:
    """``values`` (native quantity ``from_quantity``) re-expressed in
    ``to_quantity``. Raises ValueError if ``can_project`` would say no --
    callers are expected to check first, this is what fires when they don't."""
    if from_quantity == to_quantity:
        return values
    projection = _REGISTRY.get((from_quantity, to_quantity))
    if projection is None:
        raise ValueError(
            f"No registered projection from '{from_quantity}' to '{to_quantity}'."
        )
    missing = [key for key in projection.required_params if key not in params]
    if missing:
        raise ValueError(
            f"Projection from '{from_quantity}' to '{to_quantity}' needs "
            f"{', '.join(missing)} in params."
        )
    return projection.transform(values, params)


def axis_label_for(quantity: str) -> Tuple[str, str]:
    """(label, unit) for the bottom axis when a dock's X domain is
    ``quantity``. Falls back to a title-cased label with no unit for a
    quantity that has no registered display -- still better than a blank
    axis, and no existing quantity is expected to hit it."""
    return QUANTITY_AXIS_LABELS.get(quantity, (quantity.title(), ""))


# The global X axis unit (issue #459): "native" shows every quantity in its
# own unit (a spectrum in Hz, an order cut in RPM); "Hz" and "rpm" put every
# frequency and speed axis in that one unit. A display rescale only -- 1 Hz
# is 60 RPM, nothing is projected (an order cut stays against shaft speed).
X_AXIS_NATIVE = "native"
X_AXIS_HZ = "Hz"
X_AXIS_RPM = "rpm"
X_AXIS_UNITS: Tuple[str, ...] = (X_AXIS_NATIVE, X_AXIS_HZ, X_AXIS_RPM)

# (quantity, x axis unit) -> (shown unit, factor from the quantity's own unit).
_X_AXIS_RESCALES: Dict[Tuple[str, str], Tuple[str, float]] = {
    ("frequency", X_AXIS_RPM): ("RPM", 60.0),
    ("rpm", X_AXIS_HZ): ("Hz", 1.0 / 60.0),
}


@dataclass(frozen=True)
class XAxisDisplay:
    """How an axis of one quantity is shown: its label, its unit, and what
    a value in the quantity's own unit is multiplied by to be drawn."""

    label: str
    unit: str
    scale: float = 1.0


def resolve_x_axis_display(quantity: str, x_axis_unit: str = X_AXIS_NATIVE) -> XAxisDisplay:
    """The axis of ``quantity`` under the global X axis unit. A quantity
    with no rescale for it (time, an unknown unit) is shown as it is."""
    label, unit = axis_label_for(quantity)
    rescale = _X_AXIS_RESCALES.get((quantity, x_axis_unit))
    if rescale is None:
        return XAxisDisplay(label, unit)
    return XAxisDisplay(label, *rescale)


@dataclass(frozen=True)
class AxisScreenRule:
    """Where a native value sits on screen along one axis (§1.276): first
    multiplied by ``scale`` (the X axis unit, §1.130; 1.0 on a Y axis), then,
    on a Logarithmic axis, its log10. The one definition every placement on
    the axis goes through -- curves, bands, ranges, the Cursor, the labels.

    A value with no screen position (X <= 0 on a Logarithmic axis, or a
    non-finite one) comes out NaN from ``to_screen``; nothing is clipped
    or reported, the value is simply not drawn.
    """

    scale: float = 1.0
    logarithmic: bool = False

    def to_screen(self, native: Any) -> Any:
        """``native`` (a float or an array) as a screen coordinate; float in, float out."""
        shown = np.asarray(native, dtype=float) * self.scale
        if self.logarithmic:
            with np.errstate(divide="ignore", invalid="ignore"):
                shown = np.where(shown > 0, np.log10(np.where(shown > 0, shown, 1.0)), np.nan)
        return float(shown) if shown.ndim == 0 else shown

    def to_native(self, screen: Any) -> Any:
        """The inverse of ``to_screen``; a screen coordinate beyond any float
        comes back as 0 or inf rather than raising."""
        values = np.asarray(screen, dtype=float)
        if self.logarithmic:
            with np.errstate(over="ignore", under="ignore"):
                values = np.power(10.0, values)
        native = values / self.scale
        return float(native) if native.ndim == 0 else native

    def has_screen_position(self, native: Any) -> Any:
        """Whether ``native`` (a float or an array) can be drawn at all; bool in, bool out."""
        shown = np.asarray(native, dtype=float) * self.scale
        drawable = np.isfinite(shown) & ((shown > 0) if self.logarithmic else True)
        return bool(drawable) if drawable.ndim == 0 else drawable


def resolve_x_axis_screen_rule(display: XAxisDisplay, logarithmic: bool = False) -> AxisScreenRule:
    """The screen rule of an X axis shown as ``display`` (its X axis unit
    scale), on a Logarithmic axis when ``logarithmic``."""
    return AxisScreenRule(scale=display.scale, logarithmic=logarithmic)


def resolve_log_axis_floor(*native_xs: Any) -> Optional[float]:
    """The lower edge of a Logarithmic X axis (§1.276 point 4): the
    smallest positive finite X over ``native_xs`` (arrays in the native unit),
    or None when none of them has one. 0 Hz (the DC bin) and negative rpm
    (a run-down's reverse rotation) never become the edge."""
    floor: Optional[float] = None
    for xs in native_xs:
        values = np.asarray(xs, dtype=float).ravel()
        positive = values[np.isfinite(values) & (values > 0)]
        if positive.size:
            low = float(positive.min())
            floor = low if floor is None else min(floor, low)
    return floor
