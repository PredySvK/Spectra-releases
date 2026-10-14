"""Settings search: visible pages and matched text segments, without Qt."""

from dataclasses import dataclass
import re

from ._pages import SETTINGS_PAGES, build_settings_breadcrumb


@dataclass(frozen=True)
class SettingsSearchResult:
    """Segments are (text, highlighted); fields include matching choice labels."""

    page_id: str
    breadcrumb: tuple[tuple[str, bool], ...]
    field_matches: dict[str, tuple[tuple[str, bool], ...]]


def build_settings_search_results(query: str) -> tuple[SettingsSearchResult, ...]:
    """Match page paths and field text case-insensitively; blank restores all pages."""
    query = query.strip()
    pattern = re.compile(f"({re.escape(query)})", re.IGNORECASE) if query else None

    def build_segments(text: str) -> tuple[tuple[str, bool], ...]:
        if pattern is None:
            return ((text, False),)
        return tuple((part, i % 2 == 1) for i, part in enumerate(pattern.split(text)))

    results = []
    for page in SETTINGS_PAGES:
        breadcrumb = build_settings_breadcrumb(page)
        field_matches = {}
        if pattern is not None:
            for field in page.fields:
                texts = (field.label, field.description, field.note, field.group,
                         *(label for label, _value in field.choices))
                matched = tuple(text for text in texts if pattern.search(text))
                if matched:
                    field_matches[field.key] = build_segments(" · ".join(matched))
        if pattern is None or pattern.search(breadcrumb) or field_matches:
            results.append(SettingsSearchResult(page.page_id, build_segments(breadcrumb), field_matches))
    return tuple(results)
