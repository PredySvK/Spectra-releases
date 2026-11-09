"""
Block values in display settings -- the one rule that decides which values of a
block a graph shows and whether and how dB applies to them.

``resolve_curve_values`` is that rule for a curve, whatever its kind and
whichever way it reaches the graph: the base curve, an added curve and every
rebuild read it instead of each carrying their own "canonical -> display values,
RMS/Peak, squared dB formula" copy (#891). It also names the Format x
Amplitude those values are in, and ``build_trace_shown_as`` is the one place a
curve records it (#945). The spectrogram reads the spectral half of it,
``resolve_block_values``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

import numpy as np

from core.block_kinds import KIND_SPECTROGRAM, KIND_SPECTRUM, KINDS
from core.units import format_order_unit, is_squared_format

from ._display_settings import DisplaySettings
from ._plot_model import Trace

_DB_FLOOR_AMPLITUDE = 1e-12  # -240 dB
_DB_FLOOR_ENERGY = _DB_FLOOR_AMPLITUDE ** 2


def to_decibels(values: np.ndarray, is_squared: bool, reference: float = 1.0) -> np.ndarray:
    """
    The one dB conversion rule for a spectral quantity: a squared
    (power/PSD) format is already energy, so it only needs 10*log10; a linear
    (amplitude) format needs 20*log10 to land on the same dB scale.
    ``reference`` is the linear value that is 0 dB, in the unit of ``values``
    (core.units.resolve_db_reference); a squared format is relative to its square.

    The zero guard is one floor in dB (#695): clipping the raw values at one
    number would floor an amplitude at -240 dB but its energy at -120 dB, so
    a quiet bin jumped 120 dB when only the format was switched.
    """
    floor = _DB_FLOOR_ENERGY if is_squared else _DB_FLOOR_AMPLITUDE
    safe = np.clip(np.asarray(values) / (reference ** 2 if is_squared else reference), floor, None)
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


@dataclass(frozen=True)
class CurveValues:
    """
    ``values`` / ``unit``: the linear values a curve shows, before the global
    unit. ``db_squared``: the dB formula when the curve is shown in dB (10*log10
    for a squared format), None when it is not -- dB is for spectra only (§1.185).
    ``spectrum_format`` / ``amplitude_mode``: the Format x Amplitude ``values``
    are in, "" for what the curve is not in -- the format of anything but a
    spectrum, the amplitude of a curve RMS / Peak does not scale (#945).
    """

    values: np.ndarray
    unit: str
    db_squared: Optional[bool]
    spectrum_format: str = ""
    amplitude_mode: str = ""


def resolve_curve_values(
    block: Optional[Any], settings: DisplaySettings, values: np.ndarray, unit: str,
) -> CurveValues:
    """
    The values a curve of ``block`` shows in ``settings``, by the kind of the
    block: a canonical spectrum scaled to the Format x Amplitude, a kind that
    scales with RMS / Peak (``KindSpec.scales_with_rms_peak``) from its block
    values, anything else -- no block, a time record, a pre-scaled spectrum --
    its own ``values`` / ``unit`` (a caller handing over a block hands over its
    raw values with it). A pre-scaled spectrum is in the format it is stored in,
    whatever ``settings`` ask for.
    """
    shown = resolve_block_values(block, settings.spectrum_format, settings.spectrum_amplitude_mode)
    if shown is not None:
        db_squared = shown.db_is_squared if settings.decibel_scale else None
        if shown.rescaled:
            return CurveValues(shown.values, shown.unit, db_squared, shown.spectrum_format, shown.amplitude_mode)
        return CurveValues(values, unit, db_squared, shown.spectrum_format, shown.amplitude_mode)
    spec = KINDS.get(getattr(block, "kind", None))
    if spec is not None and spec.scales_with_rms_peak:
        rms_or_peak, rms_or_peak_unit = linear_amplitude_display(block.values, block.value_unit,
                                                                 settings.amplitude_mode)
        return CurveValues(rms_or_peak, rms_or_peak_unit, None, amplitude_mode=settings.amplitude_mode)
    return CurveValues(values, unit, None)


def build_trace_shown_as(trace: Trace, shown: CurveValues) -> Trace:
    """``trace`` recording the Format x Amplitude ``shown`` says its values are
    in -- what a cursor readout names and a spectrum drop takes over. Every way a
    curve reaches or is rebuilt on a graph records it here, so a curve says the
    same whichever way it arrived (#945)."""
    return replace(trace, spectrum_format=shown.spectrum_format, amplitude_mode=shown.amplitude_mode)
