"""
Classification of a user-typed result-set name for the dialogs that ask for one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from io_modules.result_cache import sanitize_result_set_label

LabelKind = Literal["empty", "unusable", "changed", "unchanged"]


@dataclass(frozen=True)
class LabelPreview:
    """`clean` is the folder name the typed text becomes ("" for empty/unusable)."""

    kind: LabelKind
    clean: str


def build_label_preview(text: str) -> LabelPreview:
    """Classify `text` (stripped) against the folder-name sanitiser."""
    typed = text.strip()
    clean = sanitize_result_set_label(typed)
    if not typed:
        return LabelPreview("empty", "")
    if not clean:
        return LabelPreview("unusable", "")
    if clean != typed:
        return LabelPreview("changed", clean)
    return LabelPreview("unchanged", clean)
