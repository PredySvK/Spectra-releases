"""Pure decisions for routing dropped channel descriptors."""

from dataclasses import dataclass
from typing import Iterable, Mapping
from core.block_kinds import KIND_ORDER_CUT

from selection.channel_identity import build_channel_key
from view_models.analysis_kinds import ANALYSIS_ORDERS, ANALYSIS_OVERALL_LEVEL


@dataclass(frozen=True)
class DropFacts:
    """Facts about the target dock that the GUI has already established, read once per drop."""

    is_graph: bool
    is_spec: bool
    analysis_kind: str
    is_result_content_dock: bool
    plotted_keys: frozenset = frozenset()
    live_pending_keys: frozenset = frozenset()


@dataclass(frozen=True)
class DropRouting:
    """Descriptors grouped by the processing path selected for the drop."""

    simple: tuple[dict, ...] = ()
    order: tuple[dict, ...] = ()
    overall_level: tuple[dict, ...] = ()
    result_content: tuple[dict, ...] = ()
    imported: tuple[dict, ...] = ()


def drop_key(descriptor: Mapping) -> tuple:
    """Return the identity used to detect a dropped channel duplicate."""

    return build_channel_key(descriptor["file_path"], descriptor["channel_index"])


def drop_keys(descriptor: Mapping) -> set[tuple]:
    """A normal drop claims a channel; a companion claims specified orders."""
    key = drop_key(descriptor)
    if "orders_to_extract" in descriptor:
        return {(*key, float(order)) for order in descriptor["orders_to_extract"]}
    return {key}


def filter_duplicate_descriptors(
    descriptors: Iterable[Mapping],
    plotted_keys: Iterable[tuple],
    pending_keys: Iterable[tuple],
    *,
    is_graph: bool,
) -> list[Mapping]:
    """Keep descriptors not already plotted, pending, or repeated in a batch."""

    plotted = set(plotted_keys)
    pending = set(pending_keys)
    valid = []
    seen = set()
    for descriptor in descriptors:
        key = drop_key(descriptor)
        if is_graph and "orders_to_extract" in descriptor:
            remaining = [order for order in descriptor["orders_to_extract"]
                         if (*key, float(order)) not in plotted | pending | seen
                         and key not in pending | seen]
            if remaining:
                descriptor = {**descriptor, "orders_to_extract": remaining}
                valid.append(descriptor)
                seen.update(drop_keys(descriptor))
            continue
        if is_graph and (key in plotted or key in pending or key in seen
                         or any(other[:2] == key for other in pending | seen)):
            continue
        valid.append(descriptor)
        seen.add(key)
    return valid


def classify_drop_descriptors(
    descriptors: Iterable[dict], facts: DropFacts,
) -> DropRouting:
    """Partition descriptors into the path that can serve the target dock."""

    simple = []
    order = []
    overall_level = []
    result_content = []
    imported = []
    for descriptor in descriptors:
        if descriptor.get("block_kind") == KIND_ORDER_CUT:
            imported.append(descriptor)
        elif facts.is_result_content_dock and "orders_to_extract" not in descriptor:
            result_content.append(descriptor)
        elif facts.is_graph and facts.analysis_kind == ANALYSIS_ORDERS:
            order.append(descriptor)
        elif facts.is_graph and facts.analysis_kind == ANALYSIS_OVERALL_LEVEL:
            overall_level.append(descriptor)
        else:
            simple.append(descriptor)
    return DropRouting(tuple(simple), tuple(order), tuple(overall_level), tuple(result_content), tuple(imported))
