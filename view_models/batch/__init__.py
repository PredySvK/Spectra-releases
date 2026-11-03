# =====================================================================
# FILE: view_models/batch/__init__.py
# =====================================================================
"""
view_models.batch -- how a batch's channel-type scope is shown, without Qt.

Architecture:
- View-model floor (Floor 3): the combo labels offered for a batch's channel
  types ("Accelerometer", "Microphone", ...) and their translation to and from
  the sensor types orchestration.batch filters by. The labels name the sensor,
  never the quantity (CONTEXT.md, Channel type).
- SAVE_CHANNEL_TYPE_OPTIONS: label -> sensor types, in combo order -- the
  Workflow editor's save block combo, offered next to "Any type".
- DATA_POOL_TYPE_OPTIONS / resolve_data_pool_types: the Compute Result Set
  dialog's own combo over the Data Pool (All / Accelerometer / Microphone).
  A second dictionary on purpose: "All" is a choice of its own there, and an
  unknown label falls back to it rather than to None.
- resolve_channel_types / resolve_channel_type_label: the two directions, each
  None for a value no label matches; the editor decides what that shows.

What does NOT belong here: Qt combos (gui/), running or planning the batch
(orchestration.batch).
"""

from ._channel_type_options import (
    DATA_POOL_TYPE_OPTIONS,
    DEFAULT_DATA_POOL_TYPE,
    SAVE_CHANNEL_TYPE_OPTIONS,
    resolve_data_pool_types,
    resolve_channel_type_label,
    resolve_channel_types,
)

__all__ = [
    "DATA_POOL_TYPE_OPTIONS",
    "DEFAULT_DATA_POOL_TYPE",
    "resolve_data_pool_types",
    "SAVE_CHANNEL_TYPE_OPTIONS",
    "resolve_channel_type_label",
    "resolve_channel_types",
]
