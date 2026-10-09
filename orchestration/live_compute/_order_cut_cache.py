"""The one read-only order-cut cache lookup the live workers share."""

from core.block_kinds import KIND_ORDER_CUT, PARAM_ORDER
from io_modules.result_cache.block_io import block_from_stored


def find_cached_order_cuts(finder, file_path, channel_name, channel_meta, params, orders):
    """Ask the result-set cache for every order in `orders` of one channel.

    `finder` is a `find_cached_result_background` callable (ADR §1.54: a worker
    never writes `cache/index.json`) or None; `params` is the order-tracking
    config as a dict. Returns the cache hit or None -- a hit holds one stored
    block per order, in `orders` order, because the lookup misses outright if
    any requested order is absent."""
    if finder is None:
        return None
    return finder(
        file_path, channel_name, KIND_ORDER_CUT, params,
        wanted_block_params=[{PARAM_ORDER: float(order)} for order in orders],
        channel_index=getattr(channel_meta, "index", None),
    )


def rebuild_cached_order_blocks(cached):
    """Live `NVHDataBlock`s from a hit's stored blocks -- the stored form has no
    `.kind`, which the plot's peak-vs-rms scaling needs."""
    return [block_from_stored(block, KIND_ORDER_CUT) for block in cached.blocks]
