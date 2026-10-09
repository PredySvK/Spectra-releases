"""Search through Help topics in a given language."""

import re
from dataclasses import dataclass

from ._toc import build_help_topic_ids, resolve_help_markdown
from ._tree import build_help_title

_FIRST_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+.+?$", re.MULTILINE)


@dataclass(frozen=True)
class HelpSearchResult:
    topic_id: str
    title: str
    snippet: str = ""


def _build_snippet(text: str, query: str, max_length: int = 120) -> str:
    """Build a single-line snippet showing ``query`` in body context."""
    match = _FIRST_HEADING.search(text)
    body = text[match.end():] if match else text

    pos = body.lower().find(query.lower())
    if pos < 0:
        for term in query.lower().split():
            pos = body.lower().find(term)
            if pos >= 0:
                break
    if pos < 0:
        return ""

    line_start = body.rfind("\n", 0, pos) + 1
    line_end = body.find("\n", pos)
    if line_end < 0:
        line_end = len(body)
    line = body[line_start:line_end].strip()
    line = re.sub(r"^#{1,6}\s*", "", line).strip()
    if len(line) <= max_length:
        return line
    rel_pos = max(0, pos - line_start)
    start = max(0, rel_pos - 40)
    end = min(len(line), start + max_length)
    snippet = line[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(line):
        snippet = snippet + "…"
    return snippet


def build_help_search_results(
    query: str,
    language: str,
    root: str | None = None,
) -> tuple[HelpSearchResult, ...]:
    """Search topics in ``language`` (falling back to English for untranslated pages).

    Returns matching topics ordered with title matches first, preserving
    table-of-contents order within each tier.
    """
    cleaned = query.strip()
    if not cleaned:
        return ()

    terms = [term.lower() for term in cleaned.split()]
    title_matches: list[HelpSearchResult] = []
    body_matches: list[HelpSearchResult] = []

    for topic_id in build_help_topic_ids(root):
        markdown, _ = resolve_help_markdown(topic_id, language, root)
        if markdown is None:
            continue

        title = build_help_title(markdown, topic_id)
        title_lower = title.lower()
        topic_lower = topic_id.lower()
        body_lower = markdown.lower()
        corpus = f"{title_lower} {topic_lower} {body_lower}"

        if not all(term in corpus for term in terms):
            continue

        matches_title = all(term in title_lower or term in topic_lower for term in terms)
        snippet = _build_snippet(markdown, cleaned)
        result = HelpSearchResult(topic_id=topic_id, title=title, snippet=snippet)

        if matches_title:
            title_matches.append(result)
        else:
            body_matches.append(result)

    return tuple(title_matches + body_matches)

