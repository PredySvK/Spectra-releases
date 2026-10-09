# =====================================================================
# FILE: core/frozen.py
# =====================================================================
"""
Helpers that freeze the mapping/sequence fields of the frozen data models in
`core/` (`MeasurementSelection`, `Workflow`) inside their `__post_init__`.

Pulled out of those two modules because the three functions were copied verbatim
between them, differing only in a local type annotation. Both models are frozen,
JSON round-trippable and have immutability tests; a third such model (ROADMAP
promises more) would have copied them a third time. They stay in `core/` because
they are pure data with no I/O and no Qt, exactly like their callers.
"""
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from core.models import ChannelIdentity


def freeze_str_map(values: Optional[Mapping[str, Any]]) -> Mapping[str, Tuple[str, ...]]:
    return MappingProxyType({
        str(key): tuple(str(value) for value in (raw or ()))
        for key, raw in (values or {}).items()
    })


def freeze_range_map(values: Optional[Mapping[str, Any]]) -> Mapping[str, Tuple[Any, Any]]:
    frozen: Dict[str, Tuple[Any, Any]] = {}
    for key, bounds in (values or {}).items():
        if bounds is None:
            continue
        low, high = bounds
        frozen[str(key)] = (low, high)
    return MappingProxyType(frozen)


def freeze_identities(values) -> Tuple[ChannelIdentity, ...]:
    return tuple(
        (str(base), None if direction is None else str(direction))
        for base, direction in (values or ())
    )
