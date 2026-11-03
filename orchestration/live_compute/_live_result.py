"""
One channel's live result: cache lookup, raw read and DSP in one worker task
(ADR §1.167). Plain function, no Qt -- the GUI starts it through `dock_tasks`
and only draws what comes back.
"""

import dataclasses
from functools import partial
from typing import Any, Callable, Optional, Tuple, Union

import numpy as np

from core.block_kinds import (
    KIND_ORDER_CUT, KIND_OVERALL_LEVEL, KIND_SPECTROGRAM, KIND_SPECTRUM, PARAM_ORDER,
    resolve_invalid_sample_metadata,
)
from core.channel_types import CHANNEL_TYPE_ACCELEROMETER
from core.data_block import NVHDataBlock, build_source_ref
from io_modules.data_accessor import DataAccessor
from io_modules.result_cache import block_from_stored
from io_modules.tab_cache import TabCacheMiss, read_tab_cache_file
from orchestration.live_compute._compute_origin import PHASE_COMPUTE, PHASE_READ
from orchestration.tab_cache import build_tab_cache_miss_line
from orchestration.tacho_interpolation import build_tacho_interpolation_line
from signal_processing.result_blocks import (
    TrackingScratch,
    build_invalid_samples_line,
    build_order_cut_blocks,
    build_order_tracking_curve_recipe,
    build_overall_level_missing_line,
    compute_order_cuts,
    compute_overall_level,
    compute_spectrogram,
    compute_spectrum,
    require_uniform_rpm_axis,
    resolve_sampling_frequency,
    UnevenRpmAxisError,
)
from selection.tacho import find_tacho_channel, tacho_interpolates


@dataclasses.dataclass(frozen=True)
class LiveRequest:
    """
    What a live view asks for: one channel, the Block kind to make of it, and
    the DSP config DTO whole. `tacho_block` is a tacho the view already holds
    (a Refresh); None reads `tacho_meta`, or the file's own when that is None
    too (a dropped channel's run is bare and names its tacho instead).
    `vib_block` is the channel itself already read (a drop onto a
    spectrogram): then nothing is read and nothing comes from the cache --
    the view paired these channels itself, and `tacho_block` is the whole
    tacho.
    `with_overall_level` adds the Overall Level and Residual curves to an
    order cut.
    `tab_cache_path` is a restored curve's Tab cache file, tried before
    anything else; `compute_notices` are log lines that only
    hold when the curve is computed after all (where its config came from).
    """
    run_index: Any
    channel_meta: Any
    block_kind: str
    config: Any
    tacho_block: Optional[NVHDataBlock] = None
    with_overall_level: bool = False
    tacho_meta: Any = None
    vib_block: Optional[NVHDataBlock] = None
    tab_cache_path: Optional[str] = None
    compute_notices: Tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class LiveResult:
    """
    The blocks for one channel, computed now, rebuilt from a saved result
    set (`from_cache`, then named by `result_set_label`) or read back from
    the Tab cache (`from_tab_cache`). `vib_block` and
    `tacho_block` are the raw channels a miss read, for the view to keep;
    `notices` are log lines the GUI writes as they are.
    """
    blocks: Tuple[NVHDataBlock, ...]
    from_cache: bool = False
    result_set_label: str = ""
    vib_block: Optional[NVHDataBlock] = None
    tacho_block: Optional[NVHDataBlock] = None
    notices: Tuple[str, ...] = ()
    from_tab_cache: bool = False


@dataclasses.dataclass(frozen=True)
class LiveFailure:
    """A live compute that will not land: which phase failed (`PHASE_READ` /
    `PHASE_COMPUTE`) and why."""
    phase: str
    message: str
    notices: Tuple[str, ...] = ()


def run_live_compute(request: LiveRequest, finder: Optional[Callable] = None,
                        tracking: Optional[TrackingScratch] = None,
                        ) -> Union[LiveResult, LiveFailure]:
    """
    Runs on a worker thread. Asks the result-set cache first --
    `finder` is a `ProjectSession.cache_finder` callable, None to skip it --
    and on a miss reads the channel and computes it, in this one task so a
    miss never waits on a GUI callback before it reaches the disk (#504).

    An Overall Level computed with the orders never comes from the cache
   . A lookup that raises, or a stored block that does
    not rebuild, counts as a miss. `tracking` is the caller's `TrackingScratch`,
    so clicks on channels of one file build their TrackingPlan once (#500).

    A restored curve reads its Tab cache file first (`tab_cache_path`); a
    file that cannot stand in for the compute costs one log line and the
    curve is computed as if there were none.

    Never raises for a bad channel or config: the failure comes back as a
    `LiveFailure` with the phase it failed in.
    """
    if request.tab_cache_path is not None:
        from_tab_cache, miss_line = _read_tab_cache(request)
        if from_tab_cache is not None:
            return from_tab_cache
        before = (miss_line,) + tuple(request.compute_notices)
    else:
        before = tuple(request.compute_notices)

    try:
        _check_preconditions(request)
    except ValueError as error:
        return LiveFailure(PHASE_COMPUTE, str(error), before)

    # Neither an Overall Level computed with the orders
    # nor channels the view paired itself (a saved set used the file's tacho).
    if not request.with_overall_level and request.vib_block is None:
        hit = _lookup(request, finder)
        if hit is not None:
            return dataclasses.replace(hit, notices=before + hit.notices)

    try:
        vib_block, tacho_block = _read(request)
    except Exception as error:
        return LiveFailure(PHASE_READ, str(error), before)

    try:
        blocks, notices = _run_dsp(request, vib_block, tacho_block, tracking)
    except Exception as error:
        return LiveFailure(PHASE_COMPUTE, str(error), before)

    return LiveResult(
        blocks=tuple(blocks), vib_block=vib_block, tacho_block=tacho_block,
        notices=before + _tacho_interpolation_notices(request, vib_block, tacho_block)
        + notices + _invalid_samples_notices(blocks),
    )


def _tacho_interpolation_notices(request: LiveRequest, vib_block, tacho_block) -> Tuple[str, ...]:
    """The line saying a miss carried its tacho onto another rate: never for a hit, which computes nothing."""
    if tacho_block is None or request.block_kind == KIND_SPECTRUM or getattr(request.config, "tracking_mode", "rpm") != "rpm":
        return ()
    try:
        tacho_rate = resolve_sampling_frequency(tacho_block)
        channel_rate = resolve_sampling_frequency(vib_block)
    except ValueError:
        return ()  # the compute refuses a block without a usable rate with its own message
    if not tacho_interpolates(tacho_rate, channel_rate):
        return ()
    return (build_tacho_interpolation_line(
        request.run_index.file_name, tacho_block.name, tacho_rate, channel_rate),)


def _read_tab_cache(request: LiveRequest) -> Tuple[Optional[LiveResult], str]:
    """The curve from its Tab cache file, or None and the line saying why not."""
    channel_name = getattr(request.channel_meta, "name", "") or ""
    try:
        blocks = read_tab_cache_file(request.tab_cache_path).blocks
        if blocks[0].kind != request.block_kind:
            raise TabCacheMiss(f"holds a {blocks[0].kind}, not a {request.block_kind}")
        if request.block_kind == KIND_SPECTROGRAM:
            require_uniform_rpm_axis(blocks[0])
    except (TabCacheMiss, UnevenRpmAxisError) as miss:
        return None, build_tab_cache_miss_line(channel_name, str(miss))
    return LiveResult(blocks=blocks, from_tab_cache=True,
                      notices=_invalid_samples_notices(blocks)), ""


def _invalid_samples_notices(blocks) -> Tuple[str, ...]:
    """The invalid (NaN) samples line (#673), for a hit as for a miss."""
    line = build_invalid_samples_line(list(blocks))
    return (line,) if line else ()


def _check_preconditions(request: LiveRequest) -> None:
    if request.block_kind == KIND_ORDER_CUT and not request.config.orders_to_extract:
        raise ValueError("No Target Orders specified.")


# ---- cache -----------------------------------------------------------------

def _lookup(request: LiveRequest, finder: Optional[Callable]) -> Optional[LiveResult]:
    file_path = getattr(request.run_index, "file_path", None)
    if finder is None or not file_path or request.channel_meta is None:
        return None

    wanted = None
    if request.block_kind == KIND_ORDER_CUT:
        wanted = [{PARAM_ORDER: float(order)} for order in request.config.orders_to_extract]
    try:
        cached = finder(
            file_path, request.channel_meta.name, request.block_kind,
            dataclasses.asdict(request.config),
            wanted_block_params=wanted,
            channel_index=getattr(request.channel_meta, "index", None),
        )
        if cached is None or not cached.blocks:
            return None
        blocks = _rebuild_cached_blocks(request, cached)
        if request.block_kind == KIND_SPECTROGRAM:
            require_uniform_rpm_axis(blocks[0])
    except Exception:
        return None

    label = cached.result_set_label or ""
    if label:
        blocks = [
            dataclasses.replace(block, metadata={**block.metadata, "result_set_label": label})
            for block in blocks
        ]
    return LiveResult(blocks=tuple(blocks), from_cache=True, result_set_label=label,
                      notices=_invalid_samples_notices(blocks))


def _rebuild_cached_blocks(request: LiveRequest, cached) -> list:
    """
    Live blocks from a hit's stored ones. Order cuts are built by the same
    builder a fresh compute ends in, over a source block named from the
    channel itself -- no raw read (a hit is always cheaper than a miss,
    ADR §1.54). Its `SourceRef` is the one a fresh read stamps: left unset,
    the order-2.. curves would not match the base channel any more and a
    later Refresh would re-drop them as overlays (#379).
    """
    if request.block_kind != KIND_ORDER_CUT:
        return [block_from_stored(cached.blocks[0], request.block_kind)]

    config = request.config
    channel_meta = request.channel_meta
    first = cached.blocks[0]
    source_block = NVHDataBlock.time_response(
        name=channel_meta.name,
        values=np.empty(0),
        times=np.empty(0),
        value_unit=first.value_unit or getattr(channel_meta, "unit", "") or "",
        channel_type=getattr(channel_meta, "type", None) or CHANNEL_TYPE_ACCELEROMETER,
        source=build_source_ref(request.run_index, channel_meta),
    )
    # The lookup misses outright when any requested order is absent, so the
    # stored blocks come back in requested order and this zip is safe.
    blocks = build_order_cut_blocks(
        source_block, first.axes[0].values,
        {order: block.values for order, block in zip(config.orders_to_extract, cached.blocks)},
        window_type=config.window_type, fft_size=config.fft_size,
        value_unit=first.value_unit,
        curve_recipe=build_order_tracking_curve_recipe(config),
    )
    # What invalid samples cost the cut is all the rebuild keeps of the stored
    # metadata: the rest is rebuilt from the channel (#673).
    invalid = resolve_invalid_sample_metadata((getattr(first, "meta", None) or {}).get("metadata"))
    if not invalid:
        return blocks
    return [dataclasses.replace(block, metadata={**block.metadata, **invalid}) for block in blocks]


# ---- miss ------------------------------------------------------------------

def _read(request: LiveRequest):
    """The raw channels a miss computes from: `(vib, tacho_or_None)`."""
    run_index, channel_meta, config = request.run_index, request.channel_meta, request.config
    kind = request.block_kind
    if kind not in (KIND_SPECTRUM, KIND_SPECTROGRAM, KIND_ORDER_CUT, KIND_OVERALL_LEVEL):
        raise ValueError(f"no live compute for block kind '{kind}'")
    if kind == KIND_SPECTROGRAM:
        # A `vib_block` already read is kept; its tacho is still read when
        # missing -- a channel dropped onto a spectrogram restored from the Tab
        # cache, which holds no tacho.
        if config.tracking_mode == "rpm":
            return _read_with_tacho(request)
        return _read_vib(request), request.tacho_block
    if request.vib_block is not None:
        return request.vib_block, request.tacho_block

    if kind == KIND_SPECTRUM:
        return DataAccessor.fetch_channel_data(run_index, channel_meta), None

    if kind == KIND_ORDER_CUT or config.tracking_mode == "rpm":
        return _read_with_tacho(request)
    return DataAccessor.fetch_channel_data(run_index, channel_meta), request.tacho_block


def _read_vib(request: LiveRequest):
    """The vibration channel: the block the request carries, else read from disk."""
    if request.vib_block is not None:
        return request.vib_block
    return DataAccessor.fetch_channel_data(request.run_index, request.channel_meta)


def _read_with_tacho(request: LiveRequest):
    """
    The vibration channel and a tacho: the one the view holds, else
    `tacho_meta`, else the file's own (`find_tacho_channel`, ADR §1.197). A
    file with no tacho gives None for it, for the compute to refuse; a tacho
    that does not read fails the read like the vibration channel would.
    """
    vib_block = _read_vib(request)
    if request.tacho_block is not None:
        return vib_block, request.tacho_block
    tacho_meta = request.tacho_meta or find_tacho_channel(request.run_index)
    if tacho_meta is None:
        return vib_block, None
    return vib_block, DataAccessor.fetch_channel_data(request.run_index, tacho_meta)


def _run_dsp(request: LiveRequest, vib_block, tacho_block, tracking: Optional[TrackingScratch]):
    """The blocks a miss turns its channels into: `(blocks, notices)`."""
    config = request.config
    kind = request.block_kind

    def _tracked(compute_fn):
        if tracking is None:
            return compute_fn(vib_block, tacho_block, config)
        return tracking.compute(compute_fn, vib_block, tacho_block, config)

    if kind == KIND_SPECTRUM:
        return [compute_spectrum(vib_block, config)], ()

    if kind == KIND_SPECTROGRAM:
        if config.tracking_mode == "rpm" and tacho_block is None:
            # Nothing switches to Time mode by itself; say what to do instead
            # (audit 02, finding S3/3.4).
            raise ValueError(
                "RPM Tracking is on but this file has no tacho channel. "
                "Set the ribbon to Time mode to view this channel."
            )
        block = _tracked(compute_spectrogram)
        # An rpm axis the image cannot draw truthfully (#434).
        require_uniform_rpm_axis(block)
        return [block], ()

    if kind == KIND_ORDER_CUT:
        if tacho_block is None:
            raise ValueError("Tacho channel is strictly required for Order Tracking.")
        compute_fn = compute_order_cuts
        if request.with_overall_level:
            compute_fn = partial(compute_order_cuts, with_overall_level=True)
        blocks = _tracked(compute_fn)
        missing = build_overall_level_missing_line(blocks) if request.with_overall_level else None
        return blocks, ((missing,) if missing else ())

    if kind == KIND_OVERALL_LEVEL:
        if config.tracking_mode == "rpm" and tacho_block is None:
            raise ValueError("Tacho channel is strictly required for Overall Level tracked against RPM.")
        return [_tracked(compute_overall_level)], ()

    raise ValueError(f"no live compute for block kind '{kind}'")
