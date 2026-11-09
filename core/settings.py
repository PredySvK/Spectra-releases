"""
settings -- the shape of every application setting the Settings store holds.

Per key: its default, how a stored value is coerced into a valid one, and
whether it takes effect only after a restart. No labels -- how a
setting is shown is view_models/settings; where it is held is session/settings.
Besides the Settings window's fields, the store holds the Tools tab switches
(`TOOL_SWITCH_KEYS`, ADR §1.290) and `DIALOG_ONLY_KEYS`, which that window never shows.

The window's other fields are not here: panel toggles are layout and the
X axis unit is the open project's.
"""

import math
from dataclasses import dataclass
from typing import Callable

from core.tacho_cleaning import (
    DEFAULT_TACHO_HAMPEL_FILTER, DEFAULT_TACHO_HAMPEL_SIGMA, DEFAULT_TACHO_SMOOTHING_MS,
)
from core.theme import resolve_graph_theme, resolve_theme
from core.units import DISPLAY_BASE_UNIT_GROUPS, UnitPreferences


@dataclass(frozen=True)
class SettingDefinition:
    """One setting: ``coerce`` turns any stored value into a valid one or raises ValueError/TypeError.

    An integer setting also carries its range; ``minimum`` is None for every other kind.
    """

    default: object
    coerce: Callable[[object], object]
    applies_after_restart: bool = False
    minimum: int | None = None
    maximum: int | None = None


def _flag(value: object) -> bool:
    # An ini file gives every value back as text.
    if isinstance(value, str):
        if value.lower() in ("true", "1"):
            return True
        if value.lower() in ("false", "0"):
            return False
        raise ValueError(value)
    return bool(value)


def _integer(default: int, minimum: int, maximum: int) -> SettingDefinition:
    def coerce(value: object) -> int:
        return max(minimum, min(maximum, int(value)))
    return SettingDefinition(default, coerce, minimum=minimum, maximum=maximum)


def _non_negative_number(value: object) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(value)
    return number


def _positive_number(value: object) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(value)
    return number


def _db_reference(quantity: str) -> SettingDefinition:
    return SettingDefinition(getattr(UnitPreferences(), f"db_reference_{quantity}"), _positive_number)


def _choice(allowed) -> Callable[[object], str]:
    def coerce(value: object) -> str:
        if value not in allowed:
            raise ValueError(value)
        return str(value)
    return coerce


PREFIX_CHOICES: tuple[str, ...] = ("none", "auto", "µ", "m", "k", "M", "scientific")


def _prefix() -> SettingDefinition:
    return SettingDefinition("none", _choice(PREFIX_CHOICES))


DECIMALS_CHOICES: tuple[str, ...] = ("auto", "0", "1", "2", "3", "4", "5", "6")


def _decimals(default: str) -> SettingDefinition:
    return SettingDefinition(default, _choice(DECIMALS_CHOICES))


def _unit(domain: int) -> SettingDefinition:
    units = DISPLAY_BASE_UNIT_GROUPS[domain]
    return SettingDefinition(units[0], _choice(units))


SETTING_DEFINITIONS: dict[str, SettingDefinition] = {
    "open_last_project_on_startup": SettingDefinition(False, _flag),
    "check_for_updates_on_startup": SettingDefinition(True, _flag),
    "global_unit_acceleration": _unit(0),
    "global_unit_pressure": _unit(1),
    "global_unit_voltage": _unit(2),
    "global_unit_speed": _unit(3),
    "prefix_acceleration": _prefix(),
    "prefix_pressure": _prefix(),
    "prefix_voltage": _prefix(),
    "prefix_speed": _prefix(),
    "prefix_frequency": _prefix(),
    "prefix_time": _prefix(),
    "decimals_acceleration": _decimals("2"),
    "decimals_pressure": _decimals("2"),
    "decimals_voltage": _decimals("2"),
    "decimals_speed": _decimals("0"),
    "decimals_frequency": _decimals("2"),
    "decimals_time": _decimals("4"),
    # In core.units.DB_REFERENCE_UNITS, whatever the Display unit (#947).
    "db_reference_acceleration": _db_reference("acceleration"),
    "db_reference_pressure": _db_reference("pressure"),
    "db_reference_voltage": _db_reference("voltage"),
    "theme": SettingDefinition("dark", lambda value: resolve_theme(value).value, applies_after_restart=True),
    "graph_theme": SettingDefinition(
        "follow", lambda value: resolve_graph_theme(value).value, applies_after_restart=True),
    "perf_downsample_enabled": SettingDefinition(True, _flag),
    "perf_auto_mode_active": SettingDefinition(True, _flag),
    "perf_manual_factor": _integer(10, 2, 10000),
    "perf_render_screen_only": SettingDefinition(True, _flag),
    "highlight_other_opacity": _integer(25, 0, 100),
    # Opacity of the Track table's background, in percent (90 % = the box fill's alpha 230 of 255).
    # Set in Track cursor Settings only, never shown in the Settings window.
    "track_table_opacity": _integer(90, 0, 100),
    # Only ever affects what is written next: h5py decompresses transparently,
    # so result sets already on disk stay readable.
    "result_cache_compression": SettingDefinition("", _choice(("", "lzf", "gzip"))),
    "use_result_cache_lookup": SettingDefinition(True, _flag),
    # Tacho cleaning: stamped into every tracked DSP config for the next
    # calculation. No upper limits -- a window longer than
    # the record is clipped to it, a threshold past every sample flags none.
    "tacho_hampel_filter": SettingDefinition(DEFAULT_TACHO_HAMPEL_FILTER, _flag),
    "tacho_hampel_sigma": SettingDefinition(DEFAULT_TACHO_HAMPEL_SIGMA, _positive_number),
    "tacho_smoothing_ms": SettingDefinition(DEFAULT_TACHO_SMOOTHING_MS, _non_negative_number),
    # The Tools tab switches: one for every graph, remembered across starts, never shown in
    # the Settings window. Off at first except the Cursor and the Track pin.
    "cursor_enabled": SettingDefinition(True, _flag),
    "cursor_pinned": SettingDefinition(False, _flag),
    "highlight_enabled": SettingDefinition(False, _flag),
    "track_cursor_enabled": SettingDefinition(False, _flag),
    "track_cursor_pinned": SettingDefinition(True, _flag),
    "track_cursor_highlight_enabled": SettingDefinition(False, _flag),
}

# Settings that only a tool's own dialog edits; the Settings window never shows them.
DIALOG_ONLY_KEYS: frozenset[str] = frozenset({"track_table_opacity"})

TOOL_SWITCH_KEYS: frozenset[str] = frozenset({
    "cursor_enabled", "cursor_pinned", "highlight_enabled", "track_cursor_enabled", "track_cursor_pinned",
    "track_cursor_highlight_enabled"})


def resolve_setting_value(key: str, value: object) -> object:
    """The valid value of ``key`` for a stored ``value``; absent (None) or unreadable means the default.

    Raises KeyError for a key that is not a setting.
    """
    definition = SETTING_DEFINITIONS[key]
    if value is None:
        return definition.default
    try:
        return definition.coerce(value)
    except (ValueError, TypeError):
        return definition.default
