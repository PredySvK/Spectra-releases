"""
Where the Band RMS band stands on a spectrum and what its readout says, without
Qt -- the dock only draws the two lines and the text.

Both work in Hz, the spectrum's own unit. The global X axis unit only
scales the edges the readout names (issue #459), so the level never depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from core.axis_projections import XAxisDisplay
from core.units import UnitPreferences, check_units_compatibility, convert_numeric_array
from signal_processing.dsp.levels import compute_band_rms
from view_models.display_prefix import resolve_number_format

from ._legend_settings import base_display_unit
from ._plot_model import Trace

UNAVAILABLE = "Band RMS unavailable"


@dataclass(frozen=True)
class BandRmsSpan:
    """In Hz: the spectrum's extent the band must stay in, and where it stands."""

    low: float
    high: float
    start: float
    stop: float


def resolve_band_rms_span(band: Optional[Tuple[float, float]],
                          frequencies: Optional[np.ndarray]) -> Optional[BandRmsSpan]:
    """Where the band stands on a spectrum of ``frequencies``: ``band`` clamped to
    the spectrum's extent, or a default window when nothing was dragged yet or the
    band lies wholly outside the spectrum. None when the spectrum has too few points
    to hold a band."""
    if frequencies is None or len(frequencies) < 2:
        return None
    low, high = float(frequencies[0]), float(frequencies[-1])
    if band is not None:
        start, stop = max(low, float(band[0])), min(high, float(band[1]))
        if start < stop:
            return BandRmsSpan(low, high, start, stop)
    width = high - low
    return BandRmsSpan(low, high, low + 0.10 * width, low + 0.35 * width)


def _plain_unit(trace: Trace) -> str:
    """The plain physical unit behind a curve's label -- a 'dB' axis unit resolved
    back to a source unit the curve actually has."""
    unit = trace.unit.strip()
    if unit == "dB":
        if trace.source_unit and trace.source_unit != "dB":
            unit = trace.source_unit
        elif trace.block is not None:
            unit = trace.block.value_unit
    return base_display_unit(unit)


def _resolve_level(trace: Trace, start: float, stop: float, unit: str) -> float:
    """The Band RMS of ``trace`` between ``start`` and ``stop``, in ``unit``."""
    block = trace.block
    level = compute_band_rms(frequencies=trace.x, p_canon=block.values, f_start=start, f_stop=stop)
    if unit and block.value_unit and check_units_compatibility(block.value_unit, unit):
        return float(convert_numeric_array(np.array([level]), from_unit=block.value_unit, to_unit=unit)[0])
    return level


def build_band_rms_readout(trace: Trace, start: float, stop: float, x_axis: XAxisDisplay,
                           prefs: UnitPreferences) -> str:
    """The text beside the band: the Band RMS of ``trace`` between ``start`` and
    ``stop`` (Hz), the band's edges on the X axis as drawn and the curve's legend
    text, since a graph may hold several curves and the one measured may be hidden.
    Two lines, because a third would lie on the legend's first row. Says it is
    unavailable when the curve has no canonical bin energy or the band cannot be
    measured (#673)."""
    if trace.block is None or not trace.block.is_canonical:
        return f"{UNAVAILABLE}\n{trace.label}"
    unit = _plain_unit(trace)
    try:
        level = _resolve_level(trace, start, stop, unit)
    except Exception as exc:
        return f"{UNAVAILABLE}: {exc}\n{trace.label}"
    number_format = resolve_number_format(unit, prefs)
    return (
        f"Band RMS  {number_format.format(level)} {number_format.shown_unit} RMS\n"
        f"{start * x_axis.scale:,.1f} – {stop * x_axis.scale:,.1f} {x_axis.unit}  ·  {trace.label}"
    )
