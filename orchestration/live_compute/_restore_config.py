"""The config a restored tab's base curve is computed with."""

import dataclasses
from typing import Any, Mapping, Optional

from core.block_kinds import PARAM_ORDERS


@dataclasses.dataclass(frozen=True)
class RestoreConfig:
    """
    `config` is the config a restored curve computes with; `has_recipe` is
    False when the project saved no Curve recipe for it, and `config` is then
    the ribbon's.
    """
    config: Any
    has_recipe: bool


def resolve_restore_config(recipe: Optional[Mapping[str, Any]], ribbon_config: Any) -> RestoreConfig:
    """
    A restored tab computes with the Curve recipe it was saved with
    (`TraceSpec.compute_spec`), not with today's ribbon: every setting that
    changes the numbers -- step, order width, rpm and time Tracking range,
    direction, `remove_dc` -- is in the Curve recipe and taken from it (#815).
    The ribbon fills in only the display fields the Curve recipe drops (drawn
    as before) and an order tab's order list, since an order cut's Curve
    recipe names only its own order. Keys that are no config field
    (`algorithm_version`, an order cut's `order`, ...) are ignored. Without a
    Curve recipe the config is the ribbon's.
    """
    if not recipe:
        return RestoreConfig(config=ribbon_config, has_recipe=False)
    names = [field.name for field in dataclasses.fields(ribbon_config)]
    taken = {name: recipe[name] for name in names if name in recipe and name != PARAM_ORDERS}
    return RestoreConfig(config=dataclasses.replace(ribbon_config, **taken), has_recipe=True)


def build_restore_config_line(subject: str, restore_config: RestoreConfig) -> str:
    """The one log line saying where a restored tab's settings came from; `subject` is the whole phrase."""
    if not restore_config.has_recipe:
        return (f"PROJECT: {subject} restored with the ribbon's settings -- "
                f"the project saved no recipe for it.")
    return f"PROJECT: {subject} restored with its saved recipe."
