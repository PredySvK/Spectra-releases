# =====================================================================
# FILE: gui/shell/__init__.py
# =====================================================================
"""
The window chrome layer: a frameless QMainWindow base and the widgets that
draw the title strip on top of it, plus the visible dock separators.

Lives under gui/ (Qt is allowed here) but knows nothing about AppContext or
the project -- FramelessWindow is pure OS-window behaviour, and the title bar
widgets take their text and their handlers from whoever wires them.
"""

from gui.shell.dock_separator import DockSeparatorHighlight
from gui.shell.frameless_window import FramelessWindow
from gui.shell.title_bar import WindowControls

__all__ = ["DockSeparatorHighlight", "FramelessWindow", "WindowControls"]
