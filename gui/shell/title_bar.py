# =====================================================================
# FILE: gui/shell/title_bar.py
# =====================================================================
"""
The widgets that sit on the frameless window's top strip.

They carry no application state: WindowControls drives whatever window it is
parented into, and the brand/title text is pushed in from outside (the one
builder is core.app_metadata.window_title). Kept here, next to
FramelessWindow, because the two are only ever used together.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QLabel, QTabBar, QToolButton


# Segoe MDL2 Assets glyphs -- the same font the OS caption buttons use.
_GLYPH_MIN = ""
_GLYPH_MAX = ""
_GLYPH_RESTORE = ""
_GLYPH_CLOSE = ""

_BUTTON_QSS = """
QToolButton {
    border: none;
    background: transparent;
    font-family: 'Segoe MDL2 Assets';
    font-size: 10px;
    color: palette(window-text);
}
QToolButton:hover { background: rgba(128, 128, 128, 60); }
QToolButton#closeButton:hover { background: #c42b1c; color: white; }
"""


class DraggableTabBar(QTabBar):
    """Tab bar that lives in the title strip: a click selects a tab, a drag past
    the system drag distance hands over to the OS window move (which also
    restores a maximised window), like Chrome/Edge tabs."""

    def mousePressEvent(self, event):
        self._press = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        press = getattr(self, "_press", None)
        if press is not None and (event.buttons() & Qt.LeftButton) and (
                (event.position().toPoint() - press).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press = None
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)


class WindowControls(QWidget):
    """Minimise / maximise-restore / close, wired to the top-level window."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(_BUTTON_QSS)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._btn_min = self._make_button(_GLYPH_MIN, self._on_minimise)
        self._btn_max = self._make_button(_GLYPH_MAX, self._on_max_restore)
        self._btn_close = self._make_button(_GLYPH_CLOSE, self._on_close)
        self._btn_close.setObjectName("closeButton")

        for btn in (self._btn_min, self._btn_max, self._btn_close):
            layout.addWidget(btn)

    def _make_button(self, glyph: str, slot) -> QToolButton:
        btn = QToolButton(self)
        btn.setText(glyph)
        btn.setFixedSize(QSize(46, 28))
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(slot)
        return btn

    # -- reacting to state changes ---------------------------------------

    def sync_maximised(self, is_maximised: bool) -> None:
        self._btn_max.setText(_GLYPH_RESTORE if is_maximised else _GLYPH_MAX)

    # -- handlers -------------------------------------------------------

    def _on_minimise(self) -> None:
        self.window().showMinimized()

    def _on_max_restore(self) -> None:
        win = self.window()
        # Prefer the frameless base's own toggle so there is one code path.
        toggle = getattr(win, "toggle_max_restore", None)
        if callable(toggle):
            toggle()
        else:
            win.showNormal() if win.isMaximized() else win.showMaximized()

    def _on_close(self) -> None:
        self.window().close()


class TitleStrip(QWidget):
    """The window's one top row: left-aligned widgets, the window controls on
    the right, and `title` centred on the whole strip (not in the layout, so
    the left block's width never pushes it). Long text is elided to the free
    space between the left block and the controls."""

    def __init__(self, left: list[QWidget], controls: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 0, 0, 0)
        row.setSpacing(6)
        for widget in left:
            row.addWidget(widget)
        row.addStretch(1)
        row.addWidget(controls)
        self._left_end = left[-1]
        self._controls = controls
        self._text = ""
        self.title = QLabel(self)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet("color: palette(window-text);")

    def set_title(self, text: str) -> None:
        self._text = text
        self.title.setToolTip(text)
        self._place_title()

    def _place_title(self) -> None:
        left = self._left_end.geometry().right() + 12
        right = self._controls.geometry().left() - 12
        avail = max(0, right - left)
        fm = self.title.fontMetrics()
        width = min(fm.horizontalAdvance(self._text) + 4, avail)
        x = min(max((self.width() - width) // 2, left), max(left, right - width))
        self.title.setText(fm.elidedText(self._text, Qt.ElideRight, width))
        self.title.setGeometry(x, 0, width, self.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_title()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._place_title()
