"""Which settings a channel dropped onto a dock holding result sets is computed with."""

import dataclasses
from typing import Iterable

from core.block_kinds import KIND_ORDER_CUT
from core.dsp_configs import OrderTrackingConfig
from selection.parameter_sets import ParameterSet, default_primary_index


def resolve_result_content_drop_config(ribbon_config: OrderTrackingConfig,
                                       parameter_sets: Iterable[ParameterSet], *,
                                       from_refresh: bool = False) -> OrderTrackingConfig:
    """
    The config a channel without a saved recipe is computed with on a dock
    holding result sets. A Refresh obeys ``ribbon_config``. A new
    drop fits what the dock shows: the settings of the dock's most-used order
    Parameter Set (``default_primary_index``), or ``ribbon_config`` when the
    dock holds no order set. A set of another kind, such as Overall Level, says
    nothing about an order computation.

    ``ParameterSet.params`` is a whole ``ResultSetRef.params``: identity-only
    keys the config does not know (``algorithm_version``, ``lineage``) stay out.
    """
    order_sets = [ps for ps in parameter_sets if ps.kind == KIND_ORDER_CUT]
    if from_refresh or not order_sets:
        return ribbon_config
    chosen_index = default_primary_index(order_sets)
    chosen = next(ps for ps in order_sets if ps.index == chosen_index)
    known = {field.name for field in dataclasses.fields(OrderTrackingConfig)}
    return OrderTrackingConfig(**{name: value for name, value in chosen.params.items() if name in known})
