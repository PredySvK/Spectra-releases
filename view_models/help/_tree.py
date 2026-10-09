"""The topic tree shown on the left of the Help window."""

import re
from dataclasses import dataclass

from io_modules.help import read_help_toc

from ._toc import resolve_help_markdown

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_LEADING_DECORATION = re.compile(r"^[^\w$]+")


@dataclass(frozen=True)
class HelpTreeEntry:
    topic_id: str
    title: str
    children: tuple["HelpTreeEntry", ...] = ()


def build_help_title(markdown: str, topic_id: str) -> str:
    """First heading of a page without leading emoji; the topic id if there is none."""
    match = _HEADING.search(markdown)
    return _LEADING_DECORATION.sub("", match.group(1)) if match else topic_id


def build_help_tree(language: str, root: str | None = None) -> tuple[HelpTreeEntry, ...]:
    """Tree in table-of-contents order; titles come from each page's heading,
    in ``language`` where translated, English otherwise."""
    def entry(node: dict) -> HelpTreeEntry:
        topic_id = node["id"]
        markdown = resolve_help_markdown(topic_id, language, root)[0] or ""
        return HelpTreeEntry(topic_id, build_help_title(markdown, topic_id),
                             tuple(entry(child) for child in node.get("children", [])))

    return tuple(entry(node) for node in read_help_toc(root)["topics"])
