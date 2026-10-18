"""
settings -- the shape of every application setting the Settings window edits.

Per key: its default, how a stored value is coerced into a valid one, and
whether it takes effect only after a restart. No labels -- how a
setting is shown is view_models/settings; where it is held is session/settings.

The window's other fields are not here: panel toggles are layout and the
X axis unit is the open project's.
"""

from dataclasses import dataclass
from typing import Callable

from core.theme import resolve_graph_theme, resolve_theme
from core.units import CANONICAL_UNIT_GROUPS


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


def _choice(allowed) -> Callable[[object], str]:
    def coerce(value: object) -> str:
        if value not in allowed:
            raise ValueError(value)
        return str(value)
    return coerce


def _unit(domain: int) -> SettingDefinition:
    units = CANONICAL_UNIT_GROUPS[domain]
    return SettingDefinition(units[0], _choice(units))


SETTING_DEFINITIONS: dict[str, SettingDefinition] = {
    "open_last_project_on_startup": SettingDefinition(False, _flag),
    "check_for_updates_on_startup": SettingDefinition(True, _flag),
    "global_unit_acceleration": _unit(0),
    "global_unit_pressure": _unit(1),
    "global_unit_voltage": _unit(2),
    "global_unit_speed": _unit(3),
    "theme": SettingDefinition("dark", lambda value: resolve_theme(value).value, applies_after_restart=True),
    "graph_theme": SettingDefinition(
        "follow", lambda value: resolve_graph_theme(value).value, applies_after_restart=True),
    "perf_downsample_enabled": SettingDefinition(True, _flag),
    "perf_auto_mode_active": SettingDefinition(True, _flag),
    "perf_manual_factor": _integer(10, 2, 10000),
    "perf_render_screen_only": SettingDefinition(True, _flag),
    "highlight_other_opacity": _integer(25, 0, 100),
    # Only ever affects what is written next: h5py decompresses transparently,
    # so result sets already on disk stay readable.
    "result_cache_compression": SettingDefinition("", _choice(("", "lzf", "gzip"))),
    "use_result_cache_lookup": SettingDefinition(True, _flag),
}


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
