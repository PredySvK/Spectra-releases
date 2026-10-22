# =====================================================================
# FILE: core/curve_recipe.py
# =====================================================================
"""
The Curve recipe (`CONTEXT.md`): everything one curve can be computed again
from, as the computation stamps it onto the block it makes.

A recipe is the DSP config with the kind's display-only fields dropped,
stamped with the algorithm version and, below other workflow blocks, the
lineage of the steps above it. It is the very identity a result set is saved
and looked up by (`io_modules.result_cache.result_params_from_block`, through
`signal_processing.workflow.identity_params`), built here once so the block
and the result set cannot follow two copies of the rule. An order cut's recipe
narrows the order list to its own order; a Residual's keeps all of it.

Lives in core/ because the computation (signal_processing), the result-set
identity (io_modules) and the graph's view of a curve (view_models) all read
it, and none of them may import another for it. Duck-typed on the block, like
`block_kinds.validate`, so it does not import data_block.
"""

from dataclasses import replace
from typing import Any, Dict, Mapping, Optional

from core.block_kinds import KIND_ORDER_RESIDUAL, PARAM_ORDERS, spec_for
from core.dsp_configs import DSP_ALGORITHM_VERSIONS, resolve_active_tracking_params

# Where a block carries its recipe, in Provenance.params.
PARAM_CURVE_RECIPE = "curve_recipe"
# The two keys the program stamps on top of the config.
RECIPE_ALGORITHM_VERSION = "algorithm_version"
RECIPE_LINEAGE = "lineage"

def build_curve_recipe(kind: str, params: Mapping[str, Any], *,
                       algorithm_version: Optional[int] = None, lineage: str = "") -> Dict[str, Any]:
    """
    The recipe of a `kind` result computed with config `params` (a flat
    `asdict` of its DSP config): the kind's `display_only_params` dropped, the
    algorithm version stamped -- `algorithm_version`, or the kind's current one
    when None -- and `lineage` when there is one. An empty lineage adds no
    key, so a block fed straight by the measurement keeps the identity a
    one-step graph has always had. The Tracking range of the tracking mode
    the config is not in is auto: it shaped nothing.
    """
    display_only = spec_for(kind).display_only_params
    recipe = {key: value for key, value in resolve_active_tracking_params(params).items()
              if key not in display_only}
    if algorithm_version is None:
        algorithm_version = DSP_ALGORITHM_VERSIONS.get(kind)
    recipe[RECIPE_ALGORITHM_VERSION] = algorithm_version
    if lineage:
        recipe[RECIPE_LINEAGE] = lineage
    return recipe


def build_order_cut_curve_recipe(recipe: Mapping[str, Any], order: float) -> Dict[str, Any]:
    """An order tracking `recipe` narrowed to the one order a cut was made at."""
    return {**recipe, PARAM_ORDERS: [float(order)]}


def build_order_residual_curve_recipe(params: Mapping[str, Any]) -> Dict[str, Any]:
    """
    The recipe of the Residual an Order Tracking config (`params`, flat
    `asdict`) computes: the whole order list, as floats like the one its
    provenance names -- a Residual is a function of all of them.
    """
    return build_curve_recipe(KIND_ORDER_RESIDUAL, {
        **params, PARAM_ORDERS: [float(order) for order in params[PARAM_ORDERS]]})


def resolve_curve_recipe(block: Any) -> Optional[Dict[str, Any]]:
    """The recipe `block` was stamped with, or None for a block computed without one."""
    provenance = getattr(block, "provenance", None)
    recipe = provenance.params.get(PARAM_CURVE_RECIPE) if provenance is not None else None
    return dict(recipe) if recipe else None


def build_block_with_workflow_stamp(block: Any, algorithm_version: Optional[int], lineage: str) -> Any:
    """
    `block` with its recipe stamped as the workflow block that made it is
    identified: that block's `algorithm_version` and, when there is one, the
    `lineage` of the steps above it -- the workflow runner knows both, the
    computation does not. A block without a recipe comes back as it is.
    """
    recipe = resolve_curve_recipe(block)
    if recipe is None:
        return block
    recipe[RECIPE_ALGORITHM_VERSION] = algorithm_version
    if lineage:
        recipe[RECIPE_LINEAGE] = lineage
    params = {**block.provenance.params, PARAM_CURVE_RECIPE: recipe}
    return replace(block, provenance=replace(block.provenance, params=params))
