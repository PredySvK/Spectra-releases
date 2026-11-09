"""Pure decisions for routing dropped channel descriptors."""

from dataclasses import dataclass
from typing import Iterable, Mapping

from selection.channel_identity import build_channel_key
from selection.parameter_sets import orders_equal
from view_models.analysis_kinds import (
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTRUM,
    resolve_imported_analysis_kind,
)


@dataclass(frozen=True)
class DropFacts:
    """Facts about the target dock that the GUI has already established, read once per drop."""

    is_graph: bool
    is_spec: bool
    analysis_kind: str
    is_result_content_dock: bool
    plotted_keys: frozenset = frozenset()


@dataclass(frozen=True)
class DropRouting:
    """Descriptors grouped by the Drop lane that serves them."""

    time: tuple[dict, ...] = ()
    spectrum: tuple[dict, ...] = ()
    spectrogram: tuple[dict, ...] = ()
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
    plotted_orders = _orders_by_channel(plotted)
    for descriptor in descriptors:
        key = drop_key(descriptor)
        if is_graph and "orders_to_extract" in descriptor:
            remaining = [order for order in descriptor["orders_to_extract"]
                         if (*key, float(order)) not in pending | seen
                         and not _holds_order(plotted_orders, key, order)
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


def _orders_by_channel(keys: Iterable[tuple]) -> dict[tuple, list[float]]:
    """The per-order keys among ``keys``, by the channel they belong to."""
    orders: dict[tuple, list[float]] = {}
    for key in keys:
        if len(key) == 3:
            orders.setdefault(key[:2], []).append(key[2])
    return orders


def _holds_order(orders_by_channel: Mapping[tuple, list[float]], key: tuple, order: float) -> bool:
    """A plotted curve read off a result set names its order through float32,
    so 2.3 comes back as 2.2999999523 -- still the same order."""
    return any(orders_equal(order, held) for held in orders_by_channel.get(key, ()))


def is_imported_descriptor(descriptor: Mapping) -> bool:
    """Whether the descriptor names an Imported result: read, never computed."""
    return resolve_imported_analysis_kind(descriptor.get("block_kind")) is not None


def classify_drop_descriptors(
    descriptors: Iterable[dict], facts: DropFacts,
) -> DropRouting:
    """Partition descriptors into the Drop lane that can serve the target dock."""

    time = []
    spectrum = []
    spectrogram = []
    order = []
    overall_level = []
    result_content = []
    imported = []
    for descriptor in descriptors:
        if is_imported_descriptor(descriptor):
            imported.append(descriptor)
        elif (facts.is_graph and facts.analysis_kind == ANALYSIS_ORDERS
              and facts.is_result_content_dock and "orders_to_extract" not in descriptor):
            result_content.append(descriptor)
        elif facts.is_graph and facts.analysis_kind == ANALYSIS_ORDERS:
            order.append(descriptor)
        elif facts.is_graph and facts.analysis_kind == ANALYSIS_OVERALL_LEVEL:
            overall_level.append(descriptor)
        elif facts.is_spec:
            spectrogram.append(descriptor)
        elif facts.is_graph and facts.analysis_kind == ANALYSIS_SPECTRUM:
            spectrum.append(descriptor)
        else:
            time.append(descriptor)
    return DropRouting(time=tuple(time), spectrum=tuple(spectrum), spectrogram=tuple(spectrogram),
                       order=tuple(order), overall_level=tuple(overall_level),
                       result_content=tuple(result_content), imported=tuple(imported))
