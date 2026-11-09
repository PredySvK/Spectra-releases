"""Runs a planned channel drop: the order of its lanes, the claim-run-release
skeleton and the landing of what the lanes bring back."""

import dataclasses
import functools
import json
from typing import Any, Callable, Iterable, Mapping

from core.channel_drop import RECIPE_KEY, TAB_CACHE_KEY
from core.channel_types import CHANNEL_TYPE_TACHO
from view_models.analysis_kinds import resolve_analysis_kind, resolve_imported_analysis_kind
from view_models.plot import overall_level_band_differs_from_dock

from orchestration.channel_drop._drop_plan import plan_channel_drop
from orchestration.channel_drop._drop_target import DropTarget, OrderDropInputs
from orchestration.channel_drop._dropped_channels import (
    DroppedChannel,
    resolve_dropped_channels,
    resolve_tacho_per_file,
)
from orchestration.channel_drop._pending_drops import PendingDrops
from orchestration.channel_drop._routing import drop_key
from orchestration.channel_drop._result_content_drop_config import resolve_result_content_drop_config
from orchestration.channel_drop._spectrogram_routing import decide_spectrogram_drop
from orchestration.channel_drop._spectrum_drop_config import resolve_spectrum_drop_config
from orchestration.tab_cache import build_tab_cache_hit_line


@dataclasses.dataclass(frozen=True)
class _Run:
    """What the lanes of one drop share."""

    target: DropTarget
    pending_drops: PendingDrops
    workers: Any
    # Files already refused in this drop: it may run as several tasks, and a
    # file gets one error all the same.
    refused_paths: set = dataclasses.field(default_factory=set)

    def resolve(self, descriptors) -> list[DroppedChannel]:
        """The pooled channels ``descriptors`` name; the rest refused in the log."""
        return resolve_dropped_channels(descriptors, self.target.run_lookup, self.target.log,
                                        refused_paths=self.refused_paths)


@dataclasses.dataclass(frozen=True)
class _Landing:
    """One curve a background lane brought back, as the run lands it.

    ``result`` is the ``LiveResult`` it came in -- None for a raw time
    channel, which is drawn and nothing else; ``draw`` draws it on the target.
    """

    descriptor: dict
    channel_name: str
    result: Any
    draw: Callable[[], None]


def run_channel_drop(target: DropTarget, descriptors: Iterable[dict], *,
                     pending_drops: PendingDrops, workers,
                     batch_label: str | None = None, from_refresh: bool = False) -> bool:
    """Serve a drop on ``target``; True once any of it was accepted.

    ``pending_drops`` is the dock's record of drops in flight; ``workers`` is
    ``orchestration.live_compute`` -- its background functions and its
    cache-hit line builders (same floor, so the caller hands it in).
    ``from_refresh`` says a Refresh re-drops these channels: on a dock holding
    result sets they obey the ribbon instead of fitting the dock.

    Accepted is not "drawn": the background lanes land their curves later, in
    their success callback on the GUI thread (``_land``). A channel that fails
    is logged and does not stop its siblings.
    """
    facts = target.facts
    run = _Run(target, pending_drops, workers)
    plan = plan_channel_drop(
        descriptors, facts, facts.plotted_keys,
        pending_drops.keys(),
        lambda: target.order_inputs().config.orders_to_extract,
        _result_content_orders(target, from_refresh),
    )
    if plan.is_empty:
        return False
    routing = plan.routing

    if plan.count > 1:
        target.log(f"SYSTEM: Processing {plan.count} dropped channels in the background.")

    accepted = 0

    if routing.imported:
        # An Imported result is read, never computed: it joins a graph that shows its kind
        # and opens a tab of its own anywhere else.
        shown_here = [desc for desc in routing.imported if facts.is_graph
                      and resolve_imported_analysis_kind(desc.get("block_kind")) == facts.analysis_kind]
        elsewhere = [desc for desc in routing.imported if desc not in shown_here]
        if shown_here:
            accepted += _run_read(run, _IMPORTED, shown_here, batch_label)
        opened = run.resolve(elsewhere)
        if opened:
            target.open_imported_channels(opened)
        accepted += len(opened)

    result_content_lane = _RESULT_CONTENT_REFRESH if from_refresh else _RESULT_CONTENT
    for group in plan.result_content_groups:
        accepted += _run_orders(run, result_content_lane, group.descriptors, group.orders, batch_label)

    for group in plan.order_groups:
        accepted += _run_orders(run, _ORDER_TRACKING, group.descriptors, group.orders, batch_label)

    if routing.overall_level:
        accepted += _run_overall_level(run, routing.overall_level, batch_label)

    for lane, lane_descriptors in ((_TIME, routing.time), (_SPECTRUM, routing.spectrum),
                                   (_SPECTROGRAM, routing.spectrogram)):
        if lane_descriptors:
            # Accepted for processing -- the curves land later, in the task's success callback.
            accepted += _run_read(run, lane, lane_descriptors, batch_label)

    if accepted > 0:
        # A spectrogram holds no curves to count; its title is set as it computes.
        if not facts.is_spec:
            target.refresh_tab_label()
        return True
    return False


def _run_claimed(run: _Run, descriptors, worker, *args, render, **run_kwargs) -> None:
    """The one claim-run-release skeleton of every background drop lane.

    Claims the Pending drop, runs ``worker(*args)`` through ``target.run_task``
    and releases the claim in both the success and the error callback, so a
    lane cannot forget a release. The worker returns ``(rendered, log_lines)``;
    ``render(rendered)`` lands it on the GUI thread.
    """
    target = run.target
    run.pending_drops.claim(descriptors)

    def _on_success(payload):
        run.pending_drops.release(descriptors)
        rendered, log_lines = payload
        for line in log_lines:
            target.log(line)
        render(rendered)

    def _on_error(message):
        run.pending_drops.release(descriptors)
        target.log(f"ERROR: Dropped channel processing failed: {message}")

    target.run_task(worker, *args, on_success=_on_success, on_error=_on_error, **run_kwargs)


def _by_recipe(channels) -> list[tuple[dict | None, list[DroppedChannel]]]:
    """``channels`` split by the saved recipe their descriptors carry
    (``RECIPE_KEY``), in drop order; a drop of new channels carries none and
    stays one group.

    One task serves one config, so restored overlays saved with different
    recipes are computed in as many tasks.
    """
    groups: dict[str | None, tuple[dict | None, list[DroppedChannel]]] = {}
    for channel in channels:
        recipe = channel.descriptor.get(RECIPE_KEY) or None
        key = None if recipe is None else json.dumps(recipe, sort_keys=True, default=str)
        groups.setdefault(key, (recipe, []))[1].append(channel)
    return list(groups.values())


def _config_of(target: DropTarget, recipe, channels, read_drop_config):
    """``(config, restore)`` of one group: the config is ``read_drop_config()``
    for a new drop, the saved recipe over the ribbon for restored overlays;
    ``restore`` is what restored overlays bring to the worker -- their Tab
    cache files and the recipe line -- None for a drop of new channels
   ."""
    resolved = target.restored_config(recipe) if recipe is not None else None
    config = read_drop_config() if resolved is None else resolved.config
    restored = resolved is not None or any(channel.descriptor.get(TAB_CACHE_KEY) for channel in channels)
    return config, (target.drop_restore(resolved) if restored else None)


def _with_restore(worker, restore):
    """``worker`` handed what restored overlays bring along; as it is for a new drop."""
    return worker if restore is None else functools.partial(worker, restore=restore)


def _land(run: _Run, landings: Iterable[_Landing], *, what: str = "FFT settings") -> None:
    """The one landing sequence of every background lane, on the GUI thread:
    per curve the result-set cache-hit line, the draw, the Tab cache hit line
    and the keep; the whole drop as one draw; then the title.

    The title is refreshed here because the run's own end-of-drop refresh ran
    before the curves it was waiting on existed.
    """
    target, workers = run.target, run.workers
    analysis_name = resolve_analysis_kind(target.facts.analysis_kind).display_name
    with target.drawing():
        for landing in landings:
            result = landing.result
            subject = workers.build_curve_subject(analysis_name, landing.channel_name)
            if result is not None and result.from_cache:
                target.log(workers.build_cache_hit_line(subject, result.result_set_label, what=what))
            landing.draw()
            if result is not None:
                if result.from_tab_cache:
                    target.log(build_tab_cache_hit_line(subject))
                target.keep(landing.descriptor, result)
    target.refresh_tab_label()


def _land_as_read(run: _Run, channels, rendered) -> None:
    """Each block drawn as it was read -- a time signal or an Imported result;
    nothing was computed, so nothing is kept."""
    target = run.target
    _land(run, [
        _Landing(desc, desc["channel_name"], None,
                 functools.partial(target.draw_time_curve, desc, data_block))
        for desc, data_block, _spectrum_result in rendered
    ])


def _land_spectra(run: _Run, channels, rendered) -> None:
    """Each spectrum made -- or found in a cache -- drawn and kept."""
    target = run.target
    _land(run, [
        _Landing(desc, desc["channel_name"], spectrum_result,
                 functools.partial(target.draw_spectrum_curve, desc, spectrum_result.blocks[0]))
        for desc, _data_block, spectrum_result in rendered
    ])


def _land_on_spectrogram(run: _Run, channels, rendered) -> None:
    """Each channel read paired with the one the spectrogram holds; a
    spectrogram holds no curves, so nothing is drawn as one and its title is
    not the curve count either. ``channels`` are the pooled channels the task
    read, by their ``drop_key``."""
    for desc, data_block, _spectrum_result in rendered:
        _pair_spectrogram_channel(run.target, channels[drop_key(desc)], data_block)


def _pair_spectrogram_channel(target: DropTarget, channel: DroppedChannel, block) -> None:
    """Pairs a channel dropped onto a spectrogram with the one it already holds
    and, once both are there, asks the target to compute it. A refused drop
    leaves the dock as it was.

    A spectrogram restored from the Tab cache shows its image without the raw
    channels it was computed from; the one a drop does not bring is read from
    the dock's measurement by that compute.
    """
    inputs = target.spectrogram_inputs()
    decision = decide_spectrogram_drop(
        block, inputs.vib_block, inputs.tacho_block, inputs.tracking_mode,
        channel_name=channel.descriptor["channel_name"],
        measurement_path=inputs.restored_measurement_path if inputs.vib_block is None else None,
    )
    for message in decision.messages:
        target.log(message)
    if decision.is_rejected:
        return

    dropped = None
    if block.channel_type != CHANNEL_TYPE_TACHO:
        dropped = (channel.run_index, channel.channel_meta)

    target.hold_spectrogram_channels(decision.vib_block, decision.tacho_block, dropped)
    if decision.should_compute:
        target.run_spectrogram_compute()


def _land_orders(run: _Run, rendered) -> None:
    target = run.target
    _land(run, [
        _Landing(desc, ch_name, result,
                 functools.partial(target.draw_order_curves, desc, ch_name, result.blocks))
        for desc, ch_name, result in rendered
    ])


def _land_overall_level(run: _Run, rendered) -> None:
    _land(run, [
        _Landing(desc, ch_name, result,
                 functools.partial(_draw_overall_level, run.target, result.blocks[0]))
        for desc, ch_name, result in rendered
    ], what="settings")


def _draw_overall_level(target: DropTarget, block) -> None:
    """One Overall Level curve, said once per curve added when the dock's
    curves integrate a different band."""
    model = target.plot_model()
    if model is not None and model.traces and overall_level_band_differs_from_dock(model, block):
        target.log("WORKSPACE: Overall Level curves on this dock integrate different bands.")
    target.draw_overall_level_curve(block)


def _spectrum_drop_config(target: DropTarget):
    inputs = target.spectrum_inputs()
    return resolve_spectrum_drop_config(
        inputs.config, config_from_trace=inputs.config_from_trace,
        base_compute_spec=inputs.base_compute_spec,
        base_spectrum_format=inputs.base_spectrum_format, base_amplitude_mode=inputs.base_amplitude_mode)


@dataclasses.dataclass(frozen=True)
class _ReadLane:
    """What tells the read lanes -- Imported, Time, Spectrum and Spectrogram --
    apart; everything else they share in ``_run_read``. Each reads its channels
    in a background task (``read_simple_drops``).

    ``read_config(target)`` is the FFT config of the Spectrum lane, read on the
    GUI thread once per saved recipe; None for a lane that only reads, which
    neither splits by recipe nor asks the cache. ``land(run, channels,
    rendered)`` lands what the task brings back; ``job_name`` names the job
    when the caller gives no label.
    """

    read_config: Callable[[DropTarget], Any] | None
    land: Callable[[_Run, Mapping, Any], None]
    job_name: str


_IMPORTED = _ReadLane(read_config=None, land=_land_as_read, job_name="Load")
_TIME = _ReadLane(read_config=None, land=_land_as_read, job_name="Load")
_SPECTRUM = _ReadLane(read_config=_spectrum_drop_config, land=_land_spectra, job_name="Spectrum")
_SPECTROGRAM = _ReadLane(read_config=None, land=_land_on_spectrogram, job_name="Load")


def _run_read(run: _Run, lane: _ReadLane, descriptors, label: str | None) -> int:
    """One task for the channels of a read lane -- one per saved recipe on the
    Spectrum lane; how many channels the pool holds and are served."""
    channels = run.resolve(descriptors)
    if not channels:
        return 0
    if lane.read_config is None:
        _run_read_group(run, lane, channels, None, label)
        return len(channels)
    for recipe, group in _by_recipe(channels):
        # Read on the GUI thread, before the worker starts: the worker must not reach the shell.
        config, restore = _config_of(
            run.target, recipe, group, functools.partial(lane.read_config, run.target))
        _run_read_group(run, lane, group, config, label, restore)
    return len(channels)


def _run_read_group(run: _Run, lane: _ReadLane, channels, config, label: str | None,
                    restore=None) -> None:
    _run_claimed(
        run, [c.descriptor for c in channels], _with_restore(run.workers.read_simple_drops, restore),
        [(c.descriptor, c.run_index, c.channel_meta) for c in channels], config,
        run.target.cache_finder() if config is not None else None,
        render=functools.partial(lane.land, run, {drop_key(c.descriptor): c for c in channels}),
        job_label=label or f"{lane.job_name} — {len(channels)} channels",
        progress_units=len(channels),
    )


@dataclasses.dataclass(frozen=True)
class _TrackedLane:
    """What tells the tracked lanes -- Order Tracking, Result content and Overall
    Level --
    apart; everything else they share in ``_run_tracked``.

    ``read_inputs(target)`` reads the lane's inputs on the GUI thread;
    ``against_time(config)`` says the lane needs no tacho; ``refusal`` is the
    line logged for a file without one (``{file_name}``); ``worker(workers,
    inputs)`` is the background function; ``land`` lands what it brings back;
    ``job_name`` names the job when the caller gives no label.
    """

    read_inputs: Callable[[DropTarget], Any]
    against_time: Callable[[Any], bool]
    refusal: str
    worker: Callable[[Any, Any], Callable]
    land: Callable[[_Run, Any], None]
    job_name: str


_ORDER_TRACKING = _TrackedLane(
    read_inputs=lambda target: target.order_inputs(),
    against_time=lambda config: False,
    refusal=("ERROR: Cannot extract orders from '{file_name}' -- "
             "no tacho channel is available for that measurement."),
    worker=lambda workers, inputs: functools.partial(
        workers.run_order_drops, with_overall_level=inputs.with_overall_level),
    land=_land_orders,
    job_name="Order tracking",
)

_OVERALL_LEVEL = _TrackedLane(
    read_inputs=lambda target: target.overall_level_inputs(),
    against_time=lambda config: config.tracking_mode == "time",
    refusal=("ERROR: Cannot track Overall Level against RPM for '{file_name}' -- "
             "no tacho channel is available for that measurement."),
    worker=lambda workers, inputs: workers.run_overall_level_drops,
    land=_land_overall_level,
    job_name="Overall Level",
)


def _result_content_inputs(target: DropTarget, *, from_refresh: bool = False) -> OrderDropInputs:
    """The order inputs as a dock holding result sets computes with them: the
    config fits the dock -- or obeys the ribbon on a Refresh -- and the Overall
    Level switch adds no curves to it: what the dock holds is said by its
    Parameter Sets."""
    inputs = target.order_inputs()
    return dataclasses.replace(
        inputs, with_overall_level=False,
        config=resolve_result_content_drop_config(
            inputs.config, target.parameter_sets(), from_refresh=from_refresh))


_RESULT_CONTENT = dataclasses.replace(_ORDER_TRACKING, read_inputs=_result_content_inputs)
_RESULT_CONTENT_REFRESH = dataclasses.replace(
    _ORDER_TRACKING, read_inputs=functools.partial(_result_content_inputs, from_refresh=True))


def _result_content_orders(target: DropTarget, from_refresh: bool) -> Callable[[Mapping], Any]:
    """The orders a channel on the result-content lane asks for: of the config
    it will compute with, its saved recipe's when it carries one -- whose order
    list is the ribbon's, as a recipe names only its own order (ADR §1.204
    point 5). The plan reads the dock's config once, and only when the lane is
    taken."""
    read_config = functools.cache(
        lambda: _result_content_inputs(target, from_refresh=from_refresh).config)

    def read_orders(descriptor):
        recipe = descriptor.get(RECIPE_KEY)
        config = target.restored_config(recipe).config if recipe else read_config()
        return config.orders_to_extract

    return read_orders


def _run_orders(run: _Run, lane: _TrackedLane, descriptors, orders, label: str | None) -> int:
    """Order cuts of one group of channels; how many channels are served."""
    return _run_tracked(
        run, lane, descriptors, label,
        lambda config: dataclasses.replace(config, orders_to_extract=list(orders)))


def _run_overall_level(run: _Run, descriptors, label: str | None) -> int:
    """Overall Level of one drop; how many channels are served."""
    return _run_tracked(run, _OVERALL_LEVEL, descriptors, label)


def _run_tracked(run: _Run, lane: _TrackedLane, descriptors, label: str | None,
                 for_group: Callable[[Any], Any] = lambda config: config) -> int:
    """One task per saved recipe on a tracked lane; how many channels have a
    tacho (or need none) and are served. ``for_group`` finishes the config
    of each group."""
    channels = run.resolve(descriptors)
    if not channels:
        return 0
    inputs = lane.read_inputs(run.target)
    served = 0
    for recipe, group in _by_recipe(channels):
        config, restore = _config_of(run.target, recipe, group, lambda: inputs.config)
        served += _run_tracked_group(run, lane, group, for_group(config), inputs, label, restore)
    return served


def _run_tracked_group(run: _Run, lane: _TrackedLane, channels, config, inputs,
                       label: str | None, restore) -> int:
    """Tacho is resolved once per source file."""
    target = run.target
    dock_tacho_path = inputs.dock_tacho.source.file_path if inputs.dock_tacho else None
    if not lane.against_time(config):
        channels, refused = resolve_tacho_per_file(channels, dock_tacho_path)
        for channel in refused:
            path = channel.descriptor["file_path"]
            if path not in run.refused_paths:
                run.refused_paths.add(path)
                target.log(lane.refusal.format(file_name=channel.descriptor["file_name"]))
    prepared = [(c.descriptor, c.descriptor["channel_name"], c.run_index, c.channel_meta, c.tacho_meta)
                for c in channels]
    if not prepared:
        return 0

    _run_claimed(
        run, [c.descriptor for c in channels], _with_restore(lane.worker(run.workers, inputs), restore),
        prepared, target.cache_finder(), config, inputs.dock_tacho, dock_tacho_path,
        render=functools.partial(lane.land, run),
        job_label=label or f"{lane.job_name} — {len(prepared)} channels",
        progress_units=len(prepared),
    )
    return len(prepared)
