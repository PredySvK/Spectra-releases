"""Which topics exist, and which a language is still missing."""

from io_modules.help import read_help_languages, read_help_pages

from ._toc import build_help_topic_ids


def build_help_gap_report(root: str | None = None) -> dict[str, tuple[str, ...]]:
    """Per language: table-of-contents topics that have no page in that language."""
    ids = build_help_topic_ids(root)
    report = {}
    for language in read_help_languages(root):
        present = set(read_help_pages(language, root))
        report[language] = tuple(i for i in ids if i not in present)
    return report
