"""Which Settings → Units row a Display unit falls under, and the prefixes that row offers."""

from __future__ import annotations

from typing import Optional

from core.units import CANONICAL_UNIT_GROUPS, UnitPreferences, sanitize_unit_string

UNITS_ROWS: tuple[str, ...] = ("acceleration", "pressure", "voltage", "speed", "frequency", "time")

PREFIX_FACTORS: dict[str, float] = {
    "µ": 1e6,
    "m": 1e3,
    "k": 1e-3,
    "M": 1e-6,
}

ALL_DISPLAY_PREFIXES: tuple[str, ...] = ("none", "auto", "µ", "m", "k", "M", "scientific")
G_DISPLAY_PREFIXES: tuple[str, ...] = ("none", "auto", "µ", "m", "scientific")

_PREFIX_LABELS: dict[str, str] = {"none": "None", "auto": "Auto", "scientific": "Scientific"}

# The quantity (core.data_block.Axis.quantity) that makes a Hz value a shaft speed.
_SPEED_QUANTITY = "rpm"

_ACCELERATION = {sanitize_unit_string(u) for u in CANONICAL_UNIT_GROUPS[0]}
_PRESSURE = {sanitize_unit_string(u) for u in CANONICAL_UNIT_GROUPS[1]}
_VOLTAGE = {sanitize_unit_string(u) for u in CANONICAL_UNIT_GROUPS[2]}
_SPEED = {sanitize_unit_string(u) for u in CANONICAL_UNIT_GROUPS[3] if u != "Hz"}
_TIME = {"s", "sec", "second", "seconds"}


def is_db_unit(unit: str) -> bool:
    """dB in any spelling (``dB``, ``dB(A)``): never prefixed, always one decimal."""
    return "db" in (unit or "").strip().lower()


def _base_token(unit: str) -> str:
    """``unit`` without a trailing amplitude word (``g RMS`` → ``g``)."""
    token = (unit or "").strip()
    parts = token.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].lower() in ("rms", "peak", "pk"):
        token = parts[0]
    return token


def _is_g_unit(unit: str) -> bool:
    token = _base_token(unit)
    return token.lower() == "g" or sanitize_unit_string(token) == "gravity"


def resolve_units_row(unit: str, *, quantity: str = "") -> Optional[str]:
    """The Units row (``UNITS_ROWS``) that formats ``unit``, or None for no row.

    The unit decides on its own, except ``Hz``: it is the Speed row only when
    ``quantity`` says the value is a shaft speed (``"rpm"``), otherwise the
    Frequency row. dB, orders, % and units without a row give None.
    """
    if not unit or is_db_unit(unit):
        return None
    token = _base_token(unit)
    if token.lower() in ("order", "orders", "%", "percent"):
        return None
    sanitized = sanitize_unit_string(token)
    if sanitized in _TIME or token.lower() in _TIME:
        return "time"
    if sanitized in _ACCELERATION:
        return "acceleration"
    if sanitized in _PRESSURE:
        return "pressure"
    if sanitized in _VOLTAGE:
        return "voltage"
    if sanitized in _SPEED:
        return "speed"
    if sanitized == "hertz":
        return "speed" if quantity == _SPEED_QUANTITY else "frequency"
    return None


def read_row_setting(prefs: UnitPreferences, row: str) -> tuple[str, str]:
    """(Display prefix, decimals) the user set for ``row``."""
    return getattr(prefs, f"prefix_{row}"), getattr(prefs, f"decimals_{row}")


def resolve_display_prefix_choices(unit: str) -> tuple[str, ...]:
    """Prefix tokens a row offers with ``unit`` as its Display unit: ``g`` has no ``k``/``M``."""
    return G_DISPLAY_PREFIXES if _is_g_unit(unit) else ALL_DISPLAY_PREFIXES


def resolve_display_prefix_setting_choices(unit: str) -> tuple[tuple[str, str], ...]:
    """((label, value), ...) for the prefix SettingsField of a row showing ``unit``."""
    return tuple((_PREFIX_LABELS.get(p, p), p) for p in resolve_display_prefix_choices(unit))


def resolve_display_prefix_for_unit_change(old_prefix: str, new_unit: str) -> str:
    """``old_prefix`` if ``new_unit`` still offers it, else ``"none"``."""
    return old_prefix if old_prefix in resolve_display_prefix_choices(new_unit) else "none"
