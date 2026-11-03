"""
Trace in display settings -- the one rule that turns a curve's linear values into
the finished ``Trace`` a graph draws.

The base curve builders, the overlay builders and the in-memory rebuilds (units,
RMS/Peak, dB) all end in ``build_trace_in_display_settings`` instead of each carrying their own copy
of global-unit conversion, dB-last and primary/secondary axis routing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Tuple

import numpy as np

from core.channel_types import (
    CHANNEL_TYPE_ACCELEROMETER, CHANNEL_TYPE_MICROPHONE, CHANNEL_TYPE_TACHO, CHANNEL_TYPE_VOLTAGE,
)
from core.units import (
    UnitPreferences,
    check_units_compatibility,
    convert_numeric_array,
    convert_signal_to_global_unit,
    format_order_unit,
    sanitize_unit_string,
)

from ._block_values import to_decibels
from ._legend_settings import build_legend_text, format_display_unit
from ._plot_model import PlotModel, Trace

# Ordinate-axis title per channel type (core.units.determine_channel_type).
# "general_dynamic" and anything unmapped fall back to the neutral "Amplitude".
_AXIS_QUANTITY_LABELS = {
    CHANNEL_TYPE_ACCELEROMETER: "Acceleration",
    CHANNEL_TYPE_MICROPHONE: "Sound Pressure",
    CHANNEL_TYPE_VOLTAGE: "Voltage",
    CHANNEL_TYPE_TACHO: "Speed",
}


def y_axis_label(channel_type: str) -> str:
    return _AXIS_QUANTITY_LABELS.get(channel_type, "Amplitude")


def base_trace_index(model: PlotModel) -> int:
    """Index of the base curve in ``model``, falling back to 0 if none has is_base (#356)."""
    return next((i for i, t in enumerate(model.traces) if t.is_base), 0 if model.traces else -1)


def linear_amplitude_display(values: np.ndarray, value_unit: str, amplitude_mode: str):
    """
    The shared RMS<->Peak display rule for an order cut or an Overall Level
    block: Peak = sqrt(2) * RMS, unit suffixed via
    ``format_order_unit``. RMS passes ``values``/``value_unit`` through
    untouched -- the unit is whatever the block/trace already carries, not
    forced into a canonical "unit RMS" spelling, so a caller comparing against
    an un-suffixed stored unit (e.g. a legacy "g") does not see it change.
    An Imported result takes the same rule: it is RMS once read.
    """
    if amplitude_mode == "peak":
        return values * np.sqrt(2.0), format_order_unit(value_unit, "linear", amplitude_mode)
    return values, value_unit


def resolve_overlay_axis(
    base_unit: Optional[str],
    overlay_unit: str,
    *,
    base_is_db: bool = False,
    overlay_is_db: bool = False,
) -> str:
    """Decide whether an overlay trace belongs on the 'primary' or 'secondary' axis (#355).

    An overlay shares the primary axis when both the base and overlay curves are
    shown in dB, or when both are linear and their units are compatible
    (e.g. g RMS and m/s^2 RMS). In all other cases (different physical quantities
    or dB mixed with linear), the overlay is routed to the secondary axis.
    """
    if base_is_db and overlay_is_db:
        return "primary"
    if not base_is_db and not overlay_is_db and base_unit and check_units_compatibility(base_unit, overlay_unit):
        return "primary"
    return "secondary"


@dataclass(frozen=True)
class BaseCurve:
    """What an overlay is placed against: the base curve's linear display unit
    (before any dB) and whether it is shown in dB."""

    unit: str
    is_db: bool


# What an overlay is placed against while no base curve exists yet: everything
# routes to the secondary axis.
NO_BASE_CURVE = BaseCurve("", False)


def resolve_base_curve(trace: Trace, prefs: UnitPreferences) -> BaseCurve:
    """``trace`` as the base curve overlays are placed against. A dB trace has
    lost its linear unit, so it is derived again from the trace's own raw unit."""
    if trace.unit != "dB":
        return BaseCurve(trace.unit, False)
    _, unit = convert_signal_to_global_unit(np.zeros(1), trace.source_unit, trace.channel_type, prefs)
    return BaseCurve(sanitize_unit_string(unit), True)


def build_trace_in_display_settings(
    trace: Trace,
    linear_y: np.ndarray,
    linear_unit: str,
    prefs: UnitPreferences,
    *,
    db_squared: Optional[bool] = None,
    against: Optional[BaseCurve] = None,
) -> Trace:
    """
    ``trace`` (its identity: names, channel type, block, pen, ...) with the
    values it is shown with, from its ``linear_y`` / ``linear_unit``:

    1. physical conversion to the global unit of ``prefs``;
    2. the axis -- ``against`` None makes it the base curve on the primary axis;
       otherwise a curve in a unit compatible with the base's shares the primary
       axis and is converted onto the base unit, anything else goes to the
       secondary axis (#355);
    3. dB last, from the converted values (``db_squared`` not None: the 10*log10
       formula for a squared format, else 20*log10; issue #354);
    4. the legend for the resulting unit.

    ``linear_y`` / ``linear_unit`` become ``y_raw`` / ``source_unit``.
    """
    render_y, target_unit = convert_signal_to_global_unit(linear_y, linear_unit, trace.channel_type, prefs)
    unit = sanitize_unit_string(target_unit)
    is_db = db_squared is not None

    if against is None:
        axis = "primary"
    else:
        axis = resolve_overlay_axis(against.unit, unit, base_is_db=against.is_db, overlay_is_db=is_db)
        if axis == "primary" and against.unit and check_units_compatibility(against.unit, unit):
            render_y = convert_numeric_array(render_y, from_unit=unit, to_unit=against.unit)
            unit = against.unit
    if is_db:
        render_y, unit = to_decibels(render_y, db_squared), "dB"

    label = build_legend_text(trace.file_name, trace.channel_name, unit, trace.meta_ref, trace.block)
    return replace(
        trace, y=render_y, unit=unit, label=label, axis=axis, is_base=against is None,
        y_raw=linear_y, source_unit=linear_unit,
    )


def resolve_ordinate_quantity(trace: Trace) -> str:
    """The quantity of ``trace``'s Y values: ``"rpm"`` for a speed channel, else ""."""
    return "rpm" if trace.channel_type == CHANNEL_TYPE_TACHO else ""


def resolve_ordinate(base: Trace) -> Tuple[str, str]:
    """The (label, unit) of the ordinate axis for ``base`` as the base curve."""
    if base.unit == "dB":
        return "Amplitude", "dB"
    return y_axis_label(base.channel_type or ""), format_display_unit(base.unit)
