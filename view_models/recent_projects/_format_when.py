# =====================================================================
# FILE: view_models/recent_projects/_format_when.py
# =====================================================================
"""
Formatting helpers for recent projects.
"""

from __future__ import annotations

from datetime import datetime


def format_when(iso_utc: str) -> str:
    """A remembered timestamp shown in the viewer's local time, date only when older."""
    if not iso_utc:
        return ""
    try:
        moment = datetime.fromisoformat(iso_utc)
    except ValueError:
        return ""
    local = moment.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")
