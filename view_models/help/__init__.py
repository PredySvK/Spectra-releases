"""
view_models.help -- What the Help window shows, without Qt (Floor 3).

Builds the topic tree, a topic's page HTML (Markdown + KaTeX, heading anchors,
"translation missing" note), resolves ``topic:`` / external links and tab
contexts to topic ids, and reports per-language translation gaps.

What does NOT belong here: the window and the browser widget (gui/help), reading
files (io_modules/help).
"""

from ._gaps import build_help_gap_report
from ._links import HelpLink, resolve_help_link, resolve_help_topic
from ._page import HELP_MATH_RENDER_SCRIPT, HelpPage, build_help_body, build_help_page
from ._search import HelpSearchResult, build_help_search_results
from ._toc import build_help_topic_ids
from ._tree import HelpTreeEntry, build_help_tree

__all__ = [
    "HELP_MATH_RENDER_SCRIPT",
    "HelpLink",
    "HelpPage",
    "HelpSearchResult",
    "HelpTreeEntry",
    "build_help_body",
    "build_help_gap_report",
    "build_help_page",
    "build_help_search_results",
    "build_help_tree",
    "build_help_topic_ids",
    "resolve_help_link",
    "resolve_help_topic",
]
