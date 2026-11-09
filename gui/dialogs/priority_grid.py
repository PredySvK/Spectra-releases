# =====================================================================
# FILE: gui/dialogs/priority_grid.py
# =====================================================================
"""
The checkbox + Priority grid of every settings window that picks fields and
their order: Configure Filters, Cursor Settings, Track cursor Settings and
Legend Settings (ticket #570, ADR §1.149, shell §1.301).

The window hands in titled sections of rows and the ticked keys; the grid owns
everything a tick or a Priority means from there on:

- the ticked keys in Priority order -- one order across every section; a tick
  appends last, the arrows nudge, a typed number moves the row there
  (`core.field_priority`, the one rule);
- the Priority cells: up/down arrows stacked beside a two-character spin box
  (§1.37), parked (disabled, 1) on an unticked row;
- the Default column when the window asks for one (Configure Filters §1.56,
  Legend Settings plot §1.298): enabled only on a ticked row, unticking a row
  drops its Default, Default keys no ticked row shows stay as they are;
- keys no row offers (a field of another project's schema): kept aside at the
  end of `fields`, so a choice survives a project that lacks them.

`changed` is emitted after every edit of the ticks or the order -- the window's
cue for Auto apply. A Default toggle does not emit: no preview shows it.
A window that needs more columns (Configure Filters' "Shown as") passes their
headers and a callback that fills them; the Default column comes after them.
"""
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox, QCheckBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from core.field_priority import move_key, ordered_defaults, with_default, with_key, with_key_order
from gui.appearance import APP_TOKENS


# One row: key, checkbox text, and why the row is greyed (None = not greyed).
PriorityGridEntry = Tuple[str, str, Optional[str]]
# One titled section of rows.
PriorityGridSection = Tuple[str, Sequence[PriorityGridEntry]]


class _PrioritySection(QGroupBox):
    """One titled section: draws its rows and forwards their edits to the grid."""

    def __init__(self, title: str, entries: Sequence[PriorityGridEntry], headers: Sequence[str],
                 add_cells: Callable[[QGridLayout, int, str], None], *,
                 on_toggled: Callable[[str, bool], None], on_nudge: Callable[[str, int], None],
                 on_order_typed: Callable[[str], None]):
        super().__init__(title)
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.order_spins: Dict[str, QSpinBox] = {}
        self.up_buttons: Dict[str, QToolButton] = {}
        self.down_buttons: Dict[str, QToolButton] = {}
        self._on_toggled = on_toggled
        self._on_nudge = on_nudge
        self._on_order_typed = on_order_typed

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
            self._add_row(grid, row, key, text, greyed_reason)
            add_cells(grid, row, key)
        # Keep the rows packed under the header -- without this the grid spreads
        # them down a section that happens to be tall (Excel has far more fields
        # than Identity).
        grid.setRowStretch(len(entries) + 1, 1)

    def _add_row(self, grid: QGridLayout, row: int, key: str, text: str, greyed_reason: Optional[str]) -> None:
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
        if greyed_reason:
            checkbox.setStyleSheet(f"color: {APP_TOKENS.text_muted};")
            checkbox.setToolTip(f"Cannot narrow anything down right now: {greyed_reason}.")
        checkbox.toggled.connect(lambda state, k=key: self._on_toggled(k, state))
        self.checkboxes[key] = checkbox
        grid.addWidget(checkbox, row, 1)


class PriorityGrid(QWidget):
    """Sections side by side; `fields` (ticked keys in Priority order, then the kept-aside ones)
    and `defaults` (the Default column, or None without one) are the result."""

    changed = Signal()

    def __init__(self, sections: Sequence[PriorityGridSection], fields: Sequence[str], *,
                 defaults: Optional[Sequence[str]] = None,
                 default_tooltip: str = "",
                 extra_headers: Sequence[str] = (),
                 add_extra_cells: Optional[Callable[[QGridLayout, int, str], None]] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.checkboxes: Dict[str, QCheckBox] = {}
        self.order_spins: Dict[str, QSpinBox] = {}
        self.up_buttons: Dict[str, QToolButton] = {}
        self.down_buttons: Dict[str, QToolButton] = {}
        # The Default checkbox per row; empty without a Default column.
        self.default_checks: Dict[str, QCheckBox] = {}
        self.sections: List[QGroupBox] = []
        self._has_default_column = defaults is not None
        self._default_tooltip = default_tooltip
        self._add_extra_cells = add_extra_cells
        self._default_column_index = 2 + len(extra_headers)

        headers = ("Priority", "Name", *extra_headers, *(("Default",) if self._has_default_column else ()))
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        for title, entries in sections:
            section = _PrioritySection(
                title, entries, headers, self._add_cells,
                on_toggled=self._on_toggled, on_nudge=self._on_nudge, on_order_typed=self._on_order_typed)
            self.checkboxes.update(section.checkboxes)
            self.order_spins.update(section.order_spins)
            self.up_buttons.update(section.up_buttons)
            self.down_buttons.update(section.down_buttons)
            self.sections.append(section)
            row.addWidget(section)
        self._offered = frozenset(self.checkboxes)
        self._ticked: Tuple[str, ...] = ()
        self._kept_aside: Tuple[str, ...] = ()
        self._defaults: Tuple[str, ...] = ()
        self.reset(fields, defaults)

    # -- result --------------------------------------------------------

    @property
    def fields(self) -> Tuple[str, ...]:
        """The ticked keys in Priority order, then the keys no row offers."""
        return self._ticked + self._kept_aside

    @property
    def defaults(self) -> Optional[Tuple[str, ...]]:
        """The Default keys in Priority order, then the ones no ticked row shows; None without the column."""
        return ordered_defaults(self._ticked, self._defaults) if self._has_default_column else None

    def reset(self, fields: Sequence[str], defaults: Optional[Sequence[str]] = None) -> None:
        """Show `fields` ticked in their order (and `defaults` flagged), as if the grid were new.
        Emits nothing: the window decides whether a reset is an edit."""
        fields = tuple(fields)
        self._ticked = tuple(k for k in fields if k in self._offered)
        self._kept_aside = tuple(k for k in fields if k not in self._offered)
        self._defaults = tuple(defaults or ()) if self._has_default_column else ()
        for key, checkbox in self.checkboxes.items():
            blocked = checkbox.blockSignals(True)
            checkbox.setChecked(key in self._ticked)
            checkbox.blockSignals(blocked)
        self._sync_rows()

    # -- rows ------------------------------------------------------------

    def _add_cells(self, grid: QGridLayout, row: int, key: str) -> None:
        if self._add_extra_cells is not None:
            self._add_extra_cells(grid, row, key)
        if self._has_default_column:
            check = QCheckBox()
            check.setToolTip(self._default_tooltip)
            check.toggled.connect(lambda on, k=key: self._on_default_toggled(k, on))
            self.default_checks[key] = check
            grid.addWidget(check, row, self._default_column_index, alignment=Qt.AlignmentFlag.AlignCenter)

    def _on_toggled(self, key: str, on: bool) -> None:
        self._ticked = with_key(self._ticked, key, on)
        if not on:
            self._defaults = with_default(self._defaults, self._ticked, key, False)
        self._edited()

    def _on_nudge(self, key: str, delta: int) -> None:
        moved = move_key(self._ticked, key, delta)
        if moved != self._ticked:
            self._ticked = moved
            self._edited()

    def _on_order_typed(self, key: str) -> None:
        if key in self._ticked:
            self._ticked = with_key_order(self._ticked, key, self.order_spins[key].value())
            self._edited()

    def _on_default_toggled(self, key: str, on: bool) -> None:
        self._defaults = with_default(self._defaults, self._ticked, key, on)

    def _edited(self) -> None:
        self._sync_rows()
        self.changed.emit()

    def _sync_rows(self) -> None:
        """Every row's Priority cell and Default box from the ticked keys -- an edit anywhere
        renumbers the whole order, so all rows follow."""
        for key in self.checkboxes:
            on = key in self._ticked
            for widget in (self.order_spins[key], self.up_buttons[key], self.down_buttons[key]):
                widget.setEnabled(on)
            spin = self.order_spins[key]
            blocked = spin.blockSignals(True)
            spin.setValue(self._ticked.index(key) + 1 if on else 1)
            spin.blockSignals(blocked)
        for key, check in self.default_checks.items():
            on = key in self._ticked
            check.setEnabled(on)
            blocked = check.blockSignals(True)
            check.setChecked(on and key in self._defaults)
            check.blockSignals(blocked)
