# =====================================================================
# FILE: gui/shell/frameless_window.py
# =====================================================================
"""
A borderless QMainWindow that still behaves like a real OS window:
8-direction resize, drag-to-move, Aero Snap, Win+Arrow tiling, double-click
maximise, a maximised state that stops at the taskbar, and the system drop
shadow.

Why in-repo and not a library: see ARCHITECTURE_DECISIONS.md, the frameless
shell section. The maintained packages pull a second Qt binding (PyQt5) as a
hard dependency; the part we actually need is the ~200 lines of Win32 below.

On Windows the standard-frame behaviour is kept alive at the Win32 level:
_init_native forces WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MIN/MAXIMIZEBOX
back onto the HWND (Qt's FramelessWindowHint strips them, which is what kills
snapping, the minimise/maximise animations, the maximise command itself, the
drop shadow and -- because a bare WS_POPUP has no system menu -- HTCAPTION
drag-to-move). WS_CAPTION does not resurrect the native title bar: painting it
would require DefWindowProc to reserve the caption strip in WM_NCCALCSIZE, and
that message never reaches it.

WM_NCCALCSIZE then deletes the frame entirely (client = whole window), and
WM_GETMINMAXINFO reports the maximised size/position as the work area of the
window's own monitor -- without it DefWindowProc sizes a maximised frameless
window to the monitor plus the frame width on every edge, which is where the
window spilling onto the next display and the white band over the taskbar came
from. Both read MONITORINFO per-monitor, which is what makes them correct on a
mixed-DPI multi-monitor setup. WM_NCHITTEST re-derives the resize edges and
reports the registered drag areas as caption. The shadow comes for free from
WS_THICKFRAME, so no DWM frame extension is needed (the old 1px MARGINS
extension was the white hairline around the restored window).

Anything that asks "are we maximised?" from inside a native message handler
uses Win32 IsZoomed, never Qt's isMaximized(): mid-transition (Win+Arrow,
restore-down) Qt still reports the state the window is leaving.

Off Windows this degrades to a plain frameless window with drag-to-move via
QWindow.startSystemMove(); that path is best-effort only (the product target
is Windows 11).
"""

from __future__ import annotations

import sys
from typing import Callable, Optional

from PySide6.QtCore import Qt, QPoint, QByteArray, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QMainWindow, QApplication, QWidget

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", _RECT * 3), ("lppos", ctypes.c_void_p)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]

    class _MINMAXINFO(ctypes.Structure):
        _fields_ = [("ptReserved", wintypes.POINT),
                    ("ptMaxSize", wintypes.POINT),
                    ("ptMaxPosition", wintypes.POINT),
                    ("ptMinTrackSize", wintypes.POINT),
                    ("ptMaxTrackSize", wintypes.POINT)]

    _user32 = ctypes.windll.user32
    # Pointer-wide return values: the default c_int restype truncates a HANDLE
    # or a LONG_PTR on 64-bit and hands back a garbage value.
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [
        wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.MonitorFromWindow.restype = wintypes.HMONITOR
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    _user32.IsZoomed.restype = wintypes.BOOL
    _user32.IsZoomed.argtypes = [wintypes.HWND]
    _user32.SendMessageW.restype = ctypes.c_ssize_t
    _user32.SendMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]

    def _monitor_info(hwnd) -> Optional["_MONITORINFO"]:
        """MONITORINFO of the display the window sits on, or None. NEAREST so a
        window dragged half off-screen still resolves to the display it mostly
        covers."""
        hmon = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        if not hmon:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return None
        return info

# Win32 message / hit-test constants (winuser.h).
_WM_GETMINMAXINFO = 0x0024
_WM_NCCALCSIZE = 0x0083
_WM_NCHITTEST = 0x0084
_WM_SYSCOMMAND = 0x0112
# Caption drag is deliberately NOT intercepted here: with WS_CAPTION | WS_SYSMENU
# on the HWND, DefWindowProc runs the move loop itself off the HTCAPTION that
# WM_NCHITTEST reports -- edge snapping included. An earlier round answered
# WM_NCLBUTTONDOWN with ReleaseCapture + SC_MOVE instead. While the styles were
# missing that did nothing, and once they were back it was what suppressed the
# drag: returning "handled" is exactly what keeps the message from DefWindowProc.
_SC_MAXIMIZE = 0xF030
_SC_RESTORE = 0xF120

_GWL_STYLE = -16
# WS_CAPTION is what Windows looks for before it animates a minimise/maximise
# and before DefWindowProc will act on SC_MAXIMIZE at all -- without it the
# maximise button was inert and every state change snapped instantly. It does
# NOT bring the native title bar back here: DefWindowProc would have to reserve
# the caption strip in WM_NCCALCSIZE, and that message never reaches it (we
# answer it ourselves with client == whole window). The second bar an earlier
# round saw came from DwmExtendFrameIntoClientArea, which is gone.
# WS_THICKFRAME buys the shadow / Aero Snap / resize, WS_SYSMENU makes the
# HTCAPTION move loop and the min/max boxes work.
_WS_CAPTION = 0x00C00000
_WS_THICKFRAME = 0x00040000
_WS_SYSMENU = 0x00080000
_WS_MAXIMIZEBOX = 0x00010000
_WS_MINIMIZEBOX = 0x00020000

_MONITOR_DEFAULTTONEAREST = 0x00000002

_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020

_HTCLIENT = 1
_HTCAPTION = 2
_HT_EDGES = {
    (True, False, True, False): 13,   # top-left     HTTOPLEFT
    (True, False, False, True): 14,   # top-right    HTTOPRIGHT
    (False, True, True, False): 16,   # bottom-left  HTBOTTOMLEFT
    (False, True, False, True): 17,   # bottom-right HTBOTTOMRIGHT
    (False, False, True, False): 10,  # left         HTLEFT
    (False, False, False, True): 11,  # right        HTRIGHT
    (True, False, False, False): 12,  # top          HTTOP
    (False, True, False, False): 15,  # bottom       HTBOTTOM
}


class _DragArea:
    """A widget whose empty space counts as window caption, plus an optional
    predicate that vetoes specific local points (e.g. the tab labels of a
    QTabBar, which must stay clickable)."""

    def __init__(self, widget: QWidget, veto: Optional[Callable[[QPoint], bool]]):
        self.widget = widget
        self.veto = veto

    def covers(self, global_pos: QPoint) -> bool:
        w = self.widget
        if not w.isVisible():
            return False
        local = w.mapFromGlobal(global_pos)
        if not w.rect().contains(local):
            return False
        if self.veto is not None and self.veto(local):
            return False
        # A point sitting on an interactive child (button, combo) is that
        # child's, not the caption's.
        child = w.childAt(local)
        return child is None or child is w


class FramelessWindow(QMainWindow):
    """QMainWindow with the OS frame removed but its behaviour retained."""

    #: emitted whenever the maximised/normal state changes, so a custom title
    #: bar can swap its maximise/restore glyph.
    maximised_changed = Signal(bool)

    #: logical-pixel grab band for the resize edges.
    RESIZE_BORDER = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_areas: list[_DragArea] = []
        self._native_ready = False

        flags = self.windowFlags() | Qt.FramelessWindowHint
        if _IS_WINDOWS:
            flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        self.setWindowFlags(flags)

    # -- public API ---------------------------------------------------------

    def register_drag_area(
        self, widget: QWidget, veto: Optional[Callable[[QPoint], bool]] = None
    ) -> None:
        """Mark ``widget``'s empty space as draggable window caption. ``veto``
        receives a widget-local QPoint and returns True for points that must
        NOT drag (kept interactive)."""
        self._drag_areas.append(_DragArea(widget, veto))

    def toggle_max_restore(self) -> None:
        if _IS_WINDOWS and self._native_ready:
            # The system menu command, not showMaximized(): DefWindowProc then
            # runs the real maximise/restore -- animation included -- and reads
            # the current state off the HWND, where Qt's cached window state can
            # still be the one the window is leaving.
            hwnd = int(self.winId())
            command = _SC_RESTORE if _user32.IsZoomed(hwnd) else _SC_MAXIMIZE
            _user32.SendMessageW(hwnd, _WM_SYSCOMMAND, command, 0)
            return
        self.showNormal() if self.isMaximized() else self.showMaximized()

    # -- Qt event hooks ----------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        if _IS_WINDOWS and not self._native_ready and not self._is_offscreen():
            self._init_native()

    def event(self, event):
        # Qt recreates the native window now and then (opening the owned Help
        # window does it); the new HWND has plain popup styles again, which
        # silently kills Aero Snap and drag-to-restore. Re-apply them.
        if event.type() == event.Type.WinIdChange and self._native_ready:
            self._init_native()
        return super().event(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            # IsZoomed, not Qt's isMaximized(): mid-transition (Win+Arrow,
            # restore-down) Qt still reports the state the window is leaving,
            # which would leave WindowControls showing the wrong max/restore
            # glyph. The rest of this file avoids isMaximized() for the same
            # reason.
            if _IS_WINDOWS and self._native_ready:
                maximised = bool(_user32.IsZoomed(int(self.winId())))
            else:
                maximised = self.isMaximized()
            self.maximised_changed.emit(maximised)

    def mousePressEvent(self, event: QMouseEvent):
        # The non-Windows drag path. On Windows the OS runs the move loop once
        # WM_NCHITTEST reports HTCAPTION, so this never needs to fire there.
        if not _IS_WINDOWS and event.button() == Qt.LeftButton \
                and self._point_is_caption(event.globalPosition().toPoint()):
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    # -- helpers ---------------------------------------------------------

    def _is_offscreen(self) -> bool:
        return QApplication.platformName() in ("offscreen", "minimal", "")

    def _point_is_caption(self, global_pos: QPoint) -> bool:
        return any(area.covers(global_pos) for area in self._drag_areas)

    def _dpr(self) -> float:
        handle = self.windowHandle()
        return handle.devicePixelRatio() if handle is not None else 1.0

    # -- Win32 --------------------------------------------------------------

    def _init_native(self) -> None:
        try:
            hwnd = int(self.winId())
            # Put the real frame styles back. WM_NCCALCSIZE still hides the
            # frame visually, but with these the OS again owns Aero Snap, the
            # min/max/restore animations, the drop shadow, and the HTCAPTION
            # move loop (a style-less WS_POPUP ignores HTCAPTION, which is why
            # drag-to-move did nothing before).
            style = _user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
            _user32.SetWindowLongPtrW(
                hwnd, _GWL_STYLE,
                style | _WS_CAPTION | _WS_THICKFRAME | _WS_SYSMENU
                | _WS_MAXIMIZEBOX | _WS_MINIMIZEBOX,
            )
            _user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER
                | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
            )
        except Exception:
            # A locked-down session: the window still works, it just loses the
            # native chrome behaviour.
            pass
        self._native_ready = True

    def nativeEvent(self, event_type: QByteArray, message):
        if not _IS_WINDOWS or bytes(event_type) != b"windows_generic_MSG":
            return super().nativeEvent(event_type, message)

        msg = wintypes.MSG.from_address(int(message))

        if msg.message == _WM_GETMINMAXINFO:
            if self._fill_min_max_info(msg.hWnd, msg.lParam):
                return True, 0

        if msg.message == _WM_NCCALCSIZE:
            if not msg.wParam:
                return True, 0
            params = _NCCALCSIZE_PARAMS.from_address(msg.lParam)
            # IsZoomed, not Qt's isMaximized(): while the OS is leaving the
            # maximised state (Win+Arrow snap, restore-down) it sends
            # WM_NCCALCSIZE for the NEW rect while Qt still reports the OLD
            # state. Clamping a half-width snapped window to the full work area
            # made Qt adopt a work-area-sized client and grow the window back
            # over the neighbouring monitor.
            if _user32.IsZoomed(msg.hWnd):
                # A maximised WS_THICKFRAME window's rect overhangs the monitor
                # by the frame width on every edge. Clamp the client straight
                # to the monitor work area instead of letting DefWindowProc do
                # it -- DefWindowProc also reserves a caption strip, and that
                # strip was the second bar above the ribbon. rcWork is
                # per-monitor, so this is correct on every display of a
                # mixed-DPI multi-monitor setup.
                info = _monitor_info(msg.hWnd)
                if info is not None:
                    r = info.rcWork
                    params.rgrc[0].left = r.left
                    params.rgrc[0].top = r.top
                    params.rgrc[0].right = r.right
                    params.rgrc[0].bottom = r.bottom
            # Normal state: client = whole window, no frame. WS_THICKFRAME still
            # gives the shadow / Aero Snap; resize edges come from _hit_test.
            return True, 0

        if msg.message == _WM_NCHITTEST:
            result = self._hit_test(msg.lParam)
            if result is not None:
                return True, result

        return super().nativeEvent(event_type, message)

    def _fill_min_max_info(self, hwnd, lparam: int) -> bool:
        """Tell Windows how big "maximised" is on THIS monitor.

        A frameless WS_THICKFRAME window gets this wrong on its own:
        DefWindowProc sizes a maximised window to the monitor *plus* the resize
        frame on every edge and positions it that far up and to the left, on the
        assumption that WM_NCCALCSIZE will eat the overhang. Ours does not (the
        client is the whole window), so the overhang stayed real -- the window
        spilled onto the neighbouring display, and the strip of frame below the
        work area showed as an unpainted band over the taskbar.

        Reporting the work area verbatim makes the maximised window rect equal
        the work area, per monitor, which is also what keeps it right on a
        mixed-DPI setup: MONITORINFO is in physical pixels, and so is MINMAXINFO.

        ptMaxTrackSize is deliberately left at the system default (the virtual
        screen) so a window can still be resized across several monitors by hand.
        """
        info = _monitor_info(hwnd)
        if info is None:
            return False
        work, mon = info.rcWork, info.rcMonitor
        mmi = _MINMAXINFO.from_address(lparam)
        mmi.ptMaxSize.x = work.right - work.left
        mmi.ptMaxSize.y = work.bottom - work.top
        # ptMaxPosition is relative to the monitor rect, not to the desktop.
        mmi.ptMaxPosition.x = work.left - mon.left
        mmi.ptMaxPosition.y = work.top - mon.top

        # Handling the message ourselves skips Qt's own WM_GETMINMAXINFO
        # handler, so the window's minimum size has to be re-applied here or the
        # user could drag the window smaller than its layout allows.
        handle = self.windowHandle()
        if handle is not None:
            dpr = self._dpr()
            minimum = handle.minimumSize()
            if minimum.width() > 0:
                mmi.ptMinTrackSize.x = max(
                    mmi.ptMinTrackSize.x, round(minimum.width() * dpr))
            if minimum.height() > 0:
                mmi.ptMinTrackSize.y = max(
                    mmi.ptMinTrackSize.y, round(minimum.height() * dpr))
        return True

    def _hit_test(self, lparam: int) -> Optional[int]:
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value

        rect = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(int(self.winId()), ctypes.byref(rect)):
            return None

        w, h = rect.right - rect.left, rect.bottom - rect.top
        lx, ly = x - rect.left, y - rect.top
        border = round(self.RESIZE_BORDER * self._dpr())

        if not _user32.IsZoomed(int(self.winId())):
            edges = (
                ly < border, ly >= h - border,     # top, bottom
                lx < border, lx >= w - border,     # left, right
            )
            hit = _HT_EDGES.get(edges)
            if hit is not None:
                return hit

        # QCursor.pos(), not the lParam point: Qt has already converted the very
        # same position into its own logical global space, DPI and per-screen
        # origins included. Deriving it here instead means picking one of two
        # broken conversions -- dividing an absolute screen coordinate by this
        # window's ratio is wrong on every other monitor of a mixed-DPI desktop,
        # and mapping a window-rect offset through mapToGlobal() is wrong by
        # whatever frame Qt believes the window has (which is zero while
        # maximised and not zero otherwise -- that asymmetry was the bug where
        # only a maximised window could be dragged).
        if self._point_is_caption(QCursor.pos()):
            return _HTCAPTION

        return _HTCLIENT
