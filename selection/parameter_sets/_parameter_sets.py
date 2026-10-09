from __future__ import annotations

"""
Implementation of Parameter Set grouping, shape signatures, and order comparison.
"""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Mapping, Optional, Tuple

from core.block_kinds import spec_for
from core.project_model import NVHProject, ResultSetRef

if TYPE_CHECKING:
    from selection.trace_filter import TraceIdentity

# Two order numbers mean the same order. Loose on purpose: cache_writer stores
# the order axis as float32 (DATASET_ORDERS), so an order the user typed as
# 2.3 comes back as 2.2999999523 and an exact comparison against the 2.3 still
# held in ResultSetRef.params would call them different orders. The relative
# term keeps that true for large orders too, where the float32 error grows.
ORDER_REL_TOL = 1e-5
ORDER_ABS_TOL = 1e-6


def orders_equal(left: float, right: float) -> bool:
    """Whether two order numbers name the same order -- see the tolerances above."""
    return abs(float(left) - float(right)) <= ORDER_ABS_TOL + ORDER_REL_TOL * abs(float(right))


def _hashable(value: Any) -> Any:
    """A params value in a form that can go into a tuple key."""
    if isinstance(value, (list, tuple)):
        return tuple(_hashable(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(k), _hashable(v)) for k, v in value.items()))
    return value


def shape_signature(kind: str, params: Mapping[str, Any]) -> Tuple:
    """
    What "computed with the same settings" means, for any kind.

    Every parameter counts except three sorts. `algorithm_version` is left out
    and checked separately, because a result set saved before that key existed
    must be treated as version 1 rather than as an automatic miss. Each kind's
    `cache_exempt_params` (core/block_kinds.py) are left out because a wider
    result set legitimately satisfies a narrower request -- a set saved with
    orders "1, 2, 4.5" answers a request for order 2, which is then matched per
    stored block by block_params_match(). And each kind's `display_only_params`
    (a spectrogram's colour scale) are left out because they change the picture,
    not the numbers: a live request carrying `color_scale` would otherwise never
    match a batch-saved spectrogram, whose node had it stripped (audit 02 / 7.5).

    Sorted by key, so two dicts built in a different order compare equal. This
    is the generalisation of what FFT_SHAPE_KEYS did for order cuts alone.
    """
    spec = spec_for(kind)
    exempt = (set(spec.cache_exempt_params) | set(spec.display_only_params)
              | {"algorithm_version"})
    return tuple(
        (key, _hashable(params[key])) for key in sorted(params) if key not in exempt
    )


Signature = Tuple


def parameter_signature(kind: str, params: Mapping[str, Any]) -> Signature:
    """
    What makes two computations "the same settings": their kind and its shape
    params, as one tuple. The kind rides as a `("__kind__", kind)` pair so every
    element has the same `(key, value)` shape -- callers that compare element by
    element (selection.trace_filter) can zip without special-casing the
    head. The one signature shape both a project result set and a bare dock
    trace emit, so a Global card compares them directly (ADR §1.36, §1.41).
    """
    return (("__kind__", kind),) + shape_signature(kind, params)


def result_set_signature(result_set: ResultSetRef) -> Signature:
    """What makes two result sets "the same settings": their kind and its shape params."""
    return parameter_signature(result_set.kind, result_set.params)


@dataclass
class ParameterSet:
    index: int  # 1-based, stable for the project's lifetime (see module docstring)
    signature: Signature
    result_set_ids: List[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)  # one representative full params dict, for the detail view
    kind: str = ""

    @property
    def label(self) -> str:
        return f"Parameter Set {self.index}"


def _signature_numbering(project: NVHProject) -> Dict[Signature, int]:
    numbering: Dict[Signature, int] = {}
    for rs in project.result_sets:
        sig = result_set_signature(rs)
        if sig not in numbering:
            numbering[sig] = len(numbering) + 1
    return numbering


def build_parameter_sets(project: NVHProject, result_set_ids: Iterable[str]) -> List[ParameterSet]:
    """
    One ParameterSet per distinct (kind, settings) pair found among
    `result_set_ids`, sorted by their stable, project-wide index.
    """
    numbering = _signature_numbering(project)
    refs_by_id = {rs.id: rs for rs in project.result_sets}

    grouped: Dict[Signature, List[str]] = {}
    for rs_id in result_set_ids:
        rs = refs_by_id.get(rs_id)
        if rs is None:
            continue
        grouped.setdefault(result_set_signature(rs), []).append(rs_id)

    parameter_sets = [
        ParameterSet(
            index=numbering[sig], signature=sig, result_set_ids=ids,
            params=dict(refs_by_id[ids[0]].params), kind=refs_by_id[ids[0]].kind,
        )
        for sig, ids in grouped.items()
    ]
    parameter_sets.sort(key=lambda ps: ps.index)
    return parameter_sets


def default_primary_index(parameter_sets: List[ParameterSet]) -> int:
    """The most-used Parameter Set (by result-set count); the lowest index breaks a tie."""
    return max(parameter_sets, key=lambda ps: (len(ps.result_set_ids), -ps.index)).index


def filter_result_sets_by_parameter_set(refs: List[ResultSetRef], parameter_sets: List[ParameterSet],
                                        selected_indices: Iterable[int]) -> List[ResultSetRef]:
    """
    `refs` narrowed to those belonging to a selected Parameter Set. An empty
    `selected_indices` imposes no constraint, same convention as the other
    facets in selection.source_facets.
    """
    selected = set(selected_indices)
    if not selected:
        return list(refs)

    wanted_ids = set()
    for ps in parameter_sets:
        if ps.index in selected:
            wanted_ids.update(ps.result_set_ids)
    return [rs for rs in refs if rs.id in wanted_ids]


def signature_value_matches(left: Any, right: Any) -> bool:
    """One (key, value) pair of a signature, tolerant of float noise -- a
    parameter written to two separate result-cache files can round-trip
    through float32/JSON slightly differently even when the user typed the
    same setting both times, the same reasoning as order_matches (K1)."""
    if isinstance(left, float) or isinstance(right, float):
        try:
            return orders_equal(left, right)
        except (TypeError, ValueError):
            return left == right
    return left == right


def signatures_match(a: Signature, b: Signature) -> bool:
    """Two parameter-set signatures, tolerant of float noise on the values. Both
    sides come from `parameter_signature` now (dock trace and project result
    set alike, ADR §1.41), so the shapes already line up."""
    if len(a) != len(b):
        return False
    return all(
        key_a == key_b and signature_value_matches(value_a, value_b)
        for (key_a, value_a), (key_b, value_b) in zip(a, b)
    )


def signature_matches_any(signature: Signature, signatures: Iterable[Signature]) -> bool:
    """Whether `signature` names the same settings as any of `signatures` --
    the float-tolerant membership test a checked-signature set needs, since
    plain `in` would miss a value that round-tripped through float32/JSON."""
    return any(signatures_match(signature, other) for other in signatures)


def parameter_set_for_signature(signature: Optional[Signature],
                                parameter_sets: Tuple[ParameterSet, ...]) -> Optional[ParameterSet]:
    if signature is None:
        return None
    return next((ps for ps in parameter_sets if signatures_match(signature, ps.signature)), None)


def parameter_sets_from_traces(identities: List[TraceIdentity]) -> List[ParameterSet]:
    """
    One ParameterSet per distinct (kind, settings) combination actually drawn
    on this dock, numbered by first appearance among `identities` -- a
    dock-local numbering (ARCHITECTURE_DECISIONS §1.30 F4), not
    `build_parameter_sets`'s project-wide one, since these curves need not
    even trace back to a ResultSetRef the project still knows about.

    Public because `filter_card.builtin_column_cardinalities_from_traces` needs
    the same dock-local numbering to count Parameter Set values (§1.33).
    """
    parameter_sets: List[ParameterSet] = []
    for identity in identities:
        if identity.parameter_signature is None:
            continue
        existing = parameter_set_for_signature(identity.parameter_signature, tuple(parameter_sets))
        if existing is not None:
            continue
        parameter_sets.append(ParameterSet(
            index=len(parameter_sets) + 1, signature=identity.parameter_signature,
            params=dict(identity.compute_spec or {}), kind=identity.result_kind or "",
        ))
    return parameter_sets
