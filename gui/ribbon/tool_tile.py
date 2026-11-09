# gui/ribbon/tool_tile.py
"""
The Tools tab's tile: one large square switch (glyph above a caption) with up to
three small round buttons in a row along its bottom, on fixed places -- left,
middle and right. Every switch is visibly lit when on.

The Cursor is its first use (`gui/ribbon/cursor_box.py`); a tile that needs only
two small buttons leaves the middle place empty, so the same button sits on the
same place on every tile.
"""

from enum import Enum

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QToolButton

from gui.appearance import APP_TOKENS
from gui.ribbon.icons import ribbon_icon

_SIZE = 92
_CHIP = 24
_CHIP_ROW_Y = 64
_GLYPH = 32


class ChipPosition(Enum):
    """The three fixed places of a small button along the tile's bottom."""

    LEFT = 0
    MIDDLE = 1
    RIGHT = 2


def _main_qss() -> str:
    return (
        f"QToolButton {{ background: {APP_TOKENS.cursor_background}; border: 2px solid {APP_TOKENS.cursor_border}; border-radius: 10px; }}"
        f"QToolButton:hover {{ border-color: {APP_TOKENS.cursor_accent}; }}"
        f"QToolButton:checked {{ background: {APP_TOKENS.cursor_checked}; border: 2px solid {APP_TOKENS.cursor_accent}; }}"
    )


def _chip_qss() -> str:
    return (
        f"QToolButton {{ background-color: {APP_TOKENS.cursor_chip_background}; border: 1px solid {APP_TOKENS.cursor_chip_border};"
        f"  border-radius: {_CHIP // 2}px; padding: 0; }}"
        f"QToolButton:hover {{ background-color: {APP_TOKENS.cursor_chip_hover}; }}"
        f"QToolButton:checked {{ background-color: {APP_TOKENS.cursor_chip_checked}; border: 1px solid {APP_TOKENS.cursor_chip_checked_border}; }}"
        f"QToolButton:disabled {{ background-color: {APP_TOKENS.cursor_chip_disabled}; border: 1px solid {APP_TOKENS.cursor_chip_disabled_border}; }}"
    )


def _lit_icon(name: str, px: int = 16) -> QIcon:
    """Grey glyph when off, white when on (the checked small button is filled)."""
    icon = QIcon()
    icon.addPixmap(ribbon_icon(name, size=px).pixmap(px, px), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(ribbon_icon(name, on_accent=True, size=px).pixmap(px, px),
                   QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(ribbon_icon(name, size=px).pixmap(px, px), QIcon.Mode.Disabled)
    return icon


def _chip_x(position: ChipPosition) -> int:
    gap = (_SIZE - 8 - 3 * _CHIP) // 2
    return 4 + position.value * (_CHIP + gap)


class ToolTile(QToolButton):
    """A checkable tile: `icon` glyph, `label` caption, small buttons via `add_chip`."""

    def __init__(self, icon: str, label: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(_SIZE, _SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_main_qss())
        self.setToolTip(tooltip)

        # Glyph and caption are mouse-transparent labels so the whole face toggles the tile.
        self._glyph = _lit_icon(icon, _GLYPH)
        self._icon = QLabel(self)
        self._icon.setGeometry(_SIZE // 2 - _GLYPH // 2, 4, _GLYPH, _GLYPH)
        self._text = QLabel(label, self)
        self._text.setGeometry(0, 38, _SIZE, 18)
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for item in (self._icon, self._text):
            item.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._chips: dict[ChipPosition, QToolButton] = {}
        self.toggled.connect(self._restyle)
        self._restyle(False)

    @property
    def label(self) -> str:
        return self._text.text()

    def chip(self, position: ChipPosition) -> QToolButton | None:
        """The small button on `position`, or None while that place is empty."""
        return self._chips.get(position)

    def add_chip(self, position: ChipPosition, icon: str, tooltip: str, *,
                 checkable: bool, only_while_on: bool = False) -> QToolButton:
        """Put a small button on `position`; `only_while_on` greys it out while the tile is off."""
        if position in self._chips:
            raise ValueError(f"tile {self.label!r} already has a button on {position.name}")
        button = QToolButton(self)
        button.setCheckable(checkable)
        button.setFixedSize(_CHIP, _CHIP)
        button.setIcon(_lit_icon(icon, 14))
        button.setIconSize(QSize(14, 14))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(_chip_qss())
        button.setToolTip(tooltip)
        button.move(_chip_x(position), _CHIP_ROW_Y)
        if only_while_on:
            button.setEnabled(self.isChecked())
            self.toggled.connect(button.setEnabled)
        self._chips[position] = button
        return button

    def _restyle(self, on: bool) -> None:
        state = QIcon.State.On if on else QIcon.State.Off
        self._icon.setPixmap(self._glyph.pixmap(_GLYPH, _GLYPH, QIcon.Mode.Normal, state))
        self._text.setStyleSheet(
            f"background: transparent; font-weight: bold; font-size: 12px;"
            f" color: {APP_TOKENS.cursor_text_on if on else APP_TOKENS.cursor_text_off};")
