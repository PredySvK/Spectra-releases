"""
Every edit to one FilterSelection, in one place -- what a click on
a facet value, a moved range bound, or a whole set of checks taken over does
to the selection. Pure (no Qt): FacetGrid only reports `(column key, value,
checked)` and two owners (Filter panel, Selection editor) share these rules
without sharing a widget.

Edits are in place: FilterSelectionStore holds the selection object's identity,
so a fresh FilterSelection would detach it from the store.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Set, Tuple

from core.filter_card_config import (
    COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_ORDER, COLUMN_PARAMETER_SET,
    IDENTITY_BUILTIN_ORDER,
)
from core.project_model import FilterSelection
from selection.parameter_sets import signature_matches_any, signatures_match

from ._trace_filter import EMPTY_FACET_VALUE

# The scalar gating families by Filter card column key: its "(Empty)" bucket
# token and the FilterSelection set it checks into. The keyed families
# (Identity columns, discrete metadata) use the column key as both.
_SCALAR_FAMILIES: Dict[str, Tuple[str, str]] = {
    COLUMN_CHANNEL: ("channel", "checked_channel_identities"),
    COLUMN_ORDER: ("order", "checked_orders"),
    COLUMN_ANALYSIS_TYPE: ("result_kind", "checked_result_kinds"),
    COLUMN_PARAMETER_SET: ("parameter_set", "checked_parameter_set_signatures"),
}

# Every gating family's checked field -- what write_checks takes over. Ranges
# are not here: they are "touched" only by an explicit edit.
_GATING_CHECK_FIELDS: Tuple[str, ...] = (
    "checked_channel_identities",
    "checked_orders",
    "checked_result_kinds",
    "checked_parameter_set_signatures",
    "checked_identity_values",
    "checked_metadata_values",
    "checked_empty_buckets",
)


def _empty_token(column_key: str) -> str:
    return _SCALAR_FAMILIES[column_key][0] if column_key in _SCALAR_FAMILIES else column_key


def _checked_values(selection: FilterSelection, column_key: str) -> Set[Any]:
    """The live set `column_key`'s checks are kept in, created on first use for
    a keyed column."""
    if column_key in _SCALAR_FAMILIES:
        return getattr(selection, _SCALAR_FAMILIES[column_key][1])
    keyed = (selection.checked_identity_values if column_key in IDENTITY_BUILTIN_ORDER
             else selection.checked_metadata_values)
    return keyed.setdefault(column_key, set())


def resolve_value_checked(selection: FilterSelection, column_key: str, value: Any) -> bool:
    """Whether `value` in column `column_key` is checked. The "(Empty)" row reads
    the column's bucket; a Parameter Set value is its signature, matched with
    float tolerance."""
    if value == EMPTY_FACET_VALUE:
        return _empty_token(column_key) in selection.checked_empty_buckets
    if column_key == COLUMN_PARAMETER_SET:
        return signature_matches_any(value, selection.checked_parameter_set_signatures)
    if column_key in _SCALAR_FAMILIES:
        return value in getattr(selection, _SCALAR_FAMILIES[column_key][1])
    keyed = (selection.checked_identity_values if column_key in IDENTITY_BUILTIN_ORDER
             else selection.checked_metadata_values)
    return value in keyed.get(column_key, set())


def write_value_check(selection: FilterSelection, column_key: str, value: Any,
                      checked: bool) -> None:
    """Check or uncheck one value of column `column_key`.

    The "(Empty)" row goes to `checked_empty_buckets`. Unchecking a Parameter
    Set drops every checked signature that names the same settings, so a value
    that round-tripped through float32/JSON does not stay checked.
    """
    if value == EMPTY_FACET_VALUE:
        target, value = selection.checked_empty_buckets, _empty_token(column_key)
    elif column_key == COLUMN_PARAMETER_SET and not checked:
        signatures = selection.checked_parameter_set_signatures
        signatures.difference_update([signature for signature in signatures
                                      if signatures_match(signature, value)])
        return
    else:
        target = _checked_values(selection, column_key)
    if checked:
        target.add(value)
    else:
        target.discard(value)


def write_range_bound(selection: FilterSelection, key: str, side: Literal["lo", "hi"],
                      value: Any, span: Tuple[Any, Any]) -> None:
    """Move one side of range `key`. The other side keeps its exact stored
    bound, or the data `span` when the range was never touched -- not a value
    rounded to the spin box's decimals (#350)."""
    lo, hi = selection.checked_ranges.get(key, span)
    selection.checked_ranges[key] = (value, hi) if side == "lo" else (lo, value)


def write_checks(selection: FilterSelection, checks: Any) -> None:
    """Take over every gating family's checks from `checks` -- any record with
    gating checked fields (a FilterSelection, DefaultedChecks or PanelRender).
    Ranges are left alone."""
    for name in _GATING_CHECK_FIELDS:
        setattr(selection, name, getattr(checks, name))


def write_ranges(selection: FilterSelection, checks: Any) -> None:
    """Take over the touched ranges from `checks` -- a PanelRender, whose
    `checked_ranges` keeps only the ranges still drawn."""
    selection.checked_ranges = dict(checks.checked_ranges)
