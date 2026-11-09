"""How one kind of number is written: Display prefix and decimals resolved for a Display unit."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from core.settings import DECIMALS_CHOICES
from core.units import UnitPreferences

from ._units_row import (
    ALL_DISPLAY_PREFIXES,
    PREFIX_FACTORS,
    _is_g_unit,
    is_db_unit,
    read_row_setting,
    resolve_display_prefix_choices,
    resolve_units_row,
)

_ZERO = 1e-12
_AUTO_PREFIX_BY_THOUSANDS = {1: "k", 2: "M", -1: "m", -2: "µ"}


def _format_plain(value: float) -> str:
    """4 significant digits, never scientific; the integer part is never rounded away."""
    if value == 0.0 or abs(value) < _ZERO:
        return "0"
    places = max(0, 3 - math.floor(math.log10(abs(value))))
    text = f"{value:.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _format_auto(value: float) -> str:
    """``_format_plain``, but scientific below 1e-3 or from 1e5 (0 stays plain)."""
    if value != 0.0 and abs(value) >= _ZERO and (abs(value) < 1e-3 or abs(value) >= 1e5):
        return f"{value:.3e}"
    return _format_plain(value)


def _format_db(value: float) -> str:
    text = f"{value:.1f}" if abs(value) >= _ZERO else "0.0"
    return "0.0" if text == "-0.0" else text


@dataclass(frozen=True)
class NumberFormat:
    """How numbers in one Display unit are shown, with the user's row setting resolved.

    Built by ``resolve_number_format``. ``prefix`` is the row's Display prefix
    (``"none"`` for a unit without a row, a dB unit, or a prefix the unit does
    not offer); ``decimals`` is ``"auto"`` or ``"0"``..``"6"``. Auto decimals
    are 4 significant digits; only ``"scientific"`` writes a row's number
    in scientific notation, a number without a row also below 1e-3 or from 1e5.

    Readouts (``format``, ``shown_unit``, ``scale``, ``cell_format``) treat Auto
    as no prefix, so one column never mixes ``mg`` and ``g``. Axes
    (``resolve_axis_prefix``, ``format_ticks``) keep Auto as the automatic SI
    prefix and ignore decimals.
    """

    unit: str
    row: Optional[str] = None
    prefix: str = "none"
    decimals: str = "auto"
    db: bool = False

    # -- readouts ------------------------------------------------------------

    @property
    def _readout_prefix(self) -> str:
        return self.prefix if self.prefix in PREFIX_FACTORS else ""

    @property
    def shown_unit(self) -> str:
        """The unit a readout writes after the number (``mg`` for ``g`` + ``m``)."""
        prefix = self._readout_prefix
        if prefix and self.unit.lower() == "rpm":
            return f"{prefix}rpm"
        return f"{prefix}{self.unit}"

    def scale(self, value: float) -> float:
        """``value`` in ``shown_unit`` -- what a sort key or an exported cell holds."""
        return value * PREFIX_FACTORS.get(self._readout_prefix, 1.0)

    def format(self, value: float) -> str:
        """The number as a readout writes it, without the unit."""
        if not math.isfinite(value):
            return str(value)
        if self.db:
            return _format_db(value)
        shown = self.scale(value)
        if abs(shown) < _ZERO:
            shown = 0.0
        if self.prefix == "scientific":
            places = 3 if self.decimals == "auto" else int(self.decimals)
            return f"{shown:.{places}e}"
        if self.decimals == "auto":
            # A row's own setting decides on scientific; a number without a row
            # (PSD, power, metadata) has no switch, so extremes go scientific.
            return _format_auto(shown) if self.row is None else _format_plain(shown)
        places = int(self.decimals)
        text = f"{shown:.{places}f}"
        if float(text) == 0.0:
            return f"{0.0:.{places}f}" if places else "0"
        return text

    def format_with_unit(self, value: float) -> str:
        """``format(value)`` followed by ``shown_unit`` (``"12.3 mg"``)."""
        return f"{self.format(value)} {self.shown_unit}".strip()

    @property
    def cell_format(self) -> str:
        """The xlsx number format matching ``format`` for a cell holding ``scale(value)``."""
        if self.db:
            return "0.0"
        if self.prefix == "scientific":
            if self.decimals == "auto":
                return "0.00E+00"
            places = int(self.decimals)
            return f"0.{'0' * places}E+00" if places else "0E+00"
        if self.decimals == "auto":
            return "General"
        places = int(self.decimals)
        return f"0.{'0' * places}" if places else "0"

    # -- axes ----------------------------------------------------------------

    def resolve_axis_prefix(self, max_value: float) -> tuple[str, float]:
        """(SI prefix, factor) an axis spanning up to ``max_value`` is labelled with."""
        if self.prefix in PREFIX_FACTORS:
            return self.prefix, PREFIX_FACTORS[self.prefix]
        if self.prefix != "auto" or not (max_value > 0 and math.isfinite(max_value)):
            return "", 1.0
        chosen = _AUTO_PREFIX_BY_THOUSANDS.get(math.floor(math.log10(max_value) / 3), "")
        if chosen not in resolve_display_prefix_choices(self.unit):
            return "", 1.0
        return chosen, PREFIX_FACTORS[chosen]

    def format_ticks(
        self,
        values: Sequence[float],
        *,
        spacing: Optional[float] = None,
        axis_prefix: Optional[tuple[str, float]] = None,
    ) -> tuple[list[str], str]:
        """(tick strings, label unit) for an axis; decimals never apply to ticks.

        ``axis_prefix`` is the (prefix, factor) the axis label already shows
        (``resolve_axis_prefix``); the ticks take it as is, so label and ticks
        never disagree (#1005). Without it the prefix follows ``values``.
        """
        if self.prefix == "scientific":
            if spacing and spacing > 0:
                non_zero = [abs(v) for v in values if abs(v) > _ZERO]
                magnitude = math.floor(math.log10(max(non_zero))) if non_zero else 0
                places = max(0, min(6, magnitude - math.floor(math.log10(spacing))))
            else:
                places = 1
            return [f"{v:.{places}e}" for v in values], self.unit

        if axis_prefix is not None:
            prefix, factor = axis_prefix
        else:
            non_zero = [abs(v) for v in values if math.isfinite(v) and abs(v) > _ZERO]
            prefix, factor = self.resolve_axis_prefix(max(non_zero) if non_zero else 0.0)

        scaled_spacing = spacing * factor if spacing is not None else None
        places = (max(0, math.ceil(-math.log10(scaled_spacing)))
                  if scaled_spacing is not None and scaled_spacing > 0 else None)
        strings = []
        for v in values:
            shown = v * factor
            if abs(shown) < _ZERO:
                shown = 0.0
            if abs(shown - round(shown)) < 1e-9 and not places:
                strings.append(str(int(round(shown))))
            elif places is not None:
                strings.append(f"{shown:.{places}f}")
            else:
                strings.append(f"{shown:g}")
        return strings, f"{prefix}{self.unit}"


def resolve_number_format(
    unit: str,
    prefs: Optional[UnitPreferences],
    *,
    quantity: str = "",
    db: bool = False,
) -> NumberFormat:
    """How numbers in Display unit ``unit`` are shown under ``prefs``.

    ``quantity`` (``core.data_block.Axis.quantity``) only matters for ``Hz``:
    ``"rpm"`` puts it on the Speed row, anything else on Frequency. ``db``
    marks a dB value whose unit string does not say so.
    """
    cleaned = (unit or "").strip()
    if db or is_db_unit(cleaned):
        return NumberFormat(cleaned, db=True)
    row = resolve_units_row(cleaned, quantity=quantity)
    if row is None:
        return NumberFormat(cleaned)
    prefix, decimals = read_row_setting(prefs or UnitPreferences(), row)
    if prefix not in ALL_DISPLAY_PREFIXES or (_is_g_unit(cleaned) and prefix in ("k", "M")):
        prefix = "none"
    if decimals not in DECIMALS_CHOICES:
        decimals = "auto"
    return NumberFormat(cleaned, row=row, prefix=prefix, decimals=decimals)


def resolve_units_preview(unit: str, row: str, prefix: str, decimals: str, *, sample: float = 1.23456) -> str:
    """``sample`` (given in ``unit``) as a readout of Units ``row`` writes it with ``prefix`` and ``decimals``."""
    prefs = UnitPreferences(**{f"prefix_{row}": prefix, f"decimals_{row}": decimals})
    number_format = resolve_number_format(unit, prefs, quantity="rpm" if row == "speed" else "")
    return number_format.format_with_unit(sample)
