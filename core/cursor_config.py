# =====================================================================
# FILE: core/cursor_config.py
# =====================================================================
"""
`CursorConfig` -- which lines the Cursor Box (or the columns the Track table) shows and in what order.

Shape only: frozen data that round-trips through JSON so the GUI can keep it in
the shared QSettings group. A key is either a fixed value key below or (later) a metadata
field key; the box builder skips a key the graph or project does not have.
Cursor Settings edits it through `core.field_priority`: Priority is the field's
position in `fields`, so toggle / move / set-order all just reshape the tuple.
"""

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from core.filter_card_config import COLUMN_CHANNEL

FIELD_X = "value.x"
FIELD_Y = "value.y"
FIELD_Z = "value.z"
FIELD_CURVE = "value.curve"
FIELD_AMPLITUDE = "value.amplitude"
# The fixed value keys; every other key is a metadata field.
VALUE_FIELDS = frozenset((FIELD_X, FIELD_Y, FIELD_Z, FIELD_CURVE, FIELD_AMPLITUDE))

# Channel and Z never show together: a curve graph skips Z, a spectrogram skips metadata.
DEFAULT_CURSOR_FIELDS: Tuple[str, ...] = (COLUMN_CHANNEL, FIELD_X, FIELD_Y, FIELD_Z)
# The Track table's columns until the user picks others: X is always above it, Z is a spectrogram's.
DEFAULT_TRACK_TABLE_FIELDS: Tuple[str, ...] = (COLUMN_CHANNEL, FIELD_Y)


@dataclass(frozen=True)
class CursorConfig:
    """Enabled field keys, top line first."""

    fields: Tuple[str, ...] = DEFAULT_CURSOR_FIELDS

    def to_dict(self) -> Dict[str, Any]:
        return {"fields": list(self.fields)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any],
                  default_fields: Tuple[str, ...] = DEFAULT_CURSOR_FIELDS) -> "CursorConfig":
        """`default_fields` stand in when `data` names no fields (another tool's own defaults)."""
        return cls(fields=tuple(str(key) for key in data.get("fields", default_fields)))

