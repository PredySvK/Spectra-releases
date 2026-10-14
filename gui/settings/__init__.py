"""
gui.settings -- The Settings window (Floor 1): non-modal, opened by the gear in the
title strip. Page tree, breadcrumb and the page's fields; Apply · Revert · Close.

What does NOT belong here: which pages and fields exist and the draft rules
(view_models/settings), writing the values (gui/handlers/window_settings.py).
"""

from ._window import SettingsWindow

__all__ = ["SettingsWindow"]
