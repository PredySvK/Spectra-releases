"""Background worker payload for channels dropped onto the Compare dock."""

import dataclasses
import threading
from typing import Optional, Tuple

from core.dsp_configs import OrderTrackingConfig
from io_modules.data_accessor import DataAccessor
from orchestration.live_compute._order_cut_cache import find_cached_order_cuts
from orchestration.live_compute._payloads import read_two_channels
from signal_processing.result_blocks import (
    build_order_cut_blocks, compute_order_cuts, computation_params,
)


def lookup_or_compute_order_cuts(
    project_session, run, tacho_meta, channel_meta,
    channel_name: str, config: OrderTrackingConfig,
    use_cache: bool = True,
    plan_scratch: Optional[Tuple[threading.Lock, dict]] = None,
):
    """
    Runs on a worker thread (ADR §1.54): ask the result-set cache whether this
    exact order cut was already computed and saved, then rebuild the order
    blocks from the stored amplitudes on a hit or compute them on a miss. The
    cache is asked through `find_cached_result_background`, whose `write_index`
    is hardcoded `False` -- a worker never persists `cache/index.json`.

    `plan_scratch` is `(lock, scratch)` the caller keeps for one file's tacho
    and sweep, so the channels of that file -- one job each -- build their
    `TrackingPlan` once (#99). Only the job that finds the bag empty computes
    under the lock, so siblings running at the same time wait for its plan
    instead of building their own, then cut their channels in parallel.

    Returns `(order_blocks, result_set_label_or_None)` -- the label is the
    hit/miss verdict the GUI thread logs in `_on_finished`. No Qt objects, no
    `app_context.log`.
    """
    cached = None
    if use_cache and project_session is not None:
        cached = find_cached_order_cuts(
            project_session.find_cached_result_background, run.file_path, channel_name,
            channel_meta, dataclasses.asdict(config), config.orders_to_extract,
        )
    if cached is not None:
        # A hit reads the vibration channel only for the block's name and
        # inherited sensor context -- never the tacho, and never raw data for
        # the maths (ADR §1.54: a hit is always cheaper than a miss). Same
        # builder the freshly computed path funnels into, so a cached curve and
        # a recomputed one end up in an identically assembled block. The blocks
        # come back in the requested order (find_cached_result misses outright
        # if any requested order is absent), so this zip is safe.
        vib_block = DataAccessor.fetch_channel_data(run, channel_meta)
        blocks = build_order_cut_blocks(
            vib_block, cached.blocks[0].axes[0].values,
            {order: block.values
             for order, block in zip(config.orders_to_extract, cached.blocks)},
            window_type=config.window_type, fft_size=config.fft_size,
            value_unit=cached.blocks[0].value_unit, computation=computation_params(config),
        )
        return blocks, cached.result_set_label

    vib_block, tacho_block = read_two_channels(run, channel_meta, tacho_meta)
    if plan_scratch is None:
        return compute_order_cuts(vib_block, tacho_block, config), None
    lock, scratch = plan_scratch
    with lock:
        if not scratch:
            return compute_order_cuts(vib_block, tacho_block, config, scratch=scratch), None
    return compute_order_cuts(vib_block, tacho_block, config, scratch=scratch), None
