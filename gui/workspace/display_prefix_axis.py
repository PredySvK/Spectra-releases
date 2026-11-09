"""
pyqtgraph AxisItem delegating tick formatting and SI prefix scaling to view_models.display_prefix.
"""

from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg

from core.axis_projections import AxisScreenRule
from core.units import UnitPreferences
from view_models.display_prefix import NumberFormat, resolve_number_format


# Pixels one decade needs before the labelled 2 and 5 fit between the decades,
# and before unlabelled minor ticks are drawn.
_PX_PER_DECADE_FOR_2_AND_5 = 150.0
_PX_PER_DECADE_FOR_MINOR_TICKS = 80.0
_PX_PER_DECADE_LABEL = 70.0


class DisplayPrefixAxisItem(pg.AxisItem):
    """
    An AxisItem whose tick strings and label prefix come from the
    ``NumberFormat`` of its unit (view_models.display_prefix).

    The owner says which quantity the axis shows (``set_quantity``) -- it is
    what puts a Hz axis on the Speed or the Frequency row.
    """

    def __init__(
        self,
        orientation: str,
        unit_preferences_provider: Optional[Callable[[], UnitPreferences]] = None,
        **kwargs,
    ) -> None:
        self._unit_preferences_provider = unit_preferences_provider
        self._shown_rule_provider: Optional[Callable[[], AxisScreenRule]] = None
        self._quantity = ""
        super().__init__(orientation, **kwargs)
        self.enableAutoSIPrefix(False)

    def set_quantity(self, quantity: str) -> None:
        """The quantity of the axis values (``core.data_block.Axis.quantity``), "" if unknown."""
        if quantity != self._quantity:
            self._quantity = quantity
            self._update_display_prefix()

    def set_shown_rule_provider(self, provider: Callable[[], AxisScreenRule]) -> None:
        """The owner's rule for a shown value (``_shown_rule``); asked at every use."""
        self._shown_rule_provider = provider
        self._update_display_prefix()

    def _number_format(self) -> NumberFormat:
        prefs = self._unit_preferences_provider() if self._unit_preferences_provider is not None else None
        return resolve_number_format(self.labelUnits or "", prefs, quantity=self._quantity)

    def _shown_rule(self) -> AxisScreenRule:
        """Where a shown value (the Display unit) sits on this axis: the owner's
        rule (the dock's switch, §1.276), or the library's own log mode for an
        axis with no owner rule (a spectrogram, a dialog)."""
        if self._shown_rule_provider is not None:
            return self._shown_rule_provider()
        return AxisScreenRule(logarithmic=bool(self.logMode))

    def _shown_range(self) -> tuple[float, float]:
        shown = self._shown_rule().to_native(np.array(self.range))
        return shown[0], shown[1]

    def updateAutoSIPrefix(self) -> None:
        """Called by pyqtgraph to update SI prefix on axis range changes."""
        self._update_display_prefix()

    def update_display_prefix(self) -> None:
        """Forces recalculation of the display prefix and updates the axis label and picture."""
        self._update_display_prefix()

    def _update_display_prefix(self) -> None:
        if not hasattr(self, "_quantity"):
            return  # pg.AxisItem.__init__ calls back before our own __init__ ran
        low, high = self._shown_range()
        # A log axis labels every decade down to its lowest end, so its prefix
        # follows the lowest value, not the highest (§1.282).
        reference = low if self._shown_rule().logarithmic and low > 0 else max(abs(low), abs(high))
        prefix, factor = self._number_format().resolve_axis_prefix(reference * self.scale)
        self.autoSIPrefixScale = factor
        self.labelUnitPrefix = prefix

        self.picture = None
        self._updateLabel()
        self.update()

    def setLabel(
        self,
        text: str | None = None,
        units: str | None = None,
        unitPrefix: str | None = None,
        **kwargs,
    ) -> None:
        super().setLabel(text=text, units=units, unitPrefix=unitPrefix, **kwargs)
        self._update_display_prefix()

    def setRange(self, mn: float, mx: float) -> None:
        super().setRange(mn, mx)
        self._update_display_prefix()

    def tickStrings(self, values: list[float], scale: float, spacing: float) -> list[str]:
        if self._shown_rule().logarithmic:
            return self.logTickStrings(values, scale, spacing)
        strings, _ = self._number_format().format_ticks(
            values, spacing=spacing, axis_prefix=self._label_prefix())
        return strings

    def _label_prefix(self) -> tuple[str, float]:
        """The (prefix, factor) the label shows; the ticks write the same (#1005)."""
        return self.labelUnitPrefix or "", self.autoSIPrefixScale

    # -- logarithmic mode -----------------------------------------------------
    # The library puts log10 values on the axis; the labels show the real value
    # in the Display unit. Decades are labelled, 2 and 5 too when they fit,
    # minor ticks never (§1.276). Level order is the library's: the
    # first level draws the longest ticks and its text always.

    def logTickValues(self, minVal: float, maxVal: float, size: float, stdTicks):
        if not (math.isfinite(minVal) and math.isfinite(maxVal)) or maxVal <= minVal or size <= 0:
            return []
        rule = self._shown_rule()
        per_decade = size / (maxVal - minVal)
        first, last = math.ceil(minVal), math.floor(maxVal)
        step = max(1, math.ceil(_PX_PER_DECADE_LABEL / per_decade))
        decades = [k for k in range(first, last + 1) if k % step == 0]
        labelled_digits = [2, 5] if step == 1 and per_decade >= _PX_PER_DECADE_FOR_2_AND_5 else []
        labelled = [k + rule.to_screen(d) for k in range(first - 1, last + 1) for d in labelled_digits]
        labelled = [v for v in labelled if minVal < v < maxVal]
        if len(decades) + len(labelled) < 2:
            return self._log_ticks_from_shown_values(minVal, maxVal, size, rule)
        levels = [(float(step), [float(k) for k in decades])]
        if labelled:
            levels.append((0.5, labelled))
        if per_decade >= _PX_PER_DECADE_FOR_MINOR_TICKS:
            minor = [k + rule.to_screen(d) for k in range(first - 1, last + 1) for d in range(2, 10)]
            levels.append((None, [v for v in minor if minVal < v < maxVal and not any(
                abs(v - w) < 1e-9 for w in labelled)]))
        return levels

    def _log_ticks_from_shown_values(self, minVal: float, maxVal: float, size: float, rule: AxisScreenRule):
        """Narrower than a decade with too few decade or digit ticks in view:
        ordinary round values of the shown quantity, placed through the rule."""
        low, high = (float(v) for v in rule.to_native(np.array([minVal, maxVal])))
        if not (math.isfinite(low) and math.isfinite(high)) or high <= low:
            return []  # an extreme range (10**308 and beyond) has no round values
        levels = []
        taken: list[float] = []
        for spacing, offset in self.tickSpacing(low, high, size):
            start = math.ceil((low - offset) / spacing) * spacing + offset
            values = [start + i * spacing for i in range(int((high - start) / spacing) + 1)]
            values = [v for v in values if v > 0 and not any(abs(v - t) < spacing * 0.01 for t in taken)]
            taken.extend(values)
            levels.append((1.0, [float(rule.to_screen(v)) for v in values]))
        return levels

    def logTickStrings(self, values: list[float], scale: float, spacing: float) -> list[str]:
        if spacing is None:
            return ["" for _ in values]
        shown = [float(v) for v in self._shown_rule().to_native(np.array(values, dtype=float))]
        strings, _ = self._number_format().format_ticks(shown, axis_prefix=self._label_prefix())
        return strings
