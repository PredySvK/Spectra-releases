# =====================================================================
# FILE: gui/filter_panel/filter_panel_widgets.py
# =====================================================================
"""
Stateless helpers for filter_panel.py's facet controls: the two small Qt
subclasses a facet needs (a multi-select menu that survives a click, a spin
box that hides its own trailing zeros) and the plain formatting/styling
functions shared by every `_build_*_group` builder in facet_grid.py.

Nothing here reads or writes a FilterPanel's own state -- everything takes
what it needs as arguments, which is what lets it be split out of the class
that owns that state without threading it back in.
"""
from typing import Any, Callable, List, Tuple, Union

from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QDoubleSpinBox, QMenu

from selection.trace_filter import EMPTY_FACET_VALUE

# One entry a facet can offer: the value the mask is keyed by, and what the
# user reads. The two differ for Channel (a (base, direction) tuple) and Order
# (a float), which is why every facet goes through this pair rather than
# through its label alone.
_FacetEntry = Tuple[Any, str]

# What one facet value is driven by on screen: a QCheckBox in a list, or a
# checkable QAction in a multi-select menu. The two are interchangeable for
# everything this panel (and its tests) do with them -- isChecked, setChecked,
# text -- which is what makes the two widgets one filter (§1.34).
_Control = Union[QCheckBox, QAction]


class _MultiSelectMenu(QMenu):
    """
    A QMenu that stays open while its checkable items are ticked.

    Qt closes a menu on any activation, which would cost a multi-select column
    one reopen per value -- the opposite of the trade it exists for (§1.34: the
    same mask as a checkbox list, in one row instead of thirty). Only checkable
    items are intercepted; "All" / "None" are plain items and close as usual.
    """

    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action is not None and action.isEnabled() and action.isCheckable():
            action.trigger()   # toggles and emits, without dismissing the menu
            return
        super().mouseReleaseEvent(event)


def _format_order(order: float) -> str:
    return str(int(order)) if float(order).is_integer() else str(order)


def _facet_entries(values: Any, label_of: Callable[[Any], str]) -> List[Tuple[Any, str]]:
    """`(value, label)` pairs for a checkbox list, with the "(Empty)" bucket row
    (ADR §1.56) labelled literally rather than run through `label_of` (which
    would choke on the non-numeric sentinel)."""
    return [(v, v if v == EMPTY_FACET_VALUE else label_of(v)) for v in values]


def _format_number(value: Any) -> str:
    """A number for a range bound, without redundant trailing zeros
    ("25600.0000" -> "25600", "1.50" -> "1.5"). A value that is not numeric is
    returned as its plain string (ARCHITECTURE_DECISIONS §1.37). Metadata
    checkbox labels do not come through here: they are categorical text and
    shown literally (#405)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _dead_text_color() -> QColor:
    """
    The colour a dead control's text is drawn in -- Qt's own Disabled/WindowText
    blended halfway to the window background, not that colour alone. Qt's stock
    disabled grey sits close enough to normal text that a dead row next to a
    live one read as barely different (too little contrast); pushing it further
    toward the background is what a "this is faded out" cue actually needs, and
    it keeps that meaning under both a light and a dark theme since both
    colours come off the live QApplication palette rather than being hardcoded.
    """
    palette = QApplication.palette()
    text = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText)
    background = palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Window)
    return QColor(
        (text.red() + background.red()) // 2,
        (text.green() + background.green()) // 2,
        (text.blue() + background.blue()) // 2,
    )


def _style_dead_control(control: _Control, dead: bool) -> None:
    """
    Greys a facet control's text when it currently has zero effect -- every
    trace carrying its value is already hidden by some OTHER column's checks
    (facet_value_availability, ticket needs-triage "sivé kolónky bez efektu").
    Purely visual, never `setEnabled(False)`: the control stays clickable so a
    later change elsewhere can bring it back to life without the user having
    to re-touch this one.

    Called both when a control is first built and, by
    FilterPanel._refresh_dead_state(), on every later checkbox/range edit to
    restyle a control already on screen -- so it always sets a definite state
    (never just "grey and never ungrey") rather than only reacting to `dead`
    being true.
    """
    if isinstance(control, QCheckBox):
        color = (_dead_text_color() if dead else
                QApplication.palette().color(QPalette.ColorGroup.Active, QPalette.ColorRole.WindowText))
        palette = control.palette()
        palette.setColor(QPalette.ColorRole.WindowText, color)
        control.setPalette(palette)
    else:
        # A checkable QAction in a multi-select menu has no palette of its
        # own to recolour -- italic is the closest "this does nothing right
        # now" cue Qt gives a plain QAction's text.
        font = control.font()
        font.setItalic(dead)
        control.setFont(font)


class _TrimmedDoubleSpinBox(QDoubleSpinBox):
    """A range-bound spin box that shows 25600, not 25600.0000 -- the fixed
    decimal count is there so a hand-typed bound keeps its precision, but on an
    integer-valued bound the trailing zeros are only noise (§1.37).

    `textFromValue` runs the trimmed digits through the widget's own locale
    (ticket #403): `_format_number` always builds a '.'-decimal string, but
    `QDoubleSpinBox.validate`/`valueFromText` parse against `self.locale()`.
    Under a decimal-comma locale that mismatch made every displayed value
    read back as `Invalid` -- the shown '12.5' typed back in became 125, and
    any in-place edit of the shown text was rejected outright.
    """

    def textFromValue(self, value: float) -> str:
        text = _format_number(value)
        decimal_point = self.locale().decimalPoint()
        return text.replace(".", decimal_point) if decimal_point != "." else text
