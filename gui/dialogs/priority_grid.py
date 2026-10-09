# =====================================================================
# FILE: gui/dialogs/priority_grid.py
# =====================================================================
"""
One titled section of a checkbox + Priority grid (ticket #570, ADR §1.149).

Each row is a Priority cell (up/down arrows stacked beside a two-character
spin box, §1.37) and a checkbox. A dialog that needs more columns -- Configure
Filters adds "Shown as" and "Default" -- passes their headers and a callback
that fills them. The grid only draws and reports edits; what a tick or a
Priority means is the owning dialog's business.
"""
from typing import Callable, Dict, Optional, Sequence, Tuple

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

_GREYED_STYLE = "color: #808080;"

# One row: key, checkbox text, and why the row is greyed (None = not greyed).
PriorityGridEntry = Tuple[str, str, Optional[str]]


class PriorityGrid(QGroupBox):
    def __init__(self, title: str, entries: Sequence[PriorityGridEntry], *,
                 checked_keys, on_toggled: Callable[[str, bool], None],
                 on_nudge: Callable[[str, int], None],
                 on_order_typed: Callable[[str], None],
                 extra_headers: Sequence[str] = (),
                 add_extra_cells: Optional[Callable[[QGridLayout, int, str], None]] = None):
        super().__init__(title)
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.order_spins: Dict[str, QSpinBox] = {}
        self.up_buttons: Dict[str, QToolButton] = {}
        self.down_buttons: Dict[str, QToolButton] = {}
        self._on_toggled = on_toggled
        self._on_nudge = on_nudge
        self._on_order_typed = on_order_typed
        self._add_extra_cells = add_extra_cells

        headers = ("Priority", "Name", *extra_headers)
        grid = QGridLayout(self)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)   # the Name column takes the slack

        if not entries:
            grid.addWidget(QLabel("Nothing here yet."), 0, 0, 1, len(headers),
                           alignment=Qt.AlignmentFlag.AlignTop)
            grid.setRowStretch(1, 1)
            return

        for column, text in enumerate(headers):
            header = QLabel(text)
            header.setObjectName("GridHeader" + text.replace(" ", ""))
            header.setStyleSheet("font-weight: bold;")
            grid.addWidget(header, 0, column)

        for row, (key, text, greyed_reason) in enumerate(entries, start=1):
            self._add_row(grid, row, key, text, greyed_reason, key in checked_keys)
        # Keep the rows packed under the header -- without this the grid spreads
        # them down a section that happens to be tall (Excel has far more fields
        # than Identity).
        grid.setRowStretch(len(entries) + 1, 1)

    def _add_row(self, grid: QGridLayout, row: int, key: str, text: str,
                 greyed_reason: Optional[str], checked: bool) -> None:
        # Priority cell: the up/down arrows stacked on top of each other, left of
        # a two-character spin box, the stack as tall as the spin box (§1.37).
        # The spin box's own step buttons are off -- they were the second pair of
        # arrows the ticket dropped.
        priority = QWidget()
        priority_layout = QHBoxLayout(priority)
        priority_layout.setContentsMargins(0, 0, 0, 0)
        priority_layout.setSpacing(2)

        arrows = QWidget()
        arrows_layout = QVBoxLayout(arrows)
        arrows_layout.setContentsMargins(0, 0, 0, 0)
        arrows_layout.setSpacing(0)

        up = QToolButton()
        up.setArrowType(Qt.ArrowType.UpArrow)
        up.setFixedSize(QSize(16, 11))
        up.setToolTip("Move one position earlier.")
        up.clicked.connect(lambda _checked=False, k=key: self._on_nudge(k, -1))
        self.up_buttons[key] = up
        arrows_layout.addWidget(up)

        down = QToolButton()
        down.setArrowType(Qt.ArrowType.DownArrow)
        down.setFixedSize(QSize(16, 11))
        down.setToolTip("Move one position later.")
        down.clicked.connect(lambda _checked=False, k=key: self._on_nudge(k, 1))
        self.down_buttons[key] = down
        arrows_layout.addWidget(down)

        priority_layout.addWidget(arrows)

        spin = QSpinBox()
        spin.setRange(1, 999)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spin.setFixedWidth(spin.fontMetrics().horizontalAdvance("00") + 14)
        spin.setToolTip("Position on the card. Lower is drawn first.")
        spin.editingFinished.connect(lambda k=key: self._on_order_typed(k))
        self.order_spins[key] = spin
        priority_layout.addWidget(spin)
        priority_layout.addStretch()

        grid.addWidget(priority, row, 0)

        checkbox = QCheckBox(text)
        checkbox.setChecked(checked)
        if greyed_reason:
            checkbox.setStyleSheet(_GREYED_STYLE)
            checkbox.setToolTip(f"Cannot narrow anything down right now: {greyed_reason}.")
        checkbox.toggled.connect(lambda state, k=key: self._on_toggled(k, state))
        self.checkboxes[key] = checkbox
        grid.addWidget(checkbox, row, 1)

        if self._add_extra_cells is not None:
            self._add_extra_cells(grid, row, key)

    def set_row_order(self, key: str, order: Optional[int]) -> None:
        """Show `order` in the row's Priority cell, or park the cell (disabled,
        1) when the row is off (order None)."""
        on = order is not None
        for widget in (self.order_spins[key], self.up_buttons[key], self.down_buttons[key]):
            widget.setEnabled(on)
        spin = self.order_spins[key]
        blocked = spin.blockSignals(True)
        spin.setValue(order if on else 1)
        spin.blockSignals(blocked)
