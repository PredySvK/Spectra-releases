# =====================================================================
# FILE: view_models/batch/__init__.py
# =====================================================================
"""
view_models.batch -- how a batch's channel-type scope is shown, without Qt.

Architecture:
- View-model floor (Floor 3): the combo labels the save editors offer for a
  batch's channel types ("Acceleration", "Sound", ...) and their translation
  to and from the sensor types orchestration.batch filters by.
- SAVE_CHANNEL_TYPE_OPTIONS: label -> sensor types, in combo order. One
  dictionary, so the ribbon dialog and the Workflow editor cannot disagree on
  what "Acceleration" filters to.
- resolve_channel_types / resolve_channel_type_label: the two directions, each
  None for a value no label matches; the editor decides what that shows.

What does NOT belong here: Qt combos (gui/), running or planning the batch
(orchestration.batch).
"""

from ._channel_type_options import (
    SAVE_CHANNEL_TYPE_OPTIONS,
    resolve_channel_type_label,
    resolve_channel_types,
)

__all__ = [
    "SAVE_CHANNEL_TYPE_OPTIONS",
    "resolve_channel_type_label",
    "resolve_channel_types",
]
