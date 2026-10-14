"""
view_models.settings -- What the Settings window shows, without Qt (Floor 3).

The page tree as data (sections, pages, their fields), the breadcrumb above a
page and the draft: edits stay unapplied until Apply returns the changed values,
Revert returns to the last applied ones.

What does NOT belong here: the window and its widgets (gui/settings), writing the
values to AppContext/QSettings (gui/handlers/window_settings.py).
"""

from ._draft import SettingsDraft
from ._search import SettingsSearchResult, build_settings_search_results
from ._pages import SETTINGS_IMMEDIATE_KEYS, SETTINGS_PAGES, SETTINGS_PROJECT_KEYS, SettingsField, SettingsPage, build_settings_breadcrumb, resolve_settings_page

__all__ = [
    "SETTINGS_IMMEDIATE_KEYS",
    "SETTINGS_PAGES",
    "SETTINGS_PROJECT_KEYS",
    "SettingsDraft",
    "SettingsField",
    "SettingsPage",
    "SettingsSearchResult",
    "build_settings_breadcrumb",
    "build_settings_search_results",
    "resolve_settings_page",
]
