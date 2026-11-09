# gui/dialogs/dialog_state.py
"""
Remember a dialog's size (and position) between openings and between application
restarts; a dialog always opens on the monitor Spectra's window is on.

Lives in gui/ because it is pure Qt window-state glue. The geometry is stored in
the per-window QSettings group (Root/Spawns) under the ``dialog_geometry_``
prefix, alongside dock layout state -- it describes *where a window sits*, not
how the DSP is configured, so both "Reset Layout" and "Reset All Settings" clear
it (gui/handlers/window_settings.py asks ``is_dialog_geometry_key``).

Usage:

    from gui.dialogs.dialog_state import remember_dialog_geometry

    class MyDialog(QDialog):
        def __init__(self, ..., settings=None, parent=None):
            super().__init__(parent)
            ...
            remember_dialog_geometry(self, settings, "my_dialog", default_size=(800, 600))

``settings`` may be None (tests construct dialogs without an AppContext) -- the
helper then only applies the default size and never tries to persist.
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QRect, QSettings

_PREFIX = "dialog_geometry_"


def is_dialog_geometry_key(key: str) -> bool:
    """Whether a QSettings key is a remembered dialog geometry (what Reset Layout removes)."""
    return key.startswith(_PREFIX)


def fit_width_to_scroll_content(dialog, scroll, default_size: Tuple[int, int]) -> Tuple[int, int]:
    """
    Make the dialog at least as wide as the scroll area's content, so no
    horizontal scroll bar is needed. Sets the minimum width and returns
    ``default_size`` widened to it (capped to the screen) for
    ``remember_dialog_geometry``.
    """
    margins = dialog.layout().contentsMargins()
    needed = (scroll.widget().sizeHint().width() + 2 * scroll.frameWidth()
              + scroll.verticalScrollBar().sizeHint().width()
              + margins.left() + margins.right())
    screen = dialog.screen()
    if screen is not None:
        needed = min(needed, screen.availableGeometry().width())
    dialog.setMinimumWidth(needed)
    return max(default_size[0], needed), default_size[1]


def resolve_dialog_rect(rect: QRect, screen_area: QRect, parent_rect: QRect) -> QRect:
    """
    Where a restored dialog goes: ``rect`` as saved when its centre is on the
    parent window's screen (``screen_area``); otherwise centred over the parent,
    shrunk to fit that screen and kept inside it.
    """
    if screen_area.contains(rect.center()):
        return rect
    moved = QRect(QPoint(0, 0), rect.size().boundedTo(screen_area.size()))
    moved.moveCenter(parent_rect.center())
    moved.moveLeft(max(screen_area.left(), min(moved.left(), screen_area.right() - moved.width() + 1)))
    moved.moveTop(max(screen_area.top(), min(moved.top(), screen_area.bottom() - moved.height() + 1)))
    return moved


def _keep_on_parent_screen(dialog) -> None:
    """Moves a restored dialog onto its parent window's monitor (e.g. Spectra was moved meanwhile)."""
    parent = dialog.parentWidget()
    if parent is None:
        return
    window = parent.window()
    screen = window.screen()
    if screen is None:
        return
    dialog.setGeometry(resolve_dialog_rect(dialog.geometry(), screen.availableGeometry(), window.geometry()))


def remember_dialog_geometry(
    dialog,
    settings: Optional[QSettings],
    key: str,
    default_size: Optional[Tuple[int, int]] = None,
) -> None:
    """
    Restore the dialog's saved geometry now, and save it again whenever the
    dialog finishes (accept, reject or the window's close button -- QDialog
    routes all three through ``finished``). A saved position on another monitor
    than the parent window's is moved onto the parent's (`resolve_dialog_rect`).
    """
    storage_key = _PREFIX + key

    saved = settings.value(storage_key) if settings is not None else None
    if saved is not None:
        dialog.restoreGeometry(saved)
        _keep_on_parent_screen(dialog)
    elif default_size is not None:
        dialog.resize(*default_size)

    if settings is not None:
        dialog.finished.connect(
            lambda _result, d=dialog: settings.setValue(storage_key, d.saveGeometry())
        )
