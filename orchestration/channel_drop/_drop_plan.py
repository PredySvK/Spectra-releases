"""The Qt-free decisions of a channel drop, as one plain function."""

import dataclasses
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from view_models.analysis_kinds import ANALYSIS_ORDERS

from orchestration.channel_drop._routing import (
    DropFacts,
    DropRouting,
    classify_drop_descriptors,
    drop_keys,
    filter_duplicate_descriptors,
    is_imported_descriptor,
)


@dataclass(frozen=True)
class OrderGroup:
    """Order descriptors that extract the same orders, so one job serves them all."""

    orders: tuple
    descriptors: tuple[dict, ...]


@dataclass(frozen=True)
class ChannelDropPlan:
    """What a drop will do: the routing groups plus the order groups of
    ``routing.order`` and of ``routing.result_content``."""

    routing: DropRouting
    order_groups: tuple[OrderGroup, ...] = ()
    result_content_groups: tuple[OrderGroup, ...] = ()

    @property
    def count(self) -> int:
        return sum(len(group) for group in dataclasses.astuple(self.routing))

    @property
    def is_empty(self) -> bool:
        """True when every descriptor was a duplicate and nothing is left to do."""
        return self.routing == DropRouting()


def plan_channel_drop(
    descriptors: Iterable[Mapping],
    facts: DropFacts,
    plotted_keys: Iterable[tuple],
    pending_keys: Iterable[tuple],
    read_ribbon_orders: Callable[[], Iterable[float]],
    read_result_content_orders: Callable[[Mapping], Iterable[float]],
) -> ChannelDropPlan:
    """Decide how a drop is served, without touching a dock, a disk or Qt.

    ``read_ribbon_orders()`` -- read only when needed -- fills ``orders_to_extract`` only into
    descriptors on an order dock that carry none of their own. On a dock holding
    result sets ``read_result_content_orders(descriptor)`` fills them instead:
    those channels take the result-content lane, and a descriptor with orders of
    its own (a companion) stays on the order lane. Either way the duplicate
    filter then works per order, so only the missing orders are computed.
    """
    descriptors = list(descriptors)
    if facts.is_graph and facts.analysis_kind == ANALYSIS_ORDERS and not facts.is_result_content_dock:
        # Ordinary order drops and companions claim the same per-order identity.
        descriptors = [
            desc if is_imported_descriptor(desc)
            else desc if "orders_to_extract" in desc
            else {**desc, "orders_to_extract": list(read_ribbon_orders())}
            for desc in descriptors
        ]

    arriving = classify_drop_descriptors(descriptors, facts).result_content
    arriving_ids = {id(desc) for desc in arriving}
    plotted_keys = set(plotted_keys)
    valid = filter_duplicate_descriptors(
        [desc for desc in descriptors if id(desc) not in arriving_ids],
        plotted_keys, pending_keys, is_graph=facts.is_graph)
    # Taken from the classification before the orders are filled in: with them
    # a channel of this lane could not be told from a companion any more.
    result_content = filter_duplicate_descriptors(
        [{**desc, "orders_to_extract": list(read_result_content_orders(desc))} for desc in arriving],
        plotted_keys, {*pending_keys, *(key for desc in valid for key in drop_keys(desc))},
        is_graph=facts.is_graph)
    routing = dataclasses.replace(
        classify_drop_descriptors(valid, facts), result_content=tuple(result_content))
    return ChannelDropPlan(routing, _by_orders(routing.order), _by_orders(routing.result_content))


def _by_orders(descriptors: Iterable[Mapping]) -> tuple[OrderGroup, ...]:
    groups: dict[tuple, list[dict]] = {}
    for desc in descriptors:
        groups.setdefault(tuple(desc["orders_to_extract"]), []).append(desc)
    return tuple(OrderGroup(orders, tuple(group)) for orders, group in groups.items())
