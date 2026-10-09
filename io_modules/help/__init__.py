"""
io_modules.help -- Reads the Help manual from ``resources/help/`` (Floor 4).

Layout: ``toc.json`` (topic tree + tab context -> topic id), ``<language>/<topic id>.md``
(one Markdown page per topic, a language is a folder), ``images/``, ``katex/``.

What does NOT belong here: turning Markdown into HTML or resolving links
(view_models/help), the window (gui/help).
"""

from ._reading import (
    HELP_FALLBACK_LANGUAGE,
    read_help_languages,
    read_help_page,
    read_help_pages,
    read_help_toc,
    resolve_help_resource_dir,
)

__all__ = [
    "HELP_FALLBACK_LANGUAGE",
    "read_help_languages",
    "read_help_page",
    "read_help_pages",
    "read_help_toc",
    "resolve_help_resource_dir",
]
