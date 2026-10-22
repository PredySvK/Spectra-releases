"""
pyqtgraph AxisItem delegating tick formatting and SI prefix scaling to view_models.display_prefix.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
import pyqtgraph as pg

from core.units import UnitPreferences
from view_models.display_prefix import NumberFormat, resolve_number_format


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
        self._quantity = ""
        super().__init__(orientation, **kwargs)
        self.enableAutoSIPrefix(False)

    def set_quantity(self, quantity: str) -> None:
        """The quantity of the axis values (``core.data_block.Axis.quantity``), "" if unknown."""
        if quantity != self._quantity:
            self._quantity = quantity
            self._update_display_prefix()

    def _number_format(self) -> NumberFormat:
        prefs = self._unit_preferences_provider() if self._unit_preferences_provider is not None else None
        return resolve_number_format(self.labelUnits or "", prefs, quantity=self._quantity)

    def _shown_range(self) -> tuple[float, float]:
        shown = 10 ** np.array(self.range) if self.logMode else self.range
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
        prefix, factor = self._number_format().resolve_axis_prefix(max(abs(low), abs(high)) * self.scale)
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
        strings, _ = self._number_format().format_ticks(
            values, spacing=spacing, scale=scale, axis_range=self._shown_range())
        return strings
