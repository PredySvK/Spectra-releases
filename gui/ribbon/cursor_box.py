# gui/ribbon/cursor_box.py
"""
The Tools tab's one Cursor control: a single button (Cursor on/off) with three
small round buttons in a row along its bottom -- Cursor Settings (gear), Highlight
(flashlight) and Pin. Every switch is visibly lit when on.

Exposes the same `btn_*` names the Tools tab always had, so the workspace binds
them unchanged.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QToolButton

from gui.ribbon.icons import ribbon_icon

_SIZE = 92
_CHIP = 24
_ACCENT = "#2ec4b6"
_TEXT_OFF = "#8a9a9a"
_TEXT_ON = "#e8fffd"

_MAIN_QSS = (
    "QToolButton { background: #2e3436; border: 2px solid #444c4e; border-radius: 10px; }"
    f"QToolButton:hover {{ border-color: {_ACCENT}; }}"
    f"QToolButton:checked {{ background: #1f4a4a; border: 2px solid {_ACCENT}; }}"
)
_CHIP_QSS = (
    "QToolButton { background-color: rgba(255,255,255,20); border: 1px solid rgba(255,255,255,45);"
    f"  border-radius: {_CHIP // 2}px; padding: 0; }}"
    "QToolButton:hover { background-color: rgba(255,255,255,50); }"
    "QToolButton:checked { background-color: #1f9e92; border: 1px solid rgba(255,255,255,120); }"
    "QToolButton:disabled { background-color: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,20); }"
)


def _lit_icon(name: str, px: int = 16) -> QIcon:
    """Grey glyph when off, white when on (the checked corner button is filled)."""
    icon = QIcon()
    icon.addPixmap(ribbon_icon(name, size=px).pixmap(px, px), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(ribbon_icon(name, on_accent=True, size=px).pixmap(px, px),
                   QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(ribbon_icon(name, size=px).pixmap(px, px), QIcon.Mode.Disabled)
    return icon


def _corner_button(parent, icon: str, tooltip: str, *, checkable: bool) -> QToolButton:
    button = QToolButton(parent)
    button.setCheckable(checkable)
    button.setFixedSize(_CHIP, _CHIP)
    button.setIcon(_lit_icon(icon, 14))
    button.setIconSize(QSize(14, 14))
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(_CHIP_QSS)
    button.setToolTip(tooltip)
    return button


class CursorBox(QToolButton):
    """Cursor on/off; `btn_cursor_settings`, `btn_highlight` and `btn_cursor_pin` sit in its corners."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(_SIZE, _SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_MAIN_QSS)
        self.setToolTip(
            "Cursor on/off: hover a curve graph to read the nearest sample of the nearest curve "
            "in a box next to the mouse (shortcut: C while a graph has focus).\n"
            "Bottom row: Settings, Highlight, Pin.")

        # Glyph and caption are mouse-transparent labels so the whole face toggles the Cursor.
        self._glyph = _lit_icon("cursor-arrow", 32)
        self._icon = QLabel(self)
        self._icon.setGeometry(_SIZE // 2 - 16, 4, 32, 32)
        self._text = QLabel("Cursor", self)
        self._text.setGeometry(0, 38, _SIZE, 18)
        self._text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for label in (self._icon, self._text):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.toggled.connect(self._restyle)
        self._restyle(False)

        self.btn_cursor_settings = _corner_button(
            self, "gear", "Cursor Settings…: choose which fields the Cursor Box shows and in "
                          "what order (saved for every project)", checkable=False)
        self.btn_highlight = _corner_button(
            self, "flashlight", "Highlight: emphasise the curve under the mouse and dim the "
                                "others (shortcut: H while a graph has focus)", checkable=True)
        self.btn_cursor_pin = _corner_button(
            self, "pin", "Pin: keep the Cursor Box where it is while its content follows the "
                         "mouse; drag the box to move it (shortcut: P while a graph has focus)",
            checkable=True)
        self.setObjectName("CursorButton")  # object names: targets of the help figure annotations
        self.btn_cursor_settings.setObjectName("CursorSettingsButton")
        self.btn_highlight.setObjectName("HighlightButton")
        self.btn_cursor_pin.setObjectName("CursorPinButton")
        gap = (_SIZE - 8 - 3 * _CHIP) // 2
        for i, chip in enumerate((self.btn_cursor_settings, self.btn_highlight, self.btn_cursor_pin)):
            chip.move(4 + i * (_CHIP + gap), 64)

        # Pin only means something while the Cursor is on.
        self.btn_cursor_pin.setEnabled(False)
        self.toggled.connect(self.btn_cursor_pin.setEnabled)

    def _restyle(self, on: bool) -> None:
        state = QIcon.State.On if on else QIcon.State.Off
        self._icon.setPixmap(self._glyph.pixmap(32, 32, QIcon.Mode.Normal, state))
        self._text.setStyleSheet(
            f"background: transparent; font-weight: bold; font-size: 12px;"
            f" color: {_TEXT_ON if on else _TEXT_OFF};")
