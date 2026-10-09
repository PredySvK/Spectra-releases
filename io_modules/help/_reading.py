"""Plain file reads of the Help manual. Small and user-initiated, so synchronous."""

import json
from pathlib import Path

from core.asset_paths import resource_path

HELP_FALLBACK_LANGUAGE = "en"


def resolve_help_resource_dir(root: str | None = None) -> Path:
    """Folder holding ``toc.json``, the language folders, ``images/`` and ``katex/``."""
    return Path(root) if root else Path(resource_path("resources", "help"))


def read_help_toc(root: str | None = None) -> dict:
    """``{"contexts": {tab context: topic id}, "topics": [{"id", "children"?}, ...]}``."""
    path = resolve_help_resource_dir(root) / "toc.json"
    return json.loads(path.read_text(encoding="utf-8"))


def read_help_languages(root: str | None = None) -> list[str]:
    """Language codes = folders with a Markdown tree (plus empty slots), English first."""
    base = resolve_help_resource_dir(root)
    found = [p.name for p in base.iterdir() if p.is_dir() and len(p.name) == 2]
    return sorted(found, key=lambda code: (code != HELP_FALLBACK_LANGUAGE, code))


def read_help_page(topic_id: str, language: str, root: str | None = None) -> str | None:
    """Markdown of one topic, ``None`` when that language has no such page."""
    path = resolve_help_resource_dir(root) / language / f"{topic_id}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def read_help_pages(language: str, root: str | None = None) -> list[str]:
    """Topic ids of every page that exists on disk for ``language``."""
    base = resolve_help_resource_dir(root) / language
    return sorted(p.relative_to(base).with_suffix("").as_posix() for p in base.rglob("*.md"))
