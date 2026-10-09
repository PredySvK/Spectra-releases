"""Links inside Help pages and the tab contexts that open Help."""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote, urlsplit

from io_modules.help import read_help_toc

from ._toc import build_help_topic_ids


@dataclass(frozen=True)
class HelpLink:
    kind: Literal["topic", "external", "other"]
    topic_id: str = ""
    fragment: str = ""
    url: str = ""


def resolve_help_link(url: str) -> HelpLink:
    """``topic:<id>[#heading]`` -> topic, http(s) -> external, anything else -> other."""
    parts = urlsplit(url)
    if parts.scheme == "topic":
        return HelpLink("topic", unquote(parts.netloc + parts.path), unquote(parts.fragment))
    if parts.scheme in ("http", "https"):
        return HelpLink("external", url=url)
    return HelpLink("other", url=url)


def resolve_help_topic(context: str, root: str | None = None) -> str:
    """Topic id for a tab context (``"1d_spectrum"``) or an id itself; the first
    topic of the manual when it is neither."""
    toc = read_help_toc(root)
    ids = build_help_topic_ids(root)
    if context in toc["contexts"]:
        return toc["contexts"][context]
    return context if context in ids else ids[0]
