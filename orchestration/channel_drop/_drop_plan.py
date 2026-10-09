"""The Qt-free decisions of a channel drop, as one plain function."""

import dataclasses
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from core.block_kinds import KIND_ORDER_CUT
from core.models import resolve_channel_block_kind
from view_models.analysis_kinds import ANALYSIS_ORDERS

from orchestration.channel_drop._routing import (
    DropFacts,
    DropRouting,
    classify_drop_descriptors,
    filter_duplicate_descriptors,
)


@dataclass(frozen=True)
class OrderGroup:
    """Order descriptors that extract the same orders, so one job serves them all."""

    orders: tuple
    descriptors: tuple[dict, ...]


@dataclass(frozen=True)
class ChannelDropPlan:
    """What a drop will do: the routing groups plus the order groups of ``routing.order``."""

    routing: DropRouting
    order_groups: tuple[OrderGroup, ...] = ()

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
    resolve_metadata: Callable[[Mapping], object],
    read_ribbon_orders: Callable[[], Iterable[float]],
) -> ChannelDropPlan:
    """Decide how a drop is served, without touching a dock, a disk or Qt.

    ``resolve_metadata(descriptor)`` returns the channel metadata (with
    ``func_type``); ``read_ribbon_orders()`` -- read only when needed -- fills ``orders_to_extract`` only into
    descriptors on an order dock that carry none of their own.
    """
    descriptors = list(descriptors)
    if facts.is_graph and facts.analysis_kind == ANALYSIS_ORDERS and not facts.is_result_content_dock:
        # Ordinary order drops and companions claim the same per-order identity.
        descriptors = [
            desc if resolve_channel_block_kind(resolve_metadata(desc)) == KIND_ORDER_CUT
            else desc if "orders_to_extract" in desc
            else {**desc, "orders_to_extract": list(read_ribbon_orders())}
            for desc in descriptors
        ]

    valid = filter_duplicate_descriptors(
        descriptors, plotted_keys, pending_keys, is_graph=facts.is_graph)
    # Restored overlays and graph drags can carry the older payload shape.
    resolved = []
    for desc in valid:
        meta = resolve_metadata(desc)
        resolved.append(
            {**desc, "block_kind": resolve_channel_block_kind(meta), "func_type": meta.func_type})

    routing = classify_drop_descriptors(resolved, facts)
    groups: dict[tuple, list[dict]] = {}
    for desc in routing.order:
        orders = tuple(desc["orders_to_extract"])
        groups.setdefault(orders, []).append(desc)
    return ChannelDropPlan(
        routing, tuple(OrderGroup(orders, tuple(group)) for orders, group in groups.items()))
