"""
gui.help -- The Help window (Floor 1): one non-modal window with the topic tree,
the page (web view + offline KaTeX) and the language selector. Every Help button
calls ``show_help`` with its tab context and lands on its topic in that one window.

What does NOT belong here: Markdown/HTML building and link rules (view_models/help),
reading the manual from disk (io_modules/help).
"""

from ._window import HelpWindow, close_help, show_help, show_help_at_startup

__all__ = [
    "HelpWindow",
    "close_help",
    "show_help",
    "show_help_at_startup",
]
