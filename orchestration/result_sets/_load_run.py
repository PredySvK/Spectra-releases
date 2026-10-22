"""Runs a confirmed Load Result Sets plan: one background read per result set,
landed onto one dock's curves in plan order."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Set

from core.jobs import JobState, job_step
from io_modules.result_cache import read_result_curves
from view_models.trace_filter import resolve_stored_curves_already_held

from orchestration.jobs import JobRunner
from orchestration.result_sets._load_plan import ResultSetLoadPlan


def run_result_set_load(
    plan: ResultSetLoadPlan,
    session: Any,
    job_runner: JobRunner,
    *,
    dock_id: str,
    find_curves: Callable[[str], Any],
    draw_curve: Callable[[Dict[str, Any]], None],
    on_message: Callable[[str], None],
) -> Optional[int]:
    """Read ``plan``'s result sets onto the dock ``dock_id``; the job id, or
    None when the plan reads nothing.

    ``find_curves(dock_id)`` is the dock's ``GraphCurves``, or None once the
    dock has been closed -- a step that lands then is dropped silently.
    ``draw_curve`` draws one finished curve (its ``meta`` already carries
    ``channel_index`` and ``source_path``) on that dock; nothing else here
    touches the dock.

    The sets count as pending from the moment the job is submitted
    (``request_result_sets``) until they land, fail or are cancelled (ADR
    §1.104). One job, one step per set, no slot_key, so a second load queues
    behind the first instead of superseding it (§1.31). Steps that report out
    of order (``max_parallel`` > 1) are buffered and landed in plan order, so
    pens and legend order follow the plan (#375). A failed read abandons its
    set; a job that ends any other way than DONE abandons every set still
    pending (#375, #381). A curve the dock already shows live is adopted into
    the set, not drawn twice (#116); each set lands as one change (#440).

    The over-limit question is the caller's, asked before this is called --
    ``plan`` is the confirmed one.
    """
    read_plan = list(plan.read_plan)
    if not read_plan:
        return None

    curves_now = find_curves(dock_id)
    if curves_now is not None:
        curves_now.request_result_sets(item["ref_id"] for item in read_plan)

    totals = {"curves": 0, "channels": 0, "adopted": 0}
    next_index = 0
    buffered: Dict[int, Any] = {}
    failed: Set[int] = set()

    def _land(step_index: int, payload) -> None:
        curves, matched_channel_count, warnings = payload
        # The dock may have been closed while this step waited its turn.
        live = find_curves(dock_id)
        if live is None:
            return

        ref_id = read_plan[step_index]["ref_id"]
        for message in warnings:
            on_message(f"WARNING: {message}")

        sources_by_id = {source.id: source for source in session.project.sources}
        source_location = session.source_location
        # One result set = one draw and one round of signals, not one per
        # curve (#440). land_result_set still stamps the set loaded first.
        with live.coalesce_changes():
            landing = live.land_result_set(
                ref_id, curves,
                lambda stored, held: resolve_stored_curves_already_held(
                    stored, held, source_location.entries_by_path, sources_by_id,
                ),
            )
            if landing is None:
                return
            totals["adopted"] += landing.adopted
            # source_path / channel_index: what lets the Trace filter resolve the
            # curve's measurement (identity_for_trace). Not `file_path`, which
            # the drop de-duplication reads as "this channel is already plotted".
            path_by_source_id = source_location.paths_by_entry_id
            for curve in landing.to_draw:
                meta = {**(curve.get("meta") or {}), "channel_index": curve.get("channel_index"),
                        "source_path": path_by_source_id.get(curve.get("source_id", ""))}
                draw_curve({**curve, "meta": meta})
        totals["curves"] += len(curves)
        totals["channels"] += matched_channel_count

    def _drain_ready() -> None:
        nonlocal next_index
        while next_index in buffered or next_index in failed:
            if next_index in buffered:
                _land(next_index, buffered.pop(next_index))
            else:
                failed.remove(next_index)
            next_index += 1

    def _on_step(payload, index) -> None:
        buffered[index] = payload
        _drain_ready()

    def _on_error(message, index) -> None:
        on_message(f"ERROR: Load Result Sets failed: {message}")
        live = find_curves(dock_id)
        if live is not None:
            live.abandon_result_sets([read_plan[index]["ref_id"]])
        failed.add(index)
        _drain_ready()

    def _on_done(record) -> None:
        live = find_curves(dock_id)
        if live is not None and getattr(record, "state", JobState.DONE) is not JobState.DONE:
            live.abandon_result_sets([item["ref_id"] for item in read_plan])
        already_shown = (
            f" {totals['adopted']} already shown as a live curve, not drawn twice."
            if totals["adopted"] else ""
        )
        on_message(
            f"SYSTEM: Load Result Sets -- {totals['curves']} curve(s), "
            f"{totals['channels']} channel match(es).{already_shown}"
        )

    return job_runner.submit(
        f"Load Result Sets - {len(read_plan)} set(s)",
        [job_step(item["ref_label"], read_result_curves, [item], None) for item in read_plan],
        lane="batch",
        on_step=_on_step, on_error=_on_error, on_done=_on_done,
    )
