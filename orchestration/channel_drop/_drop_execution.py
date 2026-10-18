"""Runs a planned channel drop: the order of its lanes and the claim-run-release skeleton."""

import dataclasses
import functools
import json
from typing import Any
from typing import Iterable

from core.channel_drop import RECIPE_KEY, TAB_CACHE_KEY
from view_models.analysis_kinds import ANALYSIS_ORDERS, ANALYSIS_SPECTRUM

from orchestration.channel_drop._drop_plan import plan_channel_drop
from orchestration.channel_drop._drop_target import DropTarget
from orchestration.channel_drop._pending_drops import PendingDrops
from orchestration.channel_drop._tacho_plan import plan_tacho_per_file


@dataclasses.dataclass(frozen=True)
class _Run:
    """What the lanes of one drop share."""

    target: DropTarget
    pending_drops: PendingDrops
    workers: Any


def run_channel_drop(target: DropTarget, descriptors: Iterable[dict], *,
                     pending_drops: PendingDrops, workers,
                     batch_label: str | None = None) -> bool:
    """Serve a drop on ``target``; True once any of it was accepted.

    ``pending_drops`` is the dock's record of drops in flight; ``workers`` the
    background functions of ``orchestration.live_compute`` (same floor, so the
    caller hands them in).

    Accepted is not "drawn": the background lanes land their curves later,
    through ``target.render_*``. A result-content channel that fails is
    logged and does not stop its siblings.
    """
    facts = target.facts
    run = _Run(target, pending_drops, workers)
    plan = plan_channel_drop(
        descriptors, facts, facts.plotted_keys,
        pending_drops.keys() | facts.live_pending_keys,
        lambda: target.order_inputs().config.orders_to_extract,
    )
    if plan.is_empty:
        return False
    routing = plan.routing

    if plan.count > 1:
        target.log(f"SYSTEM: Processing {plan.count} dropped channels in the background.")

    accepted = 0

    if routing.imported:
        if facts.is_graph and facts.analysis_kind == ANALYSIS_ORDERS:
            _run_simple(run, routing.imported, is_spec=False, is_spectrum=False, label=batch_label)
        else:
            target.open_imported_channels(routing.imported)
        accepted += len(routing.imported)

    # One job for the whole group, a step per channel (#468).
    label = batch_label or f"Order tracking — {len(routing.result_content)} channels"
    with target.result_content_batch(label):
        for desc in routing.result_content:
            try:
                if target.serve_result_content(desc):
                    accepted += 1
            except Exception as e:
                target.log(
                    f"ERROR: Dropped channel processing failed for {desc.get('channel_name', 'Unknown')}: {str(e)}")

    for group in plan.order_groups:
        accepted += _run_orders(run, group.descriptors, group.orders, batch_label)

    if routing.overall_level:
        accepted += _run_overall_level(run, routing.overall_level, batch_label)

    if routing.simple:
        _run_simple(run, routing.simple, is_spec=facts.is_spec,
                    is_spectrum=facts.is_graph and facts.analysis_kind == ANALYSIS_SPECTRUM,
                    label=batch_label)
        # Accepted for processing -- the curves land later, in the task's success callback.
        accepted += len(routing.simple)

    if accepted > 0:
        target.refresh_title()
        return True
    return False


def _run_claimed(run: _Run, descriptors, worker, *args, render, **run_kwargs) -> None:
    """The one claim-run-release skeleton of every background drop lane.

    Claims the Pending drop, runs ``worker(*args)`` through ``target.run_task``
    and releases the claim in both the success and the error callback, so a
    lane cannot forget a release. The worker returns ``(rendered, log_lines)``;
    ``render(rendered)`` draws on the GUI thread.
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


def _by_recipe(descriptors) -> list[tuple[dict | None, list[dict]]]:
    """``descriptors`` split by the saved recipe they carry (``RECIPE_KEY``),
    in drop order; a drop of new channels carries none and stays one group.

    One task serves one config, so restored overlays saved with different
    recipes are computed in as many tasks.
    """
    groups: dict[str | None, tuple[dict | None, list[dict]]] = {}
    for desc in descriptors:
        recipe = desc.get(RECIPE_KEY) or None
        key = None if recipe is None else json.dumps(recipe, sort_keys=True, default=str)
        groups.setdefault(key, (recipe, []))[1].append(desc)
    return list(groups.values())


def _config_of(target: DropTarget, recipe, descriptors, read_drop_config):
    """``(config, restore)`` of one group: the config is ``read_drop_config()``
    for a new drop, the saved recipe over the ribbon for restored overlays;
    ``restore`` is what restored overlays bring to the worker -- their Tab
    cache files and the recipe line -- None for a drop of new channels
   ."""
    resolved = target.restored_config(recipe) if recipe is not None else None
    config = read_drop_config() if resolved is None else resolved.config
    restored = resolved is not None or any(desc.get(TAB_CACHE_KEY) for desc in descriptors)
    return config, (target.drop_restore(resolved) if restored else None)


def _with_restore(worker, restore):
    """``worker`` handed what restored overlays bring along; as it is for a new drop."""
    return worker if restore is None else functools.partial(worker, restore=restore)


def _no_pool(path):
    """The lookup of a lane that never reads the pool (time mode asks for no tacho)."""
    raise AssertionError(f"the simple lane looked up {path!r} in the pool")


def _run_simple(run: _Run, descriptors, *, is_spec: bool, is_spectrum: bool,
                label: str | None) -> None:
    """Reads every dropped channel -- and on a spectrum dock computes its FFT --
    in one task, one per saved recipe the descriptors carry."""
    if not is_spectrum:
        _run_simple_group(run, descriptors, None, is_spec=is_spec, is_spectrum=False, label=label)
        return
    for recipe, group in _by_recipe(descriptors):
        # Read on the GUI thread, before the worker starts: the worker must not reach the shell.
        config, restore = _config_of(run.target, recipe, group, run.target.spectrum_config)
        _run_simple_group(run, group, config, is_spec=is_spec, is_spectrum=True, label=label,
                          restore=restore)


def _run_simple_group(run: _Run, descriptors, spectrum_config, *, is_spec: bool,
                      is_spectrum: bool, label: str | None, restore=None) -> None:
    target = run.target
    finder = target.cache_finder() if is_spectrum else None
    plan = plan_tacho_per_file(descriptors, _no_pool, None, against_time=True)
    prepared = [
        (desc, mock_run, mock_meta)
        for desc, _ch_name, mock_run, mock_meta, _tacho_meta in plan.prepared
    ]
    _run_claimed(
        run, descriptors, _with_restore(run.workers.read_simple_drops, restore),
        prepared, spectrum_config, finder,
        render=lambda rendered: target.render_simple(rendered, is_spec=is_spec),
        job_label=label or f"{'Spectrum' if is_spectrum else 'Load'} — {len(prepared)} channels",
        progress_units=len(prepared),
    )


def _run_orders(run: _Run, descriptors, orders, label: str | None) -> int:
    """Order cuts of one group of channels in one task (one per saved recipe);
    how many channels have a tacho and are served."""
    inputs = run.target.order_inputs()
    served = 0
    for recipe, group in _by_recipe(descriptors):
        config, restore = _config_of(run.target, recipe, group, lambda: inputs.config)
        served += _run_order_group(
            run, group, dataclasses.replace(config, orders_to_extract=list(orders)), inputs, label,
            restore)
    return served


def _run_order_group(run: _Run, descriptors, config, inputs, label: str | None, restore) -> int:
    target = run.target
    dock_tacho_path = inputs.dock_tacho.source.file_path if inputs.dock_tacho else None
    plan = plan_tacho_per_file(
        descriptors, inputs.run_lookup, dock_tacho_path, against_time=False)
    for refusal in plan.refusals:
        target.log(
            f"ERROR: Cannot extract orders from '{refusal.file_name}' -- "
            "no tacho channel is available for that measurement."
        )
    prepared = list(plan.prepared)
    if not prepared:
        return 0

    _run_claimed(
        run, [p[0] for p in prepared],
        functools.partial(_with_restore(run.workers.run_order_drops, restore),
                          with_overall_level=inputs.with_overall_level),
        prepared, target.cache_finder(), config, inputs.dock_tacho, dock_tacho_path,
        render=target.render_orders,
        job_label=label or f"Order tracking — {len(prepared)} channels",
        progress_units=len(prepared),
    )
    return len(prepared)


def _run_overall_level(run: _Run, descriptors, label: str | None) -> int:
    """
    Overall Level of one drop in one task (one per saved recipe); how many
    channels are served.
    Tacho is resolved once per source file.
    """
    inputs = run.target.overall_level_inputs()
    served = 0
    for recipe, group in _by_recipe(descriptors):
        config, restore = _config_of(run.target, recipe, group, lambda: inputs.config)
        served += _run_overall_level_group(run, group, config, inputs, label, restore)
    return served


def _run_overall_level_group(run: _Run, descriptors, config, inputs, label: str | None,
                             restore) -> int:
    target = run.target
    against_time = config.tracking_mode == "time"
    dock_tacho_path = inputs.dock_tacho.source.file_path if inputs.dock_tacho else None
    plan = plan_tacho_per_file(
        descriptors, inputs.run_lookup, dock_tacho_path, against_time=against_time)
    for refusal in plan.refusals:
        target.log(
            f"ERROR: Cannot track Overall Level against RPM for "
            f"'{refusal.file_name}' -- no tacho channel is available for that measurement."
        )
    prepared = list(plan.prepared)
    if not prepared:
        return 0

    _run_claimed(
        run, [p[0] for p in prepared], _with_restore(run.workers.run_overall_level_drops, restore),
        prepared, target.cache_finder(), config, inputs.dock_tacho, dock_tacho_path,
        render=target.render_overall_level,
        job_label=label or f"Overall Level — {len(prepared)} channels",
        progress_units=len(prepared),
    )
    return len(prepared)
