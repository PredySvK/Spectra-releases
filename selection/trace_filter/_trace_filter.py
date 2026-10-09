# =====================================================================
# FILE: selection/trace_filter/_trace_filter.py
# =====================================================================
"""
Core gating logic and TraceIdentity for the selection floor (ADR §1.29, §1.55,
ticket #168).

Whether a FilterSelection hides or shows one already-drawn Trace (via its
TraceIdentity). A mask hides only what the user had a checkbox for and
unchecked: a value the Filter panel never offered passes through untouched
(OfferedFacets, ARCHITECTURE_DECISIONS §1.29).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import (
    TYPE_CHECKING, Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple,
)

from core.filter_card_config import (
    COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_CHANNEL_TYPE,
    COLUMN_DATA_POOL_LABEL, COLUMN_DIRECTION, COLUMN_FILE_NAME, COLUMN_ORDER,
    COLUMN_PARAMETER_SET, COLUMN_RESULT_SET,
)
from core.models import ChannelIdentity
from core.project_model import FilterSelection, SourceEntry
from selection.source_facets import (
    EMPTY_FACET_VALUE,
    build_metadata_facets,
    build_order_facet,
    build_range_facets,
    categorical_schema_fields,
    channel_identity_sort_key,
    order_matches,
    ranged_schema_fields,
    curve_field_value,
    value_in_range,
    with_empty_row,
)
from selection.parameter_sets import (
    ParameterSet, build_parameter_sets, orders_equal, parameter_set_for_signature,
    signature_value_matches,
    parameter_sets_from_traces, signature_matches_any, signatures_match,
)

if TYPE_CHECKING:
    from ._panel_facets import ResolvedFacets

Signature = Tuple[Tuple[str, Any], ...]

# Which TraceIdentity attribute each built-in Identity facet column reads
# (§1.33). Channel keeps its own dedicated path (channel_identities); these
# five are the ones ticket #37 story 9 adds as live facets.
IDENTITY_FACET_ATTR: Dict[str, str] = {
    COLUMN_DIRECTION: "direction",
    COLUMN_CHANNEL_TYPE: "channel_type",
    COLUMN_FILE_NAME: "file_name",
    COLUMN_DATA_POOL_LABEL: "data_pool_label",
    COLUMN_RESULT_SET: "result_set_label",
}


@dataclass(frozen=True)
class TraceIdentity:
    """
    Everything a FilterSelection can gate a Trace on, resolved once up front.

    Resolving the source lookup here (rather than inside trace_matches) is
    what keeps render()'s per-trace cost to a dict lookup plus the facet
    checks themselves -- sources_by_path() is built once per dock, not once
    per trace (see plan's "Otvorené riziká": render() is a hot path).
    """
    channel_identity: ChannelIdentity
    order: Optional[float]
    source: Optional[SourceEntry]
    # None for a trace with no declared x_quantity (a manually dropped live
    # channel, or one built before axis_projections existed) -- never gated,
    # same "undeclared draws unconditionally" rule as plot_model.Trace.x_quantity.
    result_kind: Optional[str] = None
    # parameter_sets.parameter_signature(kind, compute_spec without PARAM_ORDER) -- the
    # order is its own facet already, so it must not also split traces
    # computed with identical FFT/window settings into different Parameter
    # Sets. None when result_kind or compute_spec is missing.
    parameter_signature: Optional[Signature] = None
    # The built-in Identity facet values (§1.33), resolved once here the same
    # way `source` is: None means "this trace has nothing to judge for that
    # column" and it is never gated by it, exactly like an unoffered channel.
    direction: Optional[str] = None
    channel_type: Optional[str] = None
    file_name: Optional[str] = None
    data_pool_label: Optional[str] = None
    result_set_label: Optional[str] = None
    # The trace's own compute_spec, carried through so parameter_sets_from_traces
    # can build a ParameterSet's representative `params` dict without needing the
    # Trace itself (ticket #166) -- everything else this dataclass already
    # exposes is derived from it (order, parameter_signature).
    compute_spec: Optional[Dict[str, Any]] = None
    # The channel's position in its file; tells apart two channels of one file
    # that share a name. None when the curve does not say (#428).
    channel_index: Optional[int] = None
    # Settings the parameter signature does not carry (order width, rpm step,
    # DC removal), as the block recorded them. Empty when it recorded none (#428).
    computation: Mapping[str, Any] = field(default_factory=dict)


def identities_match(left: TraceIdentity, right: TraceIdentity) -> bool:
    """
    Whether two identities name one and the same curve: the same channel of
    the same measurement, the same Result Kind and order, computed with the
    same settings (signatures_match, tolerant of float noise).

    Anything either side cannot state -- no source, no Result Kind, no
    parameter signature -- is a miss, never a wildcard: the caller drops one
    of the two curves on a match, so "unknown" must not pass for "equal".
    """
    if left.source is None or right.source is None or left.source.id != right.source.id:
        return False
    if left.channel_identity != right.channel_identity:
        return False
    if None not in (left.channel_index, right.channel_index) and left.channel_index != right.channel_index:
        return False
    if left.result_kind is None or left.result_kind != right.result_kind:
        return False
    if (left.order is None) != (right.order is None):
        return False
    if left.order is not None and not orders_equal(left.order, right.order):
        return False
    if left.parameter_signature is None or right.parameter_signature is None:
        return False
    if not signatures_match(left.parameter_signature, right.parameter_signature):
        return False
    # Only settings both sides state are compared: a curve from a cache written
    # before they were recorded cannot be judged on them (ADR §1.101).
    return all(
        signature_value_matches(value, right.computation[key])
        for key, value in left.computation.items() if key in right.computation
    )


def format_result_kind(kind: str) -> str:
    """Display label for a Result Kind facet value, e.g. "order_cut" -> "Order Cut"."""
    return kind.replace("_", " ").title()


@dataclass(frozen=True)
class OfferedFacets:
    """
    The Channel/Order values the panel actually put a checkbox on screen for,
    and which range fields it put a min..max widget on screen for, for the
    (profile, dock) combo a mask is being built for.

    Needed because "unchecked" and "never asked about" are the same empty set
    seen from the selection alone, and for a mask they must mean opposite
    things: a graph whose Channel facet is not opted in at all (the default)
    offers nothing, and a mask that read that as "nothing checked" blanked
    every open graph. Travels with the selection, keyed the same way
    (FilterSelectionStore.selection_key), so a dock the panel has never populated for
    resolves to the empty default here -- offering nothing, hiding nothing.

    Frozen and value-comparable on purpose: gui.handlers.filter_routing puts it
    straight into a dock's _applied_filter_key, so repopulating the same
    selection against a different offering still counts as stale.
    """
    channel_identities: FrozenSet[ChannelIdentity] = field(default_factory=frozenset)
    orders: Tuple[float, ...] = ()
    result_kinds: FrozenSet[str] = field(default_factory=frozenset)
    # The actual ParameterSet objects last offered (not just their indices):
    # trace_matches has to resolve a trace's own parameter_signature to one of
    # these before it can even ask whether that one's index is checked. Not
    # hashable in general (ParameterSet is a plain dataclass), but OfferedFacets
    # is only ever compared with ``==`` (the R6' staleness key), never hashed.
    parameter_sets: Tuple[ParameterSet, ...] = ()
    # Which numeric/date fields currently have a range widget on the card at
    # all (ARCHITECTURE_DECISIONS §1.32: "rozšíri o rozsahové kolónky rovnako,
    # ako dnes nesie kanály a ordre") -- not the spans themselves, since a
    # span moving on its own (an untouched range tracking a growing pool)
    # must not force a redraw, only a field newly opted in via "Use as
    # Filter" appearing/disappearing from offer should.
    range_fields: FrozenSet[str] = field(default_factory=frozenset)
    # Built-in Identity facets other than Channel (§1.33): column key -> the
    # values the panel put a checkbox on screen for. Same role as
    # channel_identities -- it is what tells "unchecked" apart from "never
    # offered" for a mask.
    identity_values: Dict[str, FrozenSet[str]] = field(default_factory=dict)
    # Discrete metadata fields (ADR §1.56): schema field key -> the values the
    # panel put a checkbox on screen for. Same role as identity_values -- the
    # metadata family is a sixth gating family now, not the pre-§1.56 "empty
    # selection constrains nothing" block. EMPTY_FACET_VALUE is stripped out of
    # these sets (it lives in empty_buckets instead).
    metadata_values: Dict[str, FrozenSet[str]] = field(default_factory=dict)
    # The "(Empty)" bucket tokens on offer this round (ADR §1.56): a scalar
    # family's name (`order`, `result_kind`, `parameter_set`) or a keyed
    # family's column key. Part of the staleness key like every other offered
    # value -- a facet that starts offering "(Empty)" must force a redraw.
    empty_buckets: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def parameter_set_indices(self) -> FrozenSet[int]:
        return frozenset(ps.index for ps in self.parameter_sets)

    @property
    def parameter_set_signatures(self) -> Set[Signature]:
        return {ps.signature for ps in self.parameter_sets}


@dataclass(frozen=True)
class Facet:
    """
    One gating-facet family for the §1.29 / §1.56 mask rule -- the rationale for
    a single register instead of a per-family `if` in three functions is ADR
    §1.55.

    `hides` is the rule ("offered and not checked hides; a value-less trace
    falls to the '(Empty)' bucket") spelled once. `offered_field` /
    `checked_field` name the `OfferedFacets` / `FilterSelection` attributes the
    family reads, and a test cross-checks `checked_field` against
    `serialize_selection`'s keys.

    `offered_from_resolved` builds this family's `OfferedFacets` value from the
    `ResolvedFacets` the panel already holds (the `offering_from_facets` loop);
    `apply_defaults` folds this family's §1.29 default-check heuristic onto a
    `DefaultedChecks` in place (the `resolve_default_checks` loop). Parameter Set
    and keyed Identity keep their extra step (signature->index, per-column loop)
    inside these callables, so the register stays a flat six-row list (§1.55,
    §1.56).
    """
    name: str
    offered_field: str
    checked_field: str
    hides: Callable[[TraceIdentity, FilterSelection, "OfferedFacets", Dict[str, Dict[str, Any]]], bool]
    offered_from_resolved: Callable[["ResolvedFacets"], Any]
    # The "(Empty)" bucket tokens this family offers for one `ResolvedFacets`
    # (ADR §1.56): a one-element set with the family name for the scalar
    # families, or one key per keyed column that has a value-less trace. Empty
    # when every trace carries a value.
    offers_empty: Callable[["ResolvedFacets"], Set[str]]
    apply_defaults: Callable[["DefaultedChecks", "OfferedFacets", Optional["OfferedFacets"]], None]
    # Which of this family's offered values currently have zero effect --
    # every identity carrying one is already hidden by some OTHER family's own
    # checks (facet_value_availability, #117); a value no identity carries is
    # never dead. Column key (Filter card key for the scalar families, the
    # keyed families' own key(s)) -> its dead values; a family with nothing
    # dead this round contributes no entries. Kept in the register rather than
    # a seventh hand-written traversal, same reasoning as every other row here
    # (§1.55): a family's signature/schema quirks (Parameter Set's index
    # resolution, Metadata's per-source read) stay local to its own closure.
    dead_values: Callable[[List[TraceIdentity], FilterSelection, Dict[str, Dict[str, Any]],
                          "OfferedFacets"], Dict[str, Set[Any]]]


def _default_step(current: Set[Any], offered: Set[Any], previously_offered: Optional[Set[Any]]) -> None:
    """
    One gating family's §1.29 default, in place on `current`:

    - first real populate (`previously_offered is None`): fall back to the whole
      offering, unless the remembered picks already overlap it -- a restored
      project must not re-tick a box deliberately saved as off;
    - a later, wider offering: tick only what `previously_offered` did not carry.
      A value dropped onto the graph since was never rejected; a deliberate
      uncheck of a still-offered value was.

    Plain set maths on purpose -- `resolve_default_checks` never used
    `order_matches` here, only `trace_matches` does (§1.55, float tolerance not
    unified).
    """
    if not offered:
        return
    if previously_offered is None:
        if not (current & offered):
            current |= offered
    else:
        current |= offered - previously_offered


def _fold_empty_default(token: str, checks: "DefaultedChecks", offered: "OfferedFacets",
                        previously_offered: Optional["OfferedFacets"]) -> None:
    """
    The §1.29 default heuristic for one facet's "(Empty)" bucket (ADR §1.56):
    the sentinel is just another newly-offered value -- ticked the first time
    the facet offers it, left alone once the user has had a chance to uncheck
    it. `checks.checked_empty_buckets` is one flat set across families, so this
    runs per token without disturbing another family's bucket.
    """
    _default_step(
        checks.checked_empty_buckets,
        {token} if token in offered.empty_buckets else set(),
        None if previously_offered is None
        else ({token} if token in previously_offered.empty_buckets else set()),
    )


def _permissive_selection(selection: FilterSelection, checked_field: str, key: Optional[str],
                          full_value: Any, empty_token: str) -> FilterSelection:
    """
    A copy of `selection` with one gating facet -- or, for a keyed family, one
    column inside it -- neutralised: `checked_field` (`key` present too) set to
    `full_value`, the whole set of values that family offers, so `trace_matches`
    against the result reports only what every OTHER family's current checks
    would still hide. Comparing against the *original* selection would just
    re-derive "is this box itself unchecked"; this is the one building block
    every `dead_values` closure below needs to ask instead "would
    checking/unchecking this box still change anything on screen".
    """
    sel = replace(selection)
    if key is None:
        setattr(sel, checked_field, full_value)
    else:
        checked = dict(getattr(selection, checked_field))
        checked[key] = full_value
        setattr(sel, checked_field, checked)
    sel.checked_empty_buckets = set(selection.checked_empty_buckets) | {empty_token}
    return sel


def _scalar_facet(name: str, offered_field: str, checked_field: str,
                  read: Callable[[TraceIdentity], Any], *,
                  resolved_attr: str, normalize: Callable[[List[Any]], Any],
                  column_key: str,
                  offered_test: Optional[Callable[[Any, Any], bool]] = None,
                  checked_test: Optional[Callable[[Any, Any], bool]] = None) -> Facet:
    """
    A family whose value is a single scalar read straight off the identity
    (Channel, Result Kind, Order). Order passes `order_matches` for both `hides`
    tests: a float32 axis value never compares == to the float the facet was
    built from (K1). `resolved_attr` / `normalize` say how to lift the value out
    of `ResolvedFacets`; the default heuristic compares against `offered_field`
    directly, which for these three families is already a plain set. `column_key`
    is the Filter card column (core.filter_card_config.COLUMN_*) `dead_values`
    reports its dead values under -- distinct from `name`, which is the "(Empty)"
    bucket token these families already use for `checked_empty_buckets`.
    """
    offered_test = offered_test or (lambda value, offered_values: value in offered_values)
    checked_test = checked_test or (lambda value, checked_values: value in checked_values)

    def hides(identity: TraceIdentity, selection: FilterSelection, offered: "OfferedFacets",
              schema: Dict[str, Dict[str, Any]]) -> bool:
        value = read(identity)
        if value is None:
            return (name in offered.empty_buckets
                    and name not in selection.checked_empty_buckets)
        return (offered_test(value, getattr(offered, offered_field))
                and not checked_test(value, getattr(selection, checked_field)))

    def offered_from_resolved(facets: "ResolvedFacets") -> Any:
        raw = [v for v in (getattr(facets, resolved_attr) or []) if v != EMPTY_FACET_VALUE]
        return normalize(raw)

    def offers_empty(facets: "ResolvedFacets") -> Set[str]:
        return {name} if EMPTY_FACET_VALUE in (getattr(facets, resolved_attr) or []) else set()

    def apply_defaults(checks: "DefaultedChecks", offered: "OfferedFacets",
                       previously_offered: Optional["OfferedFacets"]) -> None:
        _default_step(
            getattr(checks, checked_field),
            set(getattr(offered, offered_field)),
            None if previously_offered is None else set(getattr(previously_offered, offered_field)),
        )
        _fold_empty_default(name, checks, offered, previously_offered)

    def dead_values(identities: List[TraceIdentity], selection: FilterSelection,
                    schema: Dict[str, Dict[str, Any]], offered: "OfferedFacets") -> Dict[str, Set[Any]]:
        full_value = set(getattr(offered, offered_field))
        permissive = _permissive_selection(selection, checked_field, None, full_value, name)
        survivors = [identity for identity in identities
                    if trace_matches(identity, permissive, schema, offered)]
        carried = [read(identity) for identity in identities if read(identity) is not None]
        present = [read(identity) for identity in survivors if read(identity) is not None]
        dead = {value for value in getattr(offered, offered_field)
                if offered_test(value, carried) and not offered_test(value, present)}
        if (name in offered.empty_buckets
                and any(read(identity) is None for identity in identities)
                and not any(read(identity) is None for identity in survivors)):
            dead.add(EMPTY_FACET_VALUE)
        return {column_key: dead} if dead else {}

    return Facet(name, offered_field, checked_field, hides, offered_from_resolved,
                 offers_empty, apply_defaults, dead_values)


def _identity_columns_facet() -> Facet:
    """
    The built-in Identity facets other than Channel (Direction, Channel type,
    File name, Data Pool label, Result set -- §1.33): one register row, the
    per-column loop kept inside. Each column gates exactly like Channel; a trace
    with no value for a column (no source, a blank direction) lands in that
    column's "(Empty)" bucket and is gated through it (ADR §1.56).
    """
    def hides(identity: TraceIdentity, selection: FilterSelection, offered: "OfferedFacets",
              schema: Dict[str, Dict[str, Any]]) -> bool:
        for key, offered_values in offered.identity_values.items():
            value = getattr(identity, IDENTITY_FACET_ATTR[key], None)
            if value is None:
                if key in offered.empty_buckets and key not in selection.checked_empty_buckets:
                    return True
            elif (value in offered_values
                  and value not in selection.checked_identity_values.get(key, set())):
                return True
        return False

    def offered_from_resolved(facets: "ResolvedFacets") -> Dict[str, FrozenSet[str]]:
        return {key: frozenset(v for v in values if v != EMPTY_FACET_VALUE)
                for key, values in (getattr(facets, "identity") or {}).items()}

    def offers_empty(facets: "ResolvedFacets") -> Set[str]:
        return {key for key, values in (getattr(facets, "identity") or {}).items()
                if EMPTY_FACET_VALUE in values}

    def apply_defaults(checks: "DefaultedChecks", offered: "OfferedFacets",
                       previously_offered: Optional["OfferedFacets"]) -> None:
        for key, offered_values in offered.identity_values.items():
            current = checks.checked_identity_values.setdefault(key, set())
            prior = (None if previously_offered is None
                     else set(previously_offered.identity_values.get(key, frozenset())))
            _default_step(current, set(offered_values), prior)
            _fold_empty_default(key, checks, offered, previously_offered)

    def dead_values(identities: List[TraceIdentity], selection: FilterSelection,
                    schema: Dict[str, Dict[str, Any]], offered: "OfferedFacets") -> Dict[str, Set[Any]]:
        dead: Dict[str, Set[Any]] = {}
        for key, offered_values in offered.identity_values.items():
            permissive = _permissive_selection(
                selection, "checked_identity_values", key, set(offered_values), key)
            survivors = [identity for identity in identities
                        if trace_matches(identity, permissive, schema, offered)]
            carried = {getattr(identity, IDENTITY_FACET_ATTR[key], None) for identity in identities}
            present = {getattr(identity, IDENTITY_FACET_ATTR[key], None) for identity in survivors}
            dead_column = {value for value in offered_values
                           if value in carried and value not in present}
            if key in offered.empty_buckets and None in carried and None not in present:
                dead_column.add(EMPTY_FACET_VALUE)
            if dead_column:
                dead[key] = dead_column
        return dead

    return Facet("identity_columns", "identity_values", "checked_identity_values",
                 hides, offered_from_resolved, offers_empty, apply_defaults, dead_values)


def _snapped_signatures(signatures: Iterable[Signature],
                        parameter_sets: Tuple[ParameterSet, ...]) -> Set[Signature]:
    """`signatures` with each one replaced by the signature of the offered
    `ParameterSet` it matches (float-noise tolerant); one that matches none is
    kept as it is, so a set that is off the dock for now stays remembered."""
    snapped: Set[Signature] = set()
    for signature in signatures:
        matched = parameter_set_for_signature(signature, parameter_sets)
        snapped.add(signature if matched is None else matched.signature)
    return snapped


def _parameter_set_facet() -> Facet:
    """
    Parameter Set (plan F4): the trace's own `parameter_signature` is resolved
    to one of the offered `ParameterSet`s (float-noise tolerant, K1) and hidden
    when that set's signature is unchecked. Checks are keyed by signature, not
    by the "Parameter Set N" index, because the index is re-numbered every round
    from what is on offer (#349). A trace whose signature matches no
    offered set (a dropped live channel, one built before compute_spec was
    stamped, or a settings combination the current offering does not list)
    lands in the "(Empty)" bucket (ADR §1.56).
    """
    def hides(identity: TraceIdentity, selection: FilterSelection, offered: "OfferedFacets",
              schema: Dict[str, Dict[str, Any]]) -> bool:
        matched = parameter_set_for_signature(identity.parameter_signature, offered.parameter_sets)
        if matched is None:
            return ("parameter_set" in offered.empty_buckets
                    and "parameter_set" not in selection.checked_empty_buckets)
        return not signature_matches_any(matched.signature, selection.checked_parameter_set_signatures)

    def offered_from_resolved(facets: "ResolvedFacets") -> Tuple[ParameterSet, ...]:
        return tuple(getattr(facets, "parameter_sets") or [])

    def offers_empty(facets: "ResolvedFacets") -> Set[str]:
        return {"parameter_set"} if getattr(facets, "parameter_set_has_empty", False) else set()

    def apply_defaults(checks: "DefaultedChecks", offered: "OfferedFacets",
                       previously_offered: Optional["OfferedFacets"]) -> None:
        # Snap every signature onto the offered set it matches first, so the
        # plain set maths in _default_step cannot tell float noise apart from a
        # different setting.
        checks.checked_parameter_set_signatures = _snapped_signatures(
            checks.checked_parameter_set_signatures, offered.parameter_sets)
        _default_step(
            checks.checked_parameter_set_signatures,
            offered.parameter_set_signatures,
            None if previously_offered is None
            else _snapped_signatures(previously_offered.parameter_set_signatures, offered.parameter_sets),
        )
        _fold_empty_default("parameter_set", checks, offered, previously_offered)

    def dead_values(identities: List[TraceIdentity], selection: FilterSelection,
                    schema: Dict[str, Dict[str, Any]], offered: "OfferedFacets") -> Dict[str, Set[Any]]:
        full_value = offered.parameter_set_signatures
        permissive = _permissive_selection(
            selection, "checked_parameter_set_signatures", None, full_value, "parameter_set")
        def indices(of: List[TraceIdentity]) -> Set[Optional[int]]:
            # The offered set index each identity resolves to; None for "(Empty)".
            found: Set[Optional[int]] = set()
            for identity in of:
                matched = parameter_set_for_signature(identity.parameter_signature, offered.parameter_sets)
                found.add(None if matched is None else matched.index)
            return found

        survivors = [identity for identity in identities
                    if trace_matches(identity, permissive, schema, offered)]
        carried, present = indices(identities), indices(survivors)
        dead = {ps.index for ps in offered.parameter_sets
                if ps.index in carried and ps.index not in present}
        if "parameter_set" in offered.empty_buckets and None in carried and None not in present:
            dead.add(EMPTY_FACET_VALUE)
        return {COLUMN_PARAMETER_SET: dead} if dead else {}

    return Facet("parameter_set", "parameter_sets", "checked_parameter_set_signatures",
                 hides, offered_from_resolved, offers_empty, apply_defaults, dead_values)


def _metadata_columns_facet() -> Facet:
    """
    Discrete metadata fields (ADR §1.56): the sixth gating family. Each opted-in
    categorical schema column on the card gates exactly like an Identity column
    -- offered and unchecked hides the trace carrying that value; a trace whose
    source has no value for the column, or no source at all, lands in the
    column's "(Empty)" bucket. This replaces §1.29's "metadata imposes nothing
    when its selection is empty" rule.

    `hides` reads `schema` (the register's fourth argument, ignored by the other
    families) because a metadata value is not pre-resolved onto `TraceIdentity`
    the way an Identity value is -- it is read per field off the source here.
    """
    def hides(identity: TraceIdentity, selection: FilterSelection, offered: "OfferedFacets",
              schema: Dict[str, Dict[str, Any]]) -> bool:
        source = identity.source
        for key, offered_values in offered.metadata_values.items():
            value = (None if source is None else curve_field_value(
                source, schema, key, identity.channel_identity, identity.channel_index))
            if value is None:
                if key in offered.empty_buckets and key not in selection.checked_empty_buckets:
                    return True
            elif (value in offered_values
                  and value not in selection.checked_metadata_values.get(key, set())):
                return True
        return False

    def offered_from_resolved(facets: "ResolvedFacets") -> Dict[str, FrozenSet[str]]:
        return {key: frozenset(v for v in values if v != EMPTY_FACET_VALUE)
                for key, values in (getattr(facets, "metadata") or {}).items()}

    def offers_empty(facets: "ResolvedFacets") -> Set[str]:
        return {key for key, values in (getattr(facets, "metadata") or {}).items()
                if EMPTY_FACET_VALUE in values}

    def apply_defaults(checks: "DefaultedChecks", offered: "OfferedFacets",
                       previously_offered: Optional["OfferedFacets"]) -> None:
        for key, offered_values in offered.metadata_values.items():
            current = checks.checked_metadata_values.setdefault(key, set())
            prior = (None if previously_offered is None
                     else set(previously_offered.metadata_values.get(key, frozenset())))
            _default_step(current, set(offered_values), prior)
            _fold_empty_default(key, checks, offered, previously_offered)

    def dead_values(identities: List[TraceIdentity], selection: FilterSelection,
                    schema: Dict[str, Dict[str, Any]], offered: "OfferedFacets") -> Dict[str, Set[Any]]:
        dead: Dict[str, Set[Any]] = {}
        for key, offered_values in offered.metadata_values.items():
            permissive = _permissive_selection(
                selection, "checked_metadata_values", key, set(offered_values), key)
            values = [None if identity.source is None else curve_field_value(
                          identity.source, schema, key, identity.channel_identity,
                          identity.channel_index)
                      for identity in identities]
            carried = set(values)
            present = {value for identity, value in zip(identities, values)
                       if trace_matches(identity, permissive, schema, offered)}
            dead_column = {value for value in offered_values
                           if value in carried and value not in present}
            if key in offered.empty_buckets and None in carried and None not in present:
                dead_column.add(EMPTY_FACET_VALUE)
            if dead_column:
                dead[key] = dead_column
        return dead

    return Facet("metadata_columns", "metadata_values", "checked_metadata_values",
                 hides, offered_from_resolved, offers_empty, apply_defaults, dead_values)


# The six gating-facet families of §1.29 / §1.56, in the §1.33 order: Channel,
# the built-in Identity columns, Order, Analysis type / Result Kind, Parameter
# Set, discrete metadata. `trace_matches`, `resolve_default_checks` and
# `offering_from_facets` are each one loop over this list. Ranges are still not
# here -- a range has bounds, not a discrete value list, so "a new value ticks
# itself" does not apply; it stays a hand-written block after the loop.
GATING_FACETS: Tuple[Facet, ...] = (
    _scalar_facet("channel", "channel_identities", "checked_channel_identities",
                  lambda identity: identity.channel_identity,
                  resolved_attr="channel", column_key=COLUMN_CHANNEL,
                  normalize=lambda values: frozenset(tuple(v) for v in values)),
    _identity_columns_facet(),
    _scalar_facet("order", "orders", "checked_orders",
                  lambda identity: identity.order,
                  resolved_attr="orders", column_key=COLUMN_ORDER,
                  normalize=lambda values: tuple(sorted(float(v) for v in values)),
                  offered_test=lambda order, offered_orders: order_matches(order, offered_orders),
                  checked_test=lambda order, checked_orders: order_matches(order, checked_orders)),
    _scalar_facet("result_kind", "result_kinds", "checked_result_kinds",
                  lambda identity: identity.result_kind,
                  resolved_attr="result_kinds", column_key=COLUMN_ANALYSIS_TYPE,
                  normalize=frozenset),
    _parameter_set_facet(),
    _metadata_columns_facet(),
)


@dataclass
class DefaultedChecks:
    """
    Every gating facet's checked state after populate_facets' §1.29 / §1.56
    default heuristic has run -- what resolve_default_checks returns for the
    panel to write straight back onto its FilterSelection.

    Ranges stay absent: a range is "touched" only by an explicit edit
    (ARCHITECTURE_DECISIONS §1.32), never auto-checked. Metadata is here now
    (§1.56): it gates like Identity, so a newly-offered value ticks itself.

    Plain mutable sets, not frozen: the panel's checkbox handlers .add/.discard
    them in place after they land on the FilterSelection.
    """
    checked_channel_identities: Set[ChannelIdentity]
    checked_orders: Set[float]
    checked_result_kinds: Set[str]
    checked_parameter_set_signatures: Set[Signature]
    # Built-in Identity facets other than Channel (§1.33): column key -> checked
    # values, after the same §1.29 default heuristic. Defaulted so the four
    # older fields' call sites (and tests) need no change.
    checked_identity_values: Dict[str, Set[str]] = field(default_factory=dict)
    # Discrete metadata fields (§1.56): schema field key -> checked values, same
    # default heuristic as Identity.
    checked_metadata_values: Dict[str, Set[str]] = field(default_factory=dict)
    # The "(Empty)" bucket tokens ticked for this round (§1.56) -- family names
    # for the scalar families, column keys for the keyed ones.
    checked_empty_buckets: Set[str] = field(default_factory=set)


def selection_from_defaulted(defaulted: DefaultedChecks,
                             checked_ranges: Dict[str, Tuple[Any, Any]]) -> FilterSelection:
    """
    A `FilterSelection` view of one round's `DefaultedChecks` -- what
    `resolve_panel_render` hands `facet_value_availability` as "the checks that
    are about to land on screen". `DefaultedChecks` has no `checked_ranges`
    field (ranges are never auto-checked, ADR §1.32/§1.42), so the caller's own
    live selection supplies that one field; every other field comes straight
    off `defaulted`.
    """
    return FilterSelection(
        checked_metadata_values=defaulted.checked_metadata_values,
        checked_identity_values=defaulted.checked_identity_values,
        checked_channel_identities=defaulted.checked_channel_identities,
        checked_orders=defaulted.checked_orders,
        checked_parameter_set_signatures=defaulted.checked_parameter_set_signatures,
        checked_result_kinds=defaulted.checked_result_kinds,
        checked_ranges=dict(checked_ranges),
        checked_empty_buckets=defaulted.checked_empty_buckets,
    )


def offering_from_facets(facets: "ResolvedFacets") -> OfferedFacets:
    """
    The OfferedFacets record for one populate_facets() call, built by looping
    GATING_FACETS over the ResolvedFacets `resolve_panel_render` already holds
    (§1.55) -- carries no Qt so the "what is on offer" half of §1.29 can be
    exercised without a QApplication.

    Only `range_fields` is filled by hand: ranges are not a gating facet (an
    untouched range constrains nothing, the opposite rule) so they have no row
    in the register. `empty_buckets` is the union of every family's offered
    "(Empty)" tokens (§1.56).
    """
    offered = {facet.offered_field: facet.offered_from_resolved(facets)
               for facet in GATING_FACETS}
    empty_buckets: Set[str] = set()
    for facet in GATING_FACETS:
        empty_buckets |= facet.offers_empty(facets)
    return OfferedFacets(range_fields=frozenset(facets.ranges or {}),
                         empty_buckets=frozenset(empty_buckets), **offered)


def resolve_default_checks(offered: OfferedFacets, previously_offered: Optional[OfferedFacets],
                           remembered: FilterSelection, *, allow_default: bool) -> DefaultedChecks:
    """
    Which gating-facet values (Channel, the built-in Identity columns, Order,
    Result Kind, Parameter Set, discrete metadata -- and every family's
    "(Empty)" bucket, §1.56) to tick on the user's behalf for this
    populate_facets() call -- pure (no Qt, no ``self``), so the tickets that
    still have to reach into this decision (card configuration, ordering/widgets,
    default sets) can test it without a QApplication.

    ``allow_default`` off entirely for a replay that has already populated this
    combo for real -- otherwise a tab switch would re-tick a box the user just
    unchecked. When it is on, every family runs the same two-shape heuristic,
    spelled once in ``_default_step`` (§1.29). Keyed Identity runs it per column.
    """
    checks = DefaultedChecks(
        checked_channel_identities=set(remembered.checked_channel_identities),
        checked_orders=set(remembered.checked_orders),
        checked_result_kinds=set(remembered.checked_result_kinds),
        checked_parameter_set_signatures=set(remembered.checked_parameter_set_signatures),
        checked_identity_values={
            key: set(values) for key, values in remembered.checked_identity_values.items()
        },
        checked_metadata_values={
            key: set(values) for key, values in remembered.checked_metadata_values.items()
        },
        checked_empty_buckets=set(remembered.checked_empty_buckets),
    )

    if allow_default:
        for facet in GATING_FACETS:
            facet.apply_defaults(checks, offered, previously_offered)

    checks.checked_identity_values = {
        key: values for key, values in checks.checked_identity_values.items() if values
    }
    checks.checked_metadata_values = {
        key: values for key, values in checks.checked_metadata_values.items() if values
    }
    return checks


def _range_selection_matches(identity: "TraceIdentity", schema: Dict[str, Dict[str, Any]],
                             selection: FilterSelection) -> bool:
    """
    Whether `identity`'s source (its own channel, for a channel-layer
    field) survives every touched range facet in
    `selection.checked_ranges` -- a key's presence there is the "user moved this
    range" flag (an untouched range is simply absent, see
    FilterSelection.checked_ranges). Takes `selection`, not the extracted dict,
    so `trace_matches` names no `checked_*` attribute directly (ADR §1.55 pin,
    test_architecture.py).

    Unlike selection.source_facets.apply_range_facets (the batch
    resolver's own use of the same bounds, which drops a source with no
    value), a trace whose source cannot be judged -- no source at all, or a
    source missing this particular field -- passes: ARCHITECTURE_DECISIONS
    §1.29/§1.32, "nemám čo posúdiť" never means "skry".
    """
    checked_ranges = selection.checked_ranges
    if not checked_ranges:
        return True
    fields = ranged_schema_fields(schema)
    for key, bounds in checked_ranges.items():
        if key not in fields or not bounds or identity.source is None:
            continue
        if value_in_range(identity.source, key, fields[key], bounds,
                          identity.channel_identity, identity.channel_index) is False:
            return False
    return True


def missing_range_value_fields(identities: List["TraceIdentity"], schema: Dict[str, Dict[str, Any]],
                               checked_ranges: Dict[str, Tuple[Any, Any]]) -> List[str]:
    """
    Which touched range facets have at least one of `identities` whose source
    could not be judged against it (no source at all, or the field itself is
    missing/unparseable) -- what gui.handlers.filter_routing logs once per
    (dock, field) when it actually rebuilds a dock's mask.

    Kept separate from trace_matches on purpose: trace_matches runs inside
    render()'s per-trace hot loop and must stay a pure function with no
    side effects (ARCHITECTURE_DECISIONS §1.32), so the "log this once"
    decision lives here instead, computed once per mask rebuild.
    """
    if not checked_ranges:
        return []
    fields = ranged_schema_fields(schema)
    missing = []
    for key, bounds in checked_ranges.items():
        if key not in fields or not bounds:
            continue
        config = fields[key]
        has_missing = any(
            identity.source is None or value_in_range(
                identity.source, key, config, bounds,
                identity.channel_identity, identity.channel_index) is None
            for identity in identities
        )
        if has_missing:
            missing.append(key)
    return sorted(missing)


def trace_matches(identity: TraceIdentity, selection: FilterSelection,
                  schema: Dict[str, Dict[str, Any]], offered: OfferedFacets) -> bool:
    """
    Whether `identity` survives `selection` -- no second implementation of the
    matching rules, only the plumbing to call the existing ones on a single
    trace instead of a list of sources:

    - Channel hides a trace only when its identity was on offer and is not
      checked. A channel `offered` says nothing about (an empty Channel facet
      because it is not opted in; a channel dropped onto the graph after the
      user last clicked) cannot have been rejected, so it passes.
    - Order works the same way, and membership in the offering goes through
      order_matches too rather than `in`: an order read off a float32 axis
      never compares == to the float the facet was built from (K1). A trace
      with no order at all (time domain) is never gated.
    - Result Kind and Parameter Set (plan F4) both gate the same way as
      Channel/Order, not like Metadata/the pre-F4 project-wide Parameter Set
      picker (io_modules.parameter_sets.filter_result_sets_by_parameter_set),
      where an empty selection imposes no constraint -- that rule stays for
      the primary-config resolver in live_channel_drop, which is not a mask. A
      trace with no result_kind/parameter_signature at all (a dropped live
      channel, or one built before x_quantity/compute_spec were stamped) is
      never gated by either.
    - The built-in Identity facets other than Channel (Direction, Channel type,
      File name, Data Pool label, Result set -- §1.33) gate exactly like
      Channel: hidden only when this trace's value for that column was on offer
      and is not checked. A trace with no value for a column (no source, a
      blank direction) is never gated by it.
    - Discrete metadata fields gate exactly like the Identity columns now (ADR
      §1.56): offered and unchecked hides the trace carrying that value; a
      trace whose source has no value for the field, or no source at all,
      lands in the field's "(Empty)" bucket. The pre-§1.56 "an unchecked
      metadata field imposes no constraint" rule is gone.
    - Every gating family also carries an "(Empty)" bucket (§1.56): a
      value-less trace is hidden when the facet offered "(Empty)" and the user
      unchecked it -- this is what finally lets unchecking "(Empty)" in Order
      hide a time record on a mixed dock.
    - A numeric/date facet the user has actually moved (selection.checked_ranges,
      keyed by field -- presence is the "touched" flag, ARCHITECTURE_DECISIONS
      §1.32) hides a trace only when its source resolves to a value outside
      [lo, hi]; a trace with no resolvable value for that field passes, unlike
      the batch resolver's apply_range_facets which drops it (§1.29 again, one
      level down: a range is only a positive assertion for the sources it can
      actually judge).

    `offered` has no default: a caller that has no offering to pass is asking
    for the pre-§1.29 "empty means nothing survives" behaviour by accident,
    which is exactly the bug this argument exists to make impossible.

    ADR §1.55 / §1.56: the six gating families (Channel, Identity columns,
    Order, Result Kind, Parameter Set, discrete metadata) are one loop over
    GATING_FACETS, each family's read/offer/check folded into its own `hides`.
    Only ranges keep the opposite rule (an untouched span constrains nothing)
    and stay a hand-written block below.
    """
    for facet in GATING_FACETS:
        if facet.hides(identity, selection, offered, schema):
            return False

    if not _range_selection_matches(identity, schema, selection):
        return False

    return True


def facet_value_availability(identities: List[TraceIdentity], selection: FilterSelection,
                             schema: Dict[str, Dict[str, Any]], offered: OfferedFacets
                             ) -> Dict[str, Set[Any]]:
    """
    Which offered facet value, per Filter card column, currently has zero
    effect left to give: every identity that carries it is already hidden by
    some OTHER column's own checks (a Direction unchecked hides a channel that
    only ever measures that direction, ticket #needs-triage "sivé kolónky bez
    efektu", #117). The Filter panel greys that value's checkbox rather than
    pretending a click on it still changes the plot.

    `identities` is the drawn traces the card gates: the focused dock's own for
    a Local card, every open dock's for a Global one (#117). Only a value some
    identity actually carries can be dead -- a Global card also offers values
    from the whole Data Pool and the Result Pool that no open dock draws, and
    those say nothing about the plot, so they are never greyed. For a Local card
    every offered value comes from `identities`, so the test changes nothing.

    One loop over GATING_FACETS (§1.55), same as trace_matches / resolve_default
    _checks / offering_from_facets: each family's own `dead_values` closure
    knows how to neutralise itself (`_permissive_selection`) and read its own
    values off an identity (Parameter Set's signature resolution, Metadata's
    per-source read) -- this function does not re-derive any of that. Returns
    column key -> the set of its dead values, keys with nothing dead omitted.
    """
    dead: Dict[str, Set[Any]] = {}
    for facet in GATING_FACETS:
        dead.update(facet.dead_values(identities, selection, schema, offered))
    return dead


def facets_from_traces(identities: List[TraceIdentity],
                       schema: Dict[str, Dict[str, Any]],
                       allowed_keys: Optional[Iterable[str]] = None
                       ) -> Tuple[Dict[str, List[str]], List[ChannelIdentity], List[float],
                                  List[str], List[ParameterSet], Dict[str, Tuple[Any, Any]]]:
    """
    The facets a Local filter on a regular graph offers: only what its own
    traces actually carry, not the full Data Pool/result-set universe
    build_channel_facet/build_order_facet answer for Compare (plan's "z
    kriviek, nie cez build_channel_facet/build_order_facet"). Returns
    (metadata_facets, channel_facet, order_facet, kind_facet, parameter_sets,
    range_facets).

    `identities` is the caller's `TraceIdentity` for each of its own traces,
    resolved once via `identity_for_trace` before this is called (ADR ticket
    #166) -- this module reads only the identity, never the Trace itself.

    `allowed_keys` narrows the metadata/range offering to the Local card's own
    columns (ARCHITECTURE_DECISIONS §1.32, ticket #41). Channel/Order/Result
    Kind/Parameter Set stay as they are -- the card's Identity/Calculated
    columns govern them only from #42/#45 on.

    Every discrete family's value list gains an EMPTY_FACET_VALUE row when at
    least one trace carries no value for it (ADR §1.56): a source-less trace for
    metadata, a time-domain trace for Order, an undeclared-x_quantity trace for
    Result Kind. The row is left off when every trace has a value.
    """
    sources: List[SourceEntry] = []
    seen_source_ids = set()
    for identity in identities:
        if identity.source is not None and identity.source.id not in seen_source_ids:
            seen_source_ids.add(identity.source.id)
            sources.append(identity.source)

    metadata_facets = build_metadata_facets(sources, schema, allowed_keys)
    if any(identity.source is None for identity in identities):
        # A source-less trace has no value for any metadata field -- add the
        # "(Empty)" row to every field that already offers real values.
        metadata_facets = {key: with_empty_row([v for v in values if v != EMPTY_FACET_VALUE], True)
                           for key, values in metadata_facets.items()}

    channel_facet = sorted(
        {identity.channel_identity for identity in identities},
        key=channel_identity_sort_key,
    )
    order_facet = with_empty_row(
        sorted({identity.order for identity in identities if identity.order is not None}),
        any(identity.order is None for identity in identities))
    kind_facet = with_empty_row(
        sorted({identity.result_kind for identity in identities if identity.result_kind is not None}),
        any(identity.result_kind is None for identity in identities))
    parameter_sets = parameter_sets_from_traces(identities)
    range_facets = build_range_facets(sources, schema, allowed_keys)

    return metadata_facets, channel_facet, order_facet, kind_facet, parameter_sets, range_facets


def traces_without_parameter_set(identities: List[TraceIdentity],
                                 parameter_sets: Iterable[ParameterSet]) -> bool:
    """
    Whether any of `identities` has a parameter signature that resolves to none
    of `parameter_sets` (or no signature at all) -- the "(Empty)" bucket flag for
    the Parameter Set family (ADR §1.56). Kept out of `facets_from_traces` /
    `global_calculated_facets` so their return shape does not change: the
    Parameter Set offering is a list of objects that cannot carry the sentinel
    row in band the way Order's float list can.
    """
    sets = tuple(parameter_sets)
    return any(
        parameter_set_for_signature(identity.parameter_signature, sets) is None
        for identity in identities
    )


def identity_facets_from_traces(identities: List[TraceIdentity],
                                keys: Iterable[str]) -> Dict[str, List[str]]:
    """
    The built-in Identity facets (Direction, Channel type, File name, Data Pool
    label, Result set -- §1.33) a Local card offers: the distinct values its
    own traces carry for each column in `keys`, sorted, empty facets left out.
    A column that has real values and at least one trace with none gains an
    EMPTY_FACET_VALUE row (ADR §1.56). The Global counterpart reads the pool
    instead (selection.source_facets.build_identity_facets_from_sources).

    `identities` is resolved once by the caller via `identity_for_trace`
    (passing `result_set_labels` there, ticket #166) -- this only reads the
    resolved values off it.
    """
    facets: Dict[str, List[str]] = {}
    for key in keys:
        attr = IDENTITY_FACET_ATTR.get(key)
        if attr is None:
            continue
        values = sorted({getattr(identity, attr) for identity in identities if getattr(identity, attr)})
        if values:
            facets[key] = with_empty_row(
                values, any(not getattr(identity, attr) for identity in identities))
    return facets


def global_parameter_sets(project, identities: List[TraceIdentity]) -> List[ParameterSet]:
    """
    The Parameter Sets a Global card offers (ADR §1.36): the project's, at their
    stable project-wide index, plus one extra (numbered after the last) per
    dock-drawn settings signature no result set accounts for. A dock trace that
    maps onto a project set adds nothing -- signatures_match bridges the two
    signature dialects.

    `identities` is every open dock's own `TraceIdentity`, resolved once by the
    caller (ticket #166).
    """
    parameter_sets = build_parameter_sets(project, [ref.id for ref in project.result_sets])
    next_index = max((ps.index for ps in parameter_sets), default=0) + 1

    for identity in identities:
        signature = identity.parameter_signature
        if signature is None:
            continue
        if parameter_set_for_signature(signature, tuple(parameter_sets)) is not None:
            continue
        parameter_sets.append(ParameterSet(
            index=next_index, signature=signature,
            params=dict(identity.compute_spec or {}), kind=identity.result_kind or "",
        ))
        next_index += 1
    return parameter_sets


def global_calculated_facets(project, identities: List[TraceIdentity]
                             ) -> Tuple[List[Any], List[Any], List[ParameterSet]]:
    """
    A Global card's Order / Analysis type / Parameter set offering (ADR §1.36):
    the union of what every open dock draws and what the project's Result Pool
    holds. The single path that decides this universe.

    `identities` is every open dock's own `TraceIdentity`, resolved once by the
    caller via `identity_for_trace` (ticket #166).

    Order / Analysis type gain an EMPTY_FACET_VALUE row when an open dock draws
    a curve that carries no order / no result kind (ADR §1.56).
    """
    orders = {identity.order for identity in identities if identity.order is not None}
    orders.update(build_order_facet(project.result_sets))

    kinds = {identity.result_kind for identity in identities if identity.result_kind is not None}
    kinds.update(ref.kind for ref in project.result_sets)

    order_facet = with_empty_row(
        sorted(orders), any(identity.order is None for identity in identities))
    kind_facet = with_empty_row(
        sorted(kinds), any(identity.result_kind is None for identity in identities))

    parameter_sets = global_parameter_sets(project, identities)
    return order_facet, kind_facet, parameter_sets
