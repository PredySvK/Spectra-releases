# =====================================================================
# FILE: gui/handlers/result_content.py
# =====================================================================
"""
Reads checked h5 result sets into an ordinary dock's content -- the one path
by which computed results get onto a graph that is not the Filter panel's
mask (that stays gui.handlers.filter_routing.apply_active_filter_to_dock).

ARCHITECTURE_DECISIONS §1.30 / §1.31: a dock's h5 curves, its dropped channels
and its live computations all live side by side in the same PlotModel; loading
more result sets never narrows what is already there. Removing a set again goes
through unload_result_sets_from_dock, which drops exactly the traces carrying
that set's id (Trace.result_set_id) and leaves everything else alone. Membership
is Trace.result_set_id plus the dock's GraphCurves.loaded_result_set_ids
(view_models.plot), not a second dict in the Result Pool panel.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Iterable, Optional

import numpy as np
from PySide6.QtWidgets import QWidget

from core.jobs import JobState, job_step
from view_models.trace_filter import resolve_stored_curves_already_held
from io_modules.result_cache.compare_curve_reader import read_result_curves
from orchestration.result_sets import plan_result_set_load

# QSettings key (main_window_frame.app_context.shared_settings) for how many
# curves "Load Result Sets…" will read without asking first -- a project-wide
# tuning knob, not a per-window one, same reasoning as result_cache_compression
# in main_window.py. 500 is a starting point to revisit once a real project's
# result sets have been loaded through this a few times.
_CURVE_LIMIT_KEY = "result_content_curve_limit"
_DEFAULT_CURVE_LIMIT = 500


def _append_curve_to_dock(dock, curve: dict) -> None:
    """
    One loaded curve becomes one Trace on `dock` via dock.add_curve (#276).
    """
    x = np.asarray(curve["x"], dtype=np.float64)
    y = np.asarray(curve["y"], dtype=np.float64)
    x_quantity = curve.get("x_quantity", "")
    compute_spec = curve.get("compute_spec")
    result_set_id = curve.get("result_set_id", "")
    block = curve.get("block")

    dock.add_curve(
        x=x,
        y=y,
        source_label=curve.get("label", ""),
        incoming_unit=curve.get("unit", ""),
        source_meta=curve.get("meta"),
        block=block,
        compute_spec=compute_spec,
        x_quantity=x_quantity,
        result_set_id=result_set_id,
        title=curve.get("label", ""),
    )


class ResultContentHandler:
    """
    Coordinates loading result sets into docks.
    """

    def __init__(self, app_context, find_dock, job_manager, parent_widget: Optional[QWidget] = None):
        self.app_context = app_context
        self.find_dock = find_dock
        self.job_manager = job_manager
        self.parent_widget = parent_widget

    def load_into_dock(self, dock, ref_ids: Iterable[str]) -> None:
        """
        Reads the given result sets' curves onto `dock`, alongside whatever it
        already shows.

        Resolution (which files/channels to read) is delegated to the pure
        orchestration plan from the in-memory project -- no filter selection is
        involved, since narrowing what is shown is the Local mask's job now
        (apply_active_filter_to_dock), not this file's. The actual h5 reads run in
        the background as a
        QtJobRunner job, one step per result set, no slot_key -- the project pattern
        for "background work with progress or Cancel". Steps queue rather than
        supersede each other, so checking several sets in a row delivers all of
        them; _run_dock_task would keep only the last (ARCHITECTURE_DECISIONS
        §1.31). Each step re-resolves its dock via find_dock_by_id and drops its
        result silently if the dock has since been closed.

        A result set already loaded onto this dock, or already queued from an
        earlier call whose read has not landed yet, is skipped -- calling this
        twice in a row with the same ids before the first read lands must not
        submit a second job or duplicate curves.

        A curve the dock already shows from a live compute is not drawn a
        second time either: the live curve is adopted into the result set
        (#116).
        """
        context = self.app_context
        session = context.project_session

        already_accounted = set(dock.curves.loaded_or_pending_result_set_ids)
        # Marks this dock as a result-content dock from this call on, even if
        # new_ids turns out empty -- gui.file_explorer.actions.channel_drop reads
        # GraphCurves.holds_result_content to decide whether a manually dropped
        # channel needs the multi-source (per-file tacho, "ask before computing")
        # treatment a dock that has never loaded any h5 curve does not.
        dock.curves.mark_holds_result_content()
        limit = _DEFAULT_CURVE_LIMIT
        settings = getattr(context, "shared_settings", None)
        if settings is not None:
            limit = int(settings.value(_CURVE_LIMIT_KEY, _DEFAULT_CURVE_LIMIT))
        plan = plan_result_set_load(session.project, session.path, ref_ids, already_accounted, limit)
        for message in plan.messages:
            context.log(message)
        if not plan.read_plan:
            return

        if plan.over_limit:
            from PySide6.QtWidgets import QMessageBox

            choice = QMessageBox.question(
                self.parent_widget, "Load many curves?",
                f"This will read up to {plan.estimated_curves} curve(s), more than the configured "
                f"limit of {limit}.\n\nLoad anyway?",
            )
            if choice != QMessageBox.StandardButton.Yes:
                context.log("SYSTEM: Load Result Sets cancelled -- over the curve-count limit.")
                return

        # Queued from here on -- counted as accounted for (checkbox stays
        # checked, a second tick submits nothing new) until _on_step lands
        # the curves or unload_result_sets cancels it.
        dock.curves.request_result_sets(item["ref_id"] for item in plan.read_plan)

        dock_id = dock.dock_id
        find_dock = self.find_dock
        read_plan = list(plan.read_plan)
        totals = {"curves": 0, "channels": 0, "adopted": 0}
        next_index = 0
        buffered = {}
        failed = set()

        def _apply_step(step_index: int, payload) -> None:
            curves, matched_channel_count, warnings = payload
            # The dock may have been closed while this step waited its turn; a
            # superseded compute could also have swapped the model underneath us.
            # find_dock is the only guard left after dropping _run_dock_task.
            live = find_dock(dock_id) if find_dock is not None else None
            if live is None:
                return

            ref_id = read_plan[step_index]["ref_id"]
            for message in warnings:
                context.log(f"WARNING: {message}")

            sources_by_id = {source.id: source for source in session.project.sources}
            # One result set = one draw and one round of signals, not one per
            # curve (#440). land_result_set still stamps the set loaded first.
            with live.curves.coalesce_changes():
                landing = live.curves.land_result_set(
                    ref_id, curves,
                    lambda stored, held: resolve_stored_curves_already_held(
                        stored, held, session.sources_by_path(), sources_by_id,
                    ),
                )
                if landing is None:
                    return
                totals["adopted"] += landing.adopted
                # source_path / channel_index: what lets the Trace filter resolve the
                # curve's measurement (identity_for_trace). Not `file_path`, which
                # the drop de-duplication reads as "this channel is already plotted".
                path_by_source_id = {entry.id: path for path, entry in session.sources_by_path().items()}
                for curve in landing.to_draw:
                    meta = {**(curve.get("meta") or {}), "channel_index": curve.get("channel_index"),
                            "source_path": path_by_source_id.get(curve.get("source_id", ""))}
                    _append_curve_to_dock(live, {**curve, "meta": meta})
            totals["curves"] += len(curves)
            totals["channels"] += matched_channel_count

        def _drain_ready() -> None:
            nonlocal next_index
            while next_index in buffered or next_index in failed:
                if next_index in buffered:
                    payload = buffered.pop(next_index)
                    _apply_step(next_index, payload)
                else:
                    failed.remove(next_index)
                next_index += 1

        def _on_step(payload, index) -> None:
            # Parallel job steps report out of order with max_parallel > 1 (#375).
            # Buffer and apply in contiguous order so curve colours and legend order
            # follow read_plan rather than thread completion order.
            buffered[index] = payload
            _drain_ready()

        def _on_error(message, index) -> None:
            context.log(f"ERROR: Load Result Sets failed: {message}")
            live = find_dock(dock_id) if find_dock is not None else None
            if live is not None:
                live.curves.abandon_result_sets([read_plan[index]["ref_id"]])
            failed.add(index)
            _drain_ready()

        def _on_done(record) -> None:
            live = find_dock(dock_id) if find_dock is not None else None
            if live is not None:
                if getattr(record, "state", JobState.DONE) is not JobState.DONE:
                    # Clean up pending for any steps cancelled before landing (#375, #381)
                    live.curves.abandon_result_sets(
                        [item["ref_id"] for item in read_plan]
                    )
            already_shown = (
                f" {totals['adopted']} already shown as a live curve, not drawn twice."
                if totals["adopted"] else ""
            )
            context.log(
                f"SYSTEM: Load Result Sets -- {totals['curves']} curve(s), "
                f"{totals['channels']} channel match(es).{already_shown}"
            )

        self.job_manager.submit(
            f"Load Result Sets - {len(read_plan)} set(s)",
            [job_step(item["ref_label"], read_result_curves, [item], None) for item in read_plan],
            lane="batch",
            on_step=_on_step, on_error=_on_error, on_done=_on_done,
        )


def unload_result_sets_from_dock(dock, ref_ids: Iterable[str]) -> None:
    """
    Removes every curve read from the given result sets off `dock` -- the one
    path h5 content leaves a dock by, the mirror of ResultContentHandler.load_into_dock.

    Drops the traces whose result_set_id is in `ref_ids` off GraphCurves
    (GraphCurves.unload_result_sets), which recomputes _overlay_curve_count,
    the plotted descriptors and the Local mask from scratch. If nothing is
    left, the canvas is emptied outright (dock.clear_plot()) rather than
    rendered half-drawn -- GraphCurves itself has no notion of "clear the
    canvas", only of holding curves or not. A curve with no result_set_id --
    a dropped channel, a live compute, a base curve off a measurement -- is
    never touched. Pens are not reassigned: a pen is fixed when its curve is
    built and removing other curves does not recolour what stays
    (ARCHITECTURE_DECISIONS §1.31).

    Any of `ref_ids` still queued for a read (ResultContentHandler.load_into_dock
    submitted a job but it has not landed) is dropped from the pending set too,
    so that read's ResultContentHandler._on_step sees it as no longer pending
    and discards the curves instead of adding them back after the user already
    unticked it.
    """
    if dock.curves.unload_result_sets(ref_ids):
        dock.clear_plot()
