# =====================================================================
# FILE: view_models/data_pool/__init__.py
# =====================================================================
"""
view_models.data_pool -- the Data Pool tree and its texts, without Qt.

Architecture:
- View-model floor (Floor 3): What does the Data Pool tree show for a given
  pool -- which rows, in which order, with which text, tooltip and marker --
  without Qt?
- Data Pool tree: build_pool_tree -> PoolTree of PoolTreeNode (kinds NODE_*,
  markers MARKER_*): setups in the order they were defined with the
  UNASSIGNED_SETUP bucket last, their measurements, workbook sheets and
  channels, then folders holding Unreadable files. Each node carries a stable
  expansion key and the domain object it stands for.
- Measurement flags: MeasurementFlag, one report with a glyph and a text, derived
  from the run when the tree is built. A new kind is a new type in
  MEASUREMENT_FLAG_KINDS (PartiallyReadFlag and TachoInterpolationFlag are); drawing does not change.
- Search and Filter visibility: resolve_pool_tree_visibility ->
  PoolTreeVisibility, the keys of the nodes to hide and to open for a search
  text and the channels the Filter lets through; the tree is not rebuilt.
- Schema conflict description: describe_schema_conflict -- formats folder
  disagreements about metadata fields into user-readable explanations with
  folder basenames.

What does NOT belong here: Qt widgets, tree items or colours (gui/), deciding
what runs (orchestration/), what project is currently open (session/), which
curves or sources are filtered (selection/), or file I/O (io_modules/).
"""

from ._group_by_setup import UNASSIGNED_SETUP
from ._measurement_flag import MEASUREMENT_FLAG_KINDS, MeasurementFlag, PartiallyReadFlag, TachoInterpolationFlag
from ._pool_tree import (
    MARKER_IMPORTED_RESULT,
    MARKER_MISSING,
    MARKER_NONE,
    MARKER_UNASSIGNED,
    MARKER_UNREADABLE,
    NODE_CHANNEL,
    NODE_MEASUREMENT,
    NODE_SETUP,
    NODE_SHEET,
    NODE_UNREADABLE_FILE,
    NODE_UNREADABLE_FOLDER,
    PoolTree,
    PoolTreeNode,
    build_pool_tree,
)
from ._pool_tree_visibility import PoolTreeVisibility, resolve_pool_tree_visibility
from ._schema_conflict import describe_schema_conflict

__all__ = [
    "MARKER_IMPORTED_RESULT",
    "MARKER_MISSING",
    "MARKER_NONE",
    "MARKER_UNASSIGNED",
    "MARKER_UNREADABLE",
    "MEASUREMENT_FLAG_KINDS",
    "MeasurementFlag",
    "NODE_CHANNEL",
    "NODE_MEASUREMENT",
    "NODE_SETUP",
    "NODE_SHEET",
    "NODE_UNREADABLE_FILE",
    "NODE_UNREADABLE_FOLDER",
    "PartiallyReadFlag",
    "TachoInterpolationFlag",
    "PoolTree",
    "PoolTreeNode",
    "PoolTreeVisibility",
    "UNASSIGNED_SETUP",
    "build_pool_tree",
    "describe_schema_conflict",
    "resolve_pool_tree_visibility",
]
