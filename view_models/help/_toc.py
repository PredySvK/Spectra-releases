"""Shared lookups of the Help manual: table-of-contents walk and page-with-fallback."""

from io_modules.help import HELP_FALLBACK_LANGUAGE, read_help_page, read_help_toc


def _walk_help_topics(nodes: list):
    """Yield every node depth-first, parents before children."""
    for node in nodes:
        yield node
        yield from _walk_help_topics(node.get("children", []))


def build_help_topic_ids(root: str | None = None) -> list[str]:
    return [node["id"] for node in _walk_help_topics(read_help_toc(root)["topics"])]


def resolve_help_markdown(topic_id: str, language: str, root: str | None = None) -> tuple[str | None, bool]:
    """``(markdown, translated)``: the page in ``language``, else the English one
    (``translated=False``), else ``(None, False)``."""
    markdown = read_help_page(topic_id, language, root)
    if markdown is not None:
        return markdown, True
    return read_help_page(topic_id, HELP_FALLBACK_LANGUAGE, root), False
