# =====================================================================
# FILE: core/filter_card_config.py
# =====================================================================
"""
`FilterCardConfig` -- what one Filter card shows: which columns, in what order,
drawn as which widget, and how many columns sit side by side
(ARCHITECTURE_DECISIONS §1.32).

Lives in core/ for the same reason as `core/measurement_selection.py` and
`core/workflow_graph.py`: it is pure data with no I/O and no Qt, it round-trips
through JSON, and it is serialised into `.nvhproject` as a project-owned
decision. "Which columns a Filter card offers" used to be a property of the
metadata schema -- one setting for the whole app -- and §1.32 makes it a
per-card decision instead, which means it has to have a home in the project.

`FilterProfile` (identity), `FilterSelection` (checked values, per-dock) and
this (columns, per-card) are three separate things -- CONTEXT.md "Filter card"
owns why they must not be merged. Merging the config in would make the checked
values dirty too, which §1.32 explicitly rejected.

The half that turns a column key into a live facet (reading the schema, the
pool and the dock's traces) stays in `gui/filter_panel/` -- this module only
describes the shape.
"""

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional, Set, Tuple
import logging
import uuid

logger = logging.getLogger(__name__)


# -- column groups -------------------------------------------------------------
# The four facet groups a Filter card draws from (CONTEXT.md: "Identity",
# "Calculated metadata"). A column's group is fixed by its key -- a schema field
# is `raw` or `excel` depending on its schema layer, the built-in columns below
# are `identity` or `calculated` -- but it is stored on the column too so the
# card model never has to reach back into the schema to know how to section the
# dialog (§1.32: the card itself is a flat list, the sectioning is the dialog).
GROUP_IDENTITY = "identity"
GROUP_RAW = "raw"
GROUP_EXCEL = "excel"
GROUP_CALCULATED = "calculated"

GROUPS = (GROUP_IDENTITY, GROUP_RAW, GROUP_EXCEL, GROUP_CALCULATED)


# -- widgets ------------------------------------------------------------------
# The three ways a column can be drawn (§1.34). #43 enumerated five; the grill
# on 2026-09-07 dropped `checkbox` (a single "Only <value>" box has no way to
# pick which value it isolates) and `text_search` (the only widget carrying a
# third predicate family, substring, for two words of specification). What is
# left is two renderings of the same set mask plus the min..max range.
WIDGET_CHECKBOX_LIST = "checkbox_list"   # the default
WIDGET_RANGE = "range"
WIDGET_MULTI_SELECT = "multi_select"

WIDGETS = (WIDGET_CHECKBOX_LIST, WIDGET_RANGE, WIDGET_MULTI_SELECT)

# The two widgets that draw a set mask (§1.29: offered and unchecked => hide).
# They are the same thing bit for bit -- same `checked_*` state, same mask, an
# empty pick hides everything in both -- and differ only in how much room they
# take on the card (§1.34).
SET_MASK_WIDGETS = (WIDGET_CHECKBOX_LIST, WIDGET_MULTI_SELECT)

# The schema field kinds that filter as a range rather than as a set of values
# (selection.source_facets.field_kind). This is the *predicate* family and
# the card never overrides it: a numeric column that should be a value list has
# its Type switched to Text in Metadata and Filter Settings instead (§1.34).
RANGE_KINDS = ("int", "float", "date")

# Widget names already reported as unknown, so a project full of columns saved
# by a dialog that offered five widgets logs once per name instead of once per
# column (§1.34: "prepíše na checkbox_list a raz zaloguje"). Module-level state
# is deliberate and harmless here -- it changes nothing a caller can observe
# except how often the log repeats itself.
_UNKNOWN_WIDGETS_REPORTED: Set[str] = set()


def _widget_from_stored(widget: str) -> str:
    """
    A stored widget name, or `checkbox_list` if it names nothing this version
    knows (§1.34).

    Only `from_dict` is this forgiving; `FilterColumnConfig.__post_init__` stays
    strict. A file that is older has to open -- a project saved between #49 and
    #50 carries `checkbox` and `text_search` columns from a dialog that offered
    them -- while a *call* that lies (a typo in code) still has to fail loudly.
    """
    if widget in WIDGETS:
        return widget
    if widget not in _UNKNOWN_WIDGETS_REPORTED:
        _UNKNOWN_WIDGETS_REPORTED.add(widget)
        logger.warning(
            "Filter card column widget '%s' is not one of %s -- drawing it as a checkbox list.",
            widget, ", ".join(WIDGETS),
        )
    return WIDGET_CHECKBOX_LIST


# -- built-in column keys ----------------------------------------------------
# Columns the app can offer without reading any metadata at all (CONTEXT.md
# "Identity") or that describe the computation rather than the measurement
# (CONTEXT.md "Calculated metadata"). Their keys are constants rather than
# schema field keys, prefixed so they can never collide with a user's schema
# field name.
COLUMN_CHANNEL = "identity.channel"
COLUMN_DIRECTION = "identity.direction"
COLUMN_CHANNEL_TYPE = "identity.channel_type"
COLUMN_FILE_NAME = "identity.file_name"
COLUMN_DATA_POOL_LABEL = "identity.data_pool_label"
COLUMN_RESULT_SET = "identity.result_set"
COLUMN_ANALYSIS_TYPE = "calculated.analysis_type"
COLUMN_ORDER = "calculated.order"
COLUMN_PARAMETER_SET = "calculated.parameter_set"

# Display order and label for each built-in column, section by section
# (ticket #42): Configure Filters lays Identity and Calculated out in this
# fixed order, not alphabetically -- unlike a schema field, a built-in has no
# custom_label to sort by, and this reads better than one anyway (Channel
# before what channel *type* it is, Order before what analysis produced it).
IDENTITY_BUILTIN_ORDER: Tuple[str, ...] = (
    COLUMN_CHANNEL, COLUMN_DIRECTION, COLUMN_CHANNEL_TYPE, COLUMN_FILE_NAME,
    COLUMN_DATA_POOL_LABEL, COLUMN_RESULT_SET,
)
CALCULATED_BUILTIN_ORDER: Tuple[str, ...] = (
    COLUMN_ANALYSIS_TYPE, COLUMN_ORDER, COLUMN_PARAMETER_SET,
)

BUILTIN_COLUMN_LABELS: Dict[str, str] = {
    COLUMN_CHANNEL: "Channel",
    COLUMN_DIRECTION: "Direction",
    COLUMN_CHANNEL_TYPE: "Channel type",
    COLUMN_FILE_NAME: "File name",
    COLUMN_DATA_POOL_LABEL: "Data Pool label",
    COLUMN_RESULT_SET: "Result set",
    COLUMN_ANALYSIS_TYPE: "Analysis type",
    COLUMN_ORDER: "Order",
    COLUMN_PARAMETER_SET: "Parameter set",
}

BUILTIN_COLUMN_GROUPS: Dict[str, str] = {
    key: GROUP_IDENTITY for key in IDENTITY_BUILTIN_ORDER
}
BUILTIN_COLUMN_GROUPS.update({key: GROUP_CALCULATED for key in CALCULATED_BUILTIN_ORDER})

# The built-in column keys, as a set -- a caller telling a card's schema-field
# columns apart from its Identity/Calculated ones (selection.trace_filter)
# should test against this, not re-list the COLUMN_* constants.
BUILTIN_COLUMN_KEYS = frozenset(BUILTIN_COLUMN_GROUPS)

# The Identity built-ins that render as their own checkbox-list facet on the
# panel (ticket #37 story 9, ADR §1.33). Channel is excluded: it has its own
# dedicated facet path (channel_identities) that predates this. Analysis type /
# Order / Parameter set (Calculated) map onto the existing Result Kind / Order /
# Parameter Set facets instead, so they are not here either.
LIVE_IDENTITY_FACET_COLUMNS = frozenset({
    COLUMN_DIRECTION, COLUMN_CHANNEL_TYPE, COLUMN_FILE_NAME,
    COLUMN_DATA_POOL_LABEL, COLUMN_RESULT_SET,
})


DEFAULT_COLUMN_COUNT = 2

# How many facet columns a card may draw side by side (§1.37 widened §1.32's
# "2 or 3"). `from_dict` clamps anything else back to the default rather than
# refusing to open the project.
ALLOWED_COLUMN_COUNTS = (1, 2, 3, 4)


def _new_id() -> str:
    return f"fcard_{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class FilterColumnConfig:
    """
    One column on a Filter card.

    `key` is a metadata schema field key, or one of the `COLUMN_*` constants
    above for an Identity / Calculated column that has no schema row.

    `order` is a 1-based position. The edit helpers below keep a card's orders
    dense and unique, but `__post_init__` does not renumber -- a JSON round-trip
    returns exactly what was stored, and a half-built card handed in by a test
    stays as given.

    `default` is the user's "put this on a fresh card of this kind" checkbox
    (§1.32) -- the only way an Excel metadata column enters a built-in default
    set.
    """
    key: str
    group: str
    order: int = 1
    widget: str = WIDGET_CHECKBOX_LIST
    default: bool = False

    def __post_init__(self):
        object.__setattr__(self, "key", str(self.key))
        object.__setattr__(self, "order", int(self.order))
        object.__setattr__(self, "default", bool(self.default))
        if self.group not in GROUPS:
            raise ValueError(
                f"Unknown column group '{self.group}'. Valid groups: {', '.join(GROUPS)}."
            )
        if self.widget not in WIDGETS:
            raise ValueError(
                f"Unknown column widget '{self.widget}'. Valid widgets: {', '.join(WIDGETS)}."
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "group": self.group,
            "order": self.order,
            "widget": self.widget,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "FilterColumnConfig":
        data = data or {}
        return cls(
            key=str(data.get("key") or ""),
            group=str(data.get("group") or GROUP_IDENTITY),
            order=int(data.get("order", 1) or 1),
            widget=_widget_from_stored(str(data.get("widget") or WIDGET_CHECKBOX_LIST)),
            default=bool(data.get("default", False)),
        )


def _column_count_from_stored(value: Any) -> int:
    """A stored `column_count`, or the default if it names nothing in
    `ALLOWED_COLUMN_COUNTS` (§1.37) -- an older or hand-edited project still
    opens."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return DEFAULT_COLUMN_COUNT
    return count if count in ALLOWED_COLUMN_COUNTS else DEFAULT_COLUMN_COUNT


@dataclass(frozen=True)
class FilterCardConfig:
    """
    The column configuration of one Filter card.

    Frozen the whole way down, the same as `core/measurement_selection.py`: a
    config handed to a redraw cannot be edited underneath it. A card editor
    makes changes by rebuilding through the module-level helpers, each of which
    returns a new `FilterCardConfig`.

    `id` ties the config to a `FilterProfile` of the same id in
    `core/project_model.py`.

    `column_count` is restricted to 1..4 (§1.37 widened §1.32's "2 or 3"): a
    card with three columns and a card with fifteen do not want the same width,
    so it is a property of the card, not the app.
    """
    id: str = field(default_factory=_new_id)
    columns: Tuple[FilterColumnConfig, ...] = ()
    column_count: int = DEFAULT_COLUMN_COUNT

    def __post_init__(self):
        object.__setattr__(self, "id", str(self.id) or _new_id())
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "column_count", int(self.column_count))

        if self.column_count not in ALLOWED_COLUMN_COUNTS:
            raise ValueError(
                f"A Filter card draws in 1 to 4 columns, not {self.column_count} (§1.37)."
            )

        seen: set = set()
        for column in self.columns:
            if column.key in seen:
                raise ValueError(f"Duplicate Filter card column key '{column.key}'.")
            seen.add(column.key)

    def column(self, key: str) -> FilterColumnConfig:
        for column in self.columns:
            if column.key == key:
                return column
        raise KeyError(key)

    def has_column(self, key: str) -> bool:
        return any(column.key == key for column in self.columns)

    @property
    def ordered_columns(self) -> Tuple[FilterColumnConfig, ...]:
        """Columns sorted by `order`, ties broken by their stored position."""
        return tuple(sorted(self.columns, key=lambda column: column.order))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "columns": [column.to_dict() for column in self.columns],
            "column_count": self.column_count,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "FilterCardConfig":
        data = data or {}
        return cls(
            id=str(data.get("id") or _new_id()),
            columns=tuple(
                FilterColumnConfig.from_dict(raw) for raw in (data.get("columns") or ())
            ),
            column_count=_column_count_from_stored(
                data.get("column_count", DEFAULT_COLUMN_COUNT)
            ),
        )


# -- immutable edit helpers ---------------------------------------------------
# A FilterCardConfig is frozen, so the "Configure Filters" dialog changes one by
# rebuilding. They live here, on the pure-data model, because none of them needs
# the schema or the pool -- deriving a *live* facet from a column key does, and
# that stays in gui/filter_panel/.


def renumbered(columns) -> Tuple[FilterColumnConfig, ...]:
    """`columns` in the given sequence order, orders reassigned 1..N. Public
    (ADR §1.47) so `gui/filter_panel/filter_card.py` builds cards through this
    one rule instead of keeping a hand-synced twin."""
    return tuple(
        replace(column, order=position)
        for position, column in enumerate(columns, start=1)
    )


def with_column_order(card: FilterCardConfig, key: str, requested_order: int) -> FilterCardConfig:
    """
    Move the column `key` to position `requested_order` (1-based), typing a new
    number straight into the field.

    Collision is defined (§1.32 / ticket #40): the edited column takes the
    requested slot and every column at or after it shifts down, then the whole
    card is renumbered dense. Out-of-range numbers clamp to the ends.
    """
    target = card.column(key)
    others = sorted(
        (column for column in card.columns if column.key != key),
        key=lambda column: column.order,
    )
    position = max(1, min(int(requested_order), len(others) + 1)) - 1
    reordered = others[:position] + [target] + others[position:]
    return replace(card, columns=renumbered(reordered))


def move_column(card: FilterCardConfig, key: str, delta: int) -> FilterCardConfig:
    """
    Nudge the column `key` `delta` places (the up/down arrows: +1 / -1). A nudge
    past either end is a no-op that returns the same card. Just `with_column_order`
    against the column's current sorted position, so the two stay one rule.
    """
    ordered = card.ordered_columns
    index = next(i for i, column in enumerate(ordered) if column.key == key)
    target_index = max(0, min(index + delta, len(ordered) - 1))
    if target_index == index:
        return card
    return with_column_order(card, key, target_index + 1)


def add_column(card: FilterCardConfig, column: FilterColumnConfig) -> FilterCardConfig:
    """
    Append a newly checked column at the end with the highest number, so it
    never disturbs an order the user has already arranged (§1.32 / ticket #40).
    """
    if card.has_column(column.key):
        raise ValueError(f"Filter card already has a column '{column.key}'.")
    highest = max((existing.order for existing in card.columns), default=0)
    return replace(card, columns=card.columns + (replace(column, order=highest + 1),))


def remove_column(card: FilterCardConfig, key: str) -> FilterCardConfig:
    """Drop the column `key` (unchecked in the dialog) and renumber dense."""
    remaining = [column for column in card.ordered_columns if column.key != key]
    return replace(card, columns=renumbered(remaining))


def with_column_count(card: FilterCardConfig, column_count: int) -> FilterCardConfig:
    return replace(card, column_count=int(column_count))


def with_column_widget(card: FilterCardConfig, key: str, widget: str) -> FilterCardConfig:
    """
    Redraw the column `key` with a different widget -- the Configure Filters
    per-column widget picker (ticket #49). `FilterColumnConfig.__post_init__`
    rejects a widget name that is not in `WIDGETS`.
    """
    card.column(key)  # KeyError naming the miss, same as with_column_order
    return replace(card, columns=tuple(
        replace(column, widget=widget) if column.key == key else column
        for column in card.columns
    ))


def kind_is_ranged(kind: Optional[str]) -> bool:
    """
    Whether a schema field `kind` filters as a `min..max` range rather than as
    a set of values. The predicate family belongs to the field, never to the
    card (§1.34) -- so this is also what decides whether the widget picker in
    Configure Filters has anything left to pick.
    """
    return kind in RANGE_KINDS


def default_widget_for_kind(kind: Optional[str]) -> str:
    """
    The widget a column starts with, given its schema field `kind`
    (selection.source_facets.field_kind): a `min..max` range for the
    numeric and date kinds ticket #39 wired onto the mask path, a checkbox
    list for everything else. The Identity / Calculated built-ins have no
    kind and get the checkbox list too.

    Deliberately kind-based only: a default that read the column's cardinality
    or its name would move under the user's hands as the pool grows (§1.34
    repeats §1.32's rejection).
    """
    return WIDGET_RANGE if kind_is_ranged(kind) else WIDGET_CHECKBOX_LIST


def effective_widget(kind: Optional[str], stored_widget: str) -> str:
    """
    How a column is actually drawn, given its schema field `kind` and the
    widget stored on its card (§1.34).

    The rule in one line: `kind` picks the predicate family, the stored widget
    only picks a rendering inside it. A ranged kind is a range no matter what
    the card says, and a stored widget that belongs to the other family (a
    `range` left on a text column after its Type was switched) falls back to the
    checkbox list rather than drawing a min..max box over values that have no
    order.

    The panel does not make this call itself: it is a pure function of two
    values, so it is tested here without Qt like the rest of core/.
    """
    if kind_is_ranged(kind):
        return WIDGET_RANGE
    return stored_widget if stored_widget in SET_MASK_WIDGETS else WIDGET_CHECKBOX_LIST


def duplicate(card: FilterCardConfig, new_id: Optional[str] = None) -> FilterCardConfig:
    """
    A copy of `card` with the same columns and column count but a fresh id --
    "duplicate this card" in the dialog (§1.32 / ticket #40).
    """
    return replace(card, id=str(new_id) if new_id else _new_id())


def with_column_default(card: FilterCardConfig, key: str, default: bool) -> FilterCardConfig:
    """
    Flip the column `key`'s `default` flag -- the "Default" checkbox in Configure
    Filters, which pins a column onto every fresh graph's card (§1.32 / ticket
    #44). `card.column` raises KeyError naming the miss, same as the other
    per-column helpers.
    """
    card.column(key)
    return replace(card, columns=tuple(
        replace(column, default=bool(default)) if column.key == key else column
        for column in card.columns
    ))
