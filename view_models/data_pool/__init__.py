# =====================================================================
# FILE: view_models/data_pool/__init__.py
# =====================================================================
"""
view_models.data_pool -- Data Pool presentation grouping, without Qt.

Architecture:
- View-model floor (Floor 3): How should Data Pool measurements be grouped and
  structured for tree display, given raw pool runs and setup labels, without Qt?
- Setup grouping: group_by_setup -- buckets pool runs under their test setup
  (setups first in the order they were defined, unassigned last).
- Schema conflict description: describe_schema_conflict -- formats folder
  disagreements about metadata fields into user-readable explanations with
  folder basenames.

What does NOT belong here: Qt widgets or tree items (gui/), deciding what
runs (orchestration/), what project is currently open (session/), which
curves or sources are filtered (selection/), or file I/O (io_modules/).
"""

from ._group_by_setup import UNASSIGNED_SETUP, group_by_setup
from ._schema_conflict import describe_schema_conflict

__all__ = [
    "UNASSIGNED_SETUP",
    "describe_schema_conflict",
    "group_by_setup",
]
