# =====================================================================
# FILE: core/field_priority.py
# =====================================================================
"""
Edits of an ordered field selection -- the one set of helpers behind every
window of checkbox + Priority rows (Cursor Settings, Track cursor Settings,
Legend Settings, Configure Filters -- all drawn by `gui.dialogs.priority_grid`).

A selection is any frozen dataclass whose `fields` is the tuple of enabled
keys, first Priority first (`CursorConfig`, `LegendConfig`). Priority is the
key's position, so tick / move / set-order all just reshape the tuple; every
helper returns the same type it was given (`dataclasses.replace`). The reorder
rule itself works on a plain key tuple (`with_key_order`, `move_key`), so the
Filter card's columns, which carry more than a key, reorder by it too. The
Default column's rules (`with_default`, `ordered_defaults`) sit here as well.
"""

from dataclasses import replace
from typing import Protocol, Tuple, TypeVar


class FieldSelection(Protocol):
    fields: Tuple[str, ...]


S = TypeVar("S", bound=FieldSelection)


def with_key(keys: Tuple[str, ...], key: str, on: bool) -> Tuple[str, ...]:
    """`keys` with `key` ticked (appended, last Priority) or unticked; unchanged if already so."""
    has = key in keys
    if on and not has:
        return keys + (key,)
    if not on and has:
        return tuple(k for k in keys if k != key)
    return keys


def with_field(selection: S, key: str, on: bool) -> S:
    """Tick (append at the end, last Priority) or untick `key`; a no-op if already so."""
    fields = with_key(selection.fields, key, on)
    return selection if fields == selection.fields else replace(selection, fields=fields)


def with_key_order(keys: Tuple[str, ...], key: str, position: int) -> Tuple[str, ...]:
    """`keys` with `key` moved to 1-based `position`: it takes the slot, the keys from there on
    shift one later, out-of-range numbers clamp to the ends. The one Priority rule -- the field
    selections below and the Filter card's columns (`core.filter_card_config`) both go through it.
    `keys` unchanged when `key` is not in it."""
    if key not in keys:
        return keys
    others = [k for k in keys if k != key]
    index = max(1, min(int(position), len(others) + 1)) - 1
    return tuple(others[:index] + [key] + others[index:])


def move_key(keys: Tuple[str, ...], key: str, delta: int) -> Tuple[str, ...]:
    """`keys` with `key` nudged `delta` places (the arrows); a nudge past either end changes nothing."""
    if key not in keys:
        return keys
    return with_key_order(keys, key, keys.index(key) + 1 + delta)


def with_field_order(selection: S, key: str, position: int) -> S:
    """Move enabled `key` to 1-based `position` (`with_key_order`); the same selection when nothing moves."""
    fields = with_key_order(selection.fields, key, position)
    return selection if fields == selection.fields else replace(selection, fields=fields)


def move_field(selection: S, key: str, delta: int) -> S:
    """Nudge `key` by `delta` places (the arrows); a nudge past either end returns the same selection."""
    fields = move_key(selection.fields, key, delta)
    return selection if fields == selection.fields else replace(selection, fields=fields)


# -- the Default column (Configure Filters §1.56, Legend Settings plot §1.298) --
# `defaults` are the keys flagged Default: what a new graph starts with. A flag sits on a
# ticked row only; a flagged key no ticked row shows (another graph's or project's part)
# stays as it is.


def with_default(defaults: Tuple[str, ...], ticked: Tuple[str, ...], key: str, on: bool) -> Tuple[str, ...]:
    """Flag or unflag `key` as Default; flagging a key that is not ticked changes nothing.
    Unticking a row unflags it too: call this with `on=False` for that key."""
    if on and key not in ticked:
        return defaults
    return with_key(defaults, key, on)


def ordered_defaults(ticked: Tuple[str, ...], defaults: Tuple[str, ...]) -> Tuple[str, ...]:
    """The Default keys in the ticked rows' Priority order, then the flagged keys no ticked row shows."""
    shown = tuple(k for k in ticked if k in defaults)
    return shown + tuple(k for k in defaults if k not in shown)
