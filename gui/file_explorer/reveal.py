# gui/file_explorer/reveal.py
"""
Small OS-integration helpers shared by the two file panels: reveal a path in the
system file manager, and copy paths to the clipboard. Lives here because the Data
Pool and the File Browser are the only callers -- it is GUI glue, not I/O logic.
"""
import os
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication


def show_in_file_manager(path: str) -> None:
    """
    Open the OS file manager with ``path`` selected. Falls back to opening the
    containing folder when selection is not available (non-Windows, or the entry
    is already gone).
    """
    if not path:
        return

    normalized = os.path.normpath(path)
    if sys.platform == "win32" and os.path.exists(normalized):
        # explorer.exe hands the request to the running shell and exits at once,
        # so we wait for it here: a bare Popen left to be garbage-collected
        # prints "ResourceWarning: subprocess N is still running" once the child
        # outlives the object. explorer returns exit code 1 even on success, so
        # the result is ignored.
        subprocess.run(["explorer", f"/select,{normalized}"], check=False)
        return

    folder = normalized if os.path.isdir(normalized) else os.path.dirname(normalized)
    if folder:
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


def copy_paths_to_clipboard(paths) -> None:
    """Put one path per line onto the system clipboard."""
    text = "\n".join(p for p in paths if p)
    if text:
        QApplication.clipboard().setText(text)
