# =====================================================================
# FILE: gui/shell/dock_separator.py
# =====================================================================
"""
DockSeparatorHighlight -- a visible line on a QMainWindow's dock separators
that lights up only once the mouse has rested on it.

The separators are the resize handles between the docks and the central
widget. Unstyled they are invisible; a plain `:hover` rule makes them flash
every time the mouse merely crosses one. So the hover colour is switched on
only after the cursor has stayed on a separator for `delay_ms`, and off again
as soon as it leaves.

QMainWindow keeps no public "which separator is hovered" state, but it puts a
split cursor on itself while the mouse is over one -- that cursor is what
this class watches.
"""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QMainWindow

_BASE_QSS = "QMainWindow::separator { background: palette(mid); width: 4px; height: 4px; }"
_LIT_QSS = _BASE_QSS + "QMainWindow::separator:hover { background: palette(highlight); }"
_SPLIT_CURSORS = (Qt.CursorShape.SplitHCursor, Qt.CursorShape.SplitVCursor)
_INSIDE_EVENTS = (QEvent.Type.HoverMove, QEvent.Type.HoverEnter)
_OUTSIDE_EVENTS = (QEvent.Type.HoverLeave, QEvent.Type.Leave)

DEFAULT_DELAY_MS = 250


class DockSeparatorHighlight(QObject):
    """Styles `window`'s dock separators and lights the hovered one after a dwell."""

    def __init__(self, window: QMainWindow, delay_ms: int = DEFAULT_DELAY_MS):
        super().__init__(window)
        self._window = window
        self._lit = False
        self._inside = False
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.setInterval(delay_ms)
        self._dwell.timeout.connect(self._light_if_still_on_separator)
        window.setStyleSheet(_BASE_QSS)
        window.installEventFilter(self)

    def is_lit(self) -> bool:
        return self._lit

    def eventFilter(self, watched, event):
        if watched is not self._window:
            return False
        if event.type() in _OUTSIDE_EVENTS:
            self._inside = False
            self._sync()
        elif event.type() in _INSIDE_EVENTS:
            self._inside = True
            # The filter runs before QMainWindow updates its cursor for this
            # move, so read the cursor once the event has been handled.
            QTimer.singleShot(0, self._sync)
        return False

    def _on_separator(self) -> bool:
        return self._inside and self._window.cursor().shape() in _SPLIT_CURSORS

    def _sync(self) -> None:
        if self._on_separator():
            if not self._lit and not self._dwell.isActive():
                self._dwell.start()
            return
        self._dwell.stop()
        self._set_lit(False)

    def _light_if_still_on_separator(self) -> None:
        if self._on_separator():
            self._set_lit(True)

    def _set_lit(self, lit: bool) -> None:
        if lit != self._lit:
            self._lit = lit
            self._window.setStyleSheet(_LIT_QSS if lit else _BASE_QSS)
