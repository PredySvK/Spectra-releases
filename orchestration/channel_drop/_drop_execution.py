"""Runs a planned channel drop: the order of its lanes and the claim-run-release skeleton."""

import dataclasses
import functools
from typing import Any
from typing import Iterable

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
        target.resolve_metadata,
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


def _run_simple(run: _Run, descriptors, *, is_spec: bool, is_spectrum: bool,
                label: str | None) -> None:
    """Reads every dropped channel -- and on a spectrum dock computes its FFT -- in one task."""
    target = run.target
    # Read on the GUI thread, before the worker starts: the worker must not reach the shell.
    spectrum_config = target.spectrum_config() if is_spectrum else None
    plan = plan_tacho_per_file(descriptors, {}, None, against_time=True)
    prepared = [
        (desc, mock_run, mock_meta)
        for desc, _ch_name, mock_run, mock_meta, _tacho_meta in plan.prepared
    ]
    _run_claimed(
        run, descriptors, run.workers.read_simple_drops, prepared, spectrum_config,
        render=lambda rendered: target.render_simple(rendered, is_spec=is_spec),
        job_label=label or f"{'Spectrum' if is_spectrum else 'Load'} — {len(prepared)} channels",
        progress_units=len(prepared),
    )


def _run_orders(run: _Run, descriptors, orders, label: str | None) -> int:
    """Order cuts of one group of channels in one task; how many channels have a tacho and are served."""
    target = run.target
    inputs = target.order_inputs()
    config = dataclasses.replace(inputs.config, orders_to_extract=list(orders))
    dock_tacho_path = inputs.dock_tacho.source.file_path if inputs.dock_tacho else None
    plan = plan_tacho_per_file(
        descriptors, inputs.runs_by_path, dock_tacho_path, against_time=False)
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
        functools.partial(run.workers.lookup_or_compute_order_drops,
                          with_overall_level=inputs.with_overall_level),
        prepared, inputs.project_session, config, dataclasses.asdict(config),
        inputs.dock_tacho, dock_tacho_path, inputs.use_cache,
        render=target.render_orders,
        job_label=label or f"Order tracking — {len(prepared)} channels",
        progress_units=len(prepared),
    )
    return len(prepared)


def _run_overall_level(run: _Run, descriptors, label: str | None) -> int:
    """
    Overall Level of one drop in one task; how many channels are served.
    Tacho is resolved once per source file (ADR §1.62).
    """
    target = run.target
    inputs = target.overall_level_inputs()
    config = inputs.config
    against_time = config.tracking_mode == "time"
    dock_tacho_path = inputs.dock_tacho.source.file_path if inputs.dock_tacho else None
    plan = plan_tacho_per_file(
        descriptors, inputs.runs_by_path, dock_tacho_path, against_time=against_time)
    for refusal in plan.refusals:
        target.log(
            f"ERROR: Cannot track Overall Level against RPM for "
            f"'{refusal.file_name}' -- no tacho channel is available for that measurement."
        )
    prepared = list(plan.prepared)
    if not prepared:
        return 0

    _run_claimed(
        run, [p[0] for p in prepared], run.workers.build_overall_level_drop_payloads,
        prepared, inputs.use_cache, inputs.finder, config, dataclasses.asdict(config),
        against_time, inputs.dock_tacho, dock_tacho_path,
        render=target.render_overall_level,
        job_label=label or f"Overall Level — {len(prepared)} channels",
        progress_units=len(prepared),
    )
    return len(prepared)
