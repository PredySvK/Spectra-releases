"""
view_models.tab_label -- short Tab labels and tooltips for graph tabs.

Architecture:
- View-model floor (Floor 3): Pure Python, Qt-free logic for resolving graph tab labels
  and tooltips from an analysis kind, sources, dead links, and optional custom labels.
- Deduplication: file + channel pairs counted once, result-set curves counted once.
- Tab width: capped at ~25 characters with ellipsis (…).
"""

from ._tab_label import (
    MAX_TAB_LABEL_LENGTH,
    TabLabel,
    TabSource,
    build_tab_label,
    build_tab_source,
)
from ._tab_search import (
    TabSearchEntry,
    filter_tab_entries,
)

__all__ = [
    "MAX_TAB_LABEL_LENGTH",
    "TabLabel",
    "TabSource",
    "build_tab_label",
    "build_tab_source",
    "TabSearchEntry",
    "filter_tab_entries",
]
