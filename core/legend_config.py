# =====================================================================
# FILE: core/legend_config.py
# =====================================================================
"""
`LegendConfig` -- which parts a Curve name is made of and in what order.

Shape only: frozen data that round-trips through JSON. A key is a Filter card
column key or one of the two legend-only value keys below; the legend builder
skips a key the curve has no value for. Priority is the key's position in
`fields`, so tick / move / set-order all just reshape the tuple (`core.field_priority`,
the same helpers as `CursorConfig`).
"""

from dataclasses import dataclass
from typing import Any, Dict, Tuple

from core.filter_card_config import COLUMN_CHANNEL, COLUMN_FILE_NAME

FIELD_RESULT_NAME = "value.result_name"
FIELD_UNIT = "value.unit"
# The legend-only value keys; every other key is a Filter card column key.
LEGEND_VALUE_FIELDS = frozenset((FIELD_RESULT_NAME, FIELD_UNIT))

DEFAULT_LEGEND_FIELDS: Tuple[str, ...] = (COLUMN_FILE_NAME, COLUMN_CHANNEL, FIELD_RESULT_NAME, FIELD_UNIT)


@dataclass(frozen=True)
class LegendConfig:
    """Enabled part keys, first part first."""

    fields: Tuple[str, ...] = DEFAULT_LEGEND_FIELDS

    def to_dict(self) -> Dict[str, Any]:
        return {"fields": list(self.fields)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LegendConfig":
        return cls(fields=tuple(str(key) for key in data.get("fields", DEFAULT_LEGEND_FIELDS)))

