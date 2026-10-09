# =====================================================================
# FILE: view_models/recent_projects/__init__.py
# =====================================================================
"""
view_models.recent_projects -- Presentation helpers for recent projects, without Qt.

Architecture:
- View-model floor (Floor 3): How recent project records are formatted for display
  (e.g., timestamps in the viewer's local timezone), without Qt.
- Formatting: format_when converts ISO UTC timestamps to local datetime strings.

What does NOT belong here: Qt widgets or list items (gui/), recent project
persistence or disk I/O (core/ or session/).
"""

from ._format_when import format_when

__all__ = [
    "format_when",
]
