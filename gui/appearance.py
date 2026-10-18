"""
The application Theme and Graph theme chosen in Settings, set once at startup.

`main.py` reads both from the Settings store before it builds the window and
hands them to `set_appearance`; a changed choice applies after restart (ADR
§1.158, §1.165). Until then the look is the default Dark, which is what a test
sees unless it sets another one.

`APP_TOKENS` and `GRAPH_TOKENS` stand in for the tokens set last, so a module may
import them before `set_appearance` runs. Read a token where it is used, never into
a module constant. `THEME` is rebound, so it is read as `appearance.THEME`.
"""

from PySide6.QtCore import Qt

from core.theme import (
    Theme, app_tokens, graph_tokens, resolve_graph_look, resolve_graph_theme, resolve_theme,
)

__all__ = ["APP_TOKENS", "GRAPH_TOKENS", "THEME", "apply_theme", "set_appearance"]


class _CurrentTokens:
    """Reads every token from the tokens `set_appearance` set last (attributes only, not ==)."""

    def __init__(self, tokens):
        self._tokens = tokens

    def __getattr__(self, name):
        return getattr(self._tokens, name)


THEME = Theme.DARK
APP_TOKENS = _CurrentTokens(app_tokens(THEME))
GRAPH_TOKENS = _CurrentTokens(graph_tokens(resolve_graph_look(THEME, resolve_graph_theme(None))))


def set_appearance(theme: object, graph_theme: object) -> None:
    """Draw with the stored Theme and Graph theme; an unreadable value means its default."""
    global THEME
    THEME = resolve_theme(theme)
    APP_TOKENS._tokens = app_tokens(THEME)
    GRAPH_TOKENS._tokens = graph_tokens(resolve_graph_look(THEME, resolve_graph_theme(graph_theme)))


def apply_theme(style_hints, theme) -> None:
    """Apply the saved Theme, keeping Spectra independent of the operating-system theme."""
    scheme = Qt.ColorScheme.Light if theme is Theme.LIGHT else Qt.ColorScheme.Dark
    style_hints.setColorScheme(scheme)
