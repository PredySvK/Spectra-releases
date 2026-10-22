"""
Display prefix -- how a shown number writes its magnitude on top of its Display unit.

``resolve_number_format(unit, prefs, quantity=...)`` resolves the Settings →
Units row for a Display unit once and returns a ``NumberFormat``: readout text,
shown unit, export value and xlsx cell format, and axis tick strings, all from
that one value. The caller that knows the quantity passes it (``"rpm"`` makes
``Hz`` a speed); nothing is guessed from labels.

``resolve_units_preview`` writes a sample number the way a Units row will show it.

The Settings Units page reads which prefixes a row offers from
``resolve_display_prefix_setting_choices`` / ``resolve_display_prefix_for_unit_change``.
"""

from ._number_format import NumberFormat, resolve_number_format, resolve_units_preview
from ._units_row import (
    resolve_display_prefix_choices,
    resolve_display_prefix_for_unit_change,
    resolve_display_prefix_setting_choices,
    resolve_units_row,
)

__all__ = [
    "NumberFormat",
    "resolve_display_prefix_choices",
    "resolve_display_prefix_for_unit_change",
    "resolve_display_prefix_setting_choices",
    "resolve_number_format",
    "resolve_units_preview",
    "resolve_units_row",
]
