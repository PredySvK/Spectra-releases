"""
view_models.settings -- What the Settings window shows, without Qt (Floor 3).

The page tree as data (sections, pages, their fields), the breadcrumb above a
page and the draft: edits stay unapplied until Apply returns the changed values,
Revert returns to the last applied ones. `build_about_lines` is the text of the
About page (app and format versions). A page may list ``rows`` (the Units page:
`UnitsRow`), and `resolve_units_row_preview` writes the sample number of one row.

What does NOT belong here: the window and its widgets (gui/settings), writing the
values (session/settings), what a change sets off (gui/handlers/window_settings.py).
"""

from ._about import build_about_lines
from ._draft import SettingsDraft
from ._search import SettingsSearchResult, build_settings_search_results
from ._pages import SETTINGS_FIELD_KEYS, SETTINGS_IMMEDIATE_KEYS, SETTINGS_PAGES, SETTINGS_PROJECT_KEYS, SettingsField, SettingsPage, UnitsRow, build_settings_breadcrumb, resolve_settings_page
from ._units_rows import resolve_units_row_preview

__all__ = [
    "SETTINGS_FIELD_KEYS",
    "SETTINGS_IMMEDIATE_KEYS",
    "SETTINGS_PAGES",
    "SETTINGS_PROJECT_KEYS",
    "SettingsDraft",
    "SettingsField",
    "SettingsPage",
    "SettingsSearchResult",
    "UnitsRow",
    "build_about_lines",
    "build_settings_breadcrumb",
    "build_settings_search_results",
    "resolve_settings_page",
    "resolve_units_row_preview",
]
