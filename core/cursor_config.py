# =====================================================================
# FILE: core/cursor_config.py
# =====================================================================
"""
`CursorConfig` -- which lines the Cursor Box shows and in what order (ADR §1.149).

Shape only: frozen data that round-trips through JSON so the GUI can keep it in
`shared_settings`. A key is either a fixed value key below or (later) a metadata
field key; the box builder skips a key the graph or project does not have.
The edit helpers below are what Cursor Settings drives: Priority is the field's
position in `fields`, so toggle / move / set-order all just reshape the tuple.
"""

from dataclasses import dataclass, replace
from typing import Any, Dict, Tuple

FIELD_X = "value.x"
FIELD_Y = "value.y"
FIELD_Z = "value.z"
FIELD_CURVE = "value.curve"
FIELD_AMPLITUDE = "value.amplitude"

DEFAULT_CURSOR_FIELDS: Tuple[str, ...] = (FIELD_CURVE, FIELD_X, FIELD_Y, FIELD_Z, FIELD_AMPLITUDE)


@dataclass(frozen=True)
class CursorConfig:
    """Enabled field keys, top line first."""

    fields: Tuple[str, ...] = DEFAULT_CURSOR_FIELDS

    def to_dict(self) -> Dict[str, Any]:
        return {"fields": list(self.fields)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CursorConfig":
        return cls(fields=tuple(str(key) for key in data.get("fields", DEFAULT_CURSOR_FIELDS)))


def with_field(config: CursorConfig, key: str, on: bool) -> CursorConfig:
    """Tick (append at the end, last Priority) or untick `key`; a no-op if already so."""
    has = key in config.fields
    if on and not has:
        return replace(config, fields=config.fields + (key,))
    if not on and has:
        return replace(config, fields=tuple(k for k in config.fields if k != key))
    return config


def with_field_order(config: CursorConfig, key: str, position: int) -> CursorConfig:
    """Move enabled `key` to 1-based `position`; out-of-range numbers clamp to the ends."""
    if key not in config.fields:
        return config
    others = [k for k in config.fields if k != key]
    index = max(1, min(int(position), len(others) + 1)) - 1
    return replace(config, fields=tuple(others[:index] + [key] + others[index:]))


def move_field(config: CursorConfig, key: str, delta: int) -> CursorConfig:
    """Nudge `key` by `delta` places (the arrows); a nudge past either end is a no-op."""
    if key not in config.fields:
        return config
    return with_field_order(config, key, config.fields.index(key) + 1 + delta)
