"""The config a restored tab's base curve is computed with."""

import dataclasses
from typing import Any, Mapping, Optional, Tuple


@dataclasses.dataclass(frozen=True)
class RestoreConfig:
    """
    `config` is the saved recipe laid over the ribbon's config; `from_ribbon`
    names the fields the recipe did not carry, in the config's field order.
    `has_recipe` is False when the project saved no recipe at all.
    """
    config: Any
    from_ribbon: Tuple[str, ...]
    has_recipe: bool


def resolve_restore_config(recipe: Optional[Mapping[str, Any]], ribbon_config: Any) -> RestoreConfig:
    """
    A restored tab computes with the recipe it was saved with
    (`TraceSpec.compute_spec`), not with today's ribbon. Every field of
    `ribbon_config` the recipe holds is taken from the recipe; the rest --
    what a recipe deliberately leaves out (order width, rpm step, DC removal:
    `PARAM_COMPUTATION`), or everything when there is no recipe -- stays the
    ribbon's. Keys of the recipe that are no config field (`acf`, an order
    cut's `order`, ...) are ignored.
    """
    names = [field.name for field in dataclasses.fields(ribbon_config)]
    if not recipe:
        return RestoreConfig(config=ribbon_config, from_ribbon=tuple(names), has_recipe=False)
    taken = {name: recipe[name] for name in names if name in recipe}
    return RestoreConfig(
        config=dataclasses.replace(ribbon_config, **taken),
        from_ribbon=tuple(name for name in names if name not in taken),
        has_recipe=True,
    )


def build_restore_config_line(subject: str, restore_config: RestoreConfig) -> str:
    """The one log line saying where a restored tab's settings came from; `subject` is the whole phrase."""
    if not restore_config.has_recipe:
        return (f"PROJECT: {subject} restored with the ribbon's settings -- "
                f"the project saved no recipe for it.")
    if not restore_config.from_ribbon:
        return f"PROJECT: {subject} restored with its saved recipe."
    return (f"PROJECT: {subject} restored with its saved recipe; from the ribbon: "
            f"{', '.join(restore_config.from_ribbon)}.")
