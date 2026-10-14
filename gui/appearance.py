"""
The application Theme and Graph theme chosen in Settings, read once when the GUI loads.

The one place the GUI reads them: `THEME`, `APP_TOKENS` and `GRAPH_TOKENS` are
fixed for the process, and a changed choice applies after restart.
`AppContext` keeps the saved choice the Settings window edits.
"""

from PySide6.QtCore import QSettings

from core.app_metadata import SETTINGS_ORGANIZATION, SETTINGS_SHARED
from core.theme import app_tokens, graph_tokens, resolve_graph_look, resolve_graph_theme, resolve_theme

_SAVED = QSettings(SETTINGS_ORGANIZATION, SETTINGS_SHARED)
THEME = resolve_theme(_SAVED.value("theme"))
APP_TOKENS = app_tokens(THEME)
GRAPH_TOKENS = graph_tokens(resolve_graph_look(THEME, resolve_graph_theme(_SAVED.value("graph_theme"))))
del _SAVED
