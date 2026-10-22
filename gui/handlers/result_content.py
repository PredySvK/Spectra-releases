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

from view_models.plot import build_compute_spec
from orchestration.result_sets import plan_result_set_load, run_result_set_load


def _append_curve_to_dock(dock, curve: dict) -> None:
    """
    One loaded curve becomes one Trace on `dock` via dock.add_curve (#276).
    `curve` is finished: run_result_set_load already put its meta together.
    """
    block = curve.get("block")
    # A curve that carries its block needs no x/y of its own: the block is
    # the source of both, and of its settings and axis quantity (#665 C01).
    x = np.asarray(curve["x"], dtype=np.float64) if "x" in curve else None
    y = np.asarray(curve["y"], dtype=np.float64) if "y" in curve else None
    x_quantity = curve.get("x_quantity", "")
    compute_spec = curve.get("compute_spec")
    if compute_spec is None and block is not None:
        compute_spec = build_compute_spec(block)
    result_set_id = curve.get("result_set_id", "")

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

    def __init__(self, app_context, find_dock, job_runner, parent_widget: Optional[QWidget] = None):
        self.app_context = app_context
        self.find_dock = find_dock
        self.job_runner = job_runner
        self.parent_widget = parent_widget

    def load_into_dock(self, dock, ref_ids: Iterable[str]) -> None:
        """
        Reads the given result sets' curves onto `dock`, alongside whatever it
        already shows.

        Resolution (which files/channels to read) is delegated to the pure
        orchestration plan from the in-memory project -- no filter selection is
        involved, since narrowing what is shown is the Local mask's job now
        (apply_active_filter_to_dock), not this file's. Over the curve-count
        limit this asks first; the confirmed plan then goes to
        orchestration.result_sets.run_result_set_load, which owns the whole
        background run -- pending bookkeeping, plan order, error and Cancel
        cleanup, adoption of live curves (#116) and the summary line. This
        handler only draws each finished curve on the dock (#781).

        A result set already loaded onto this dock, or already queued from an
        earlier call whose read has not landed yet, is skipped -- calling this
        twice in a row with the same ids before the first read lands must not
        submit a second job or duplicate curves.
        """
        context = self.app_context
        session = context.project_session

        already_accounted = set(dock.curves.loaded_or_pending_result_set_ids)
        limit = context.result_content_curve_limit
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

        dock_id = dock.dock_id
        find_dock = self.find_dock

        def _find_curves(target_id):
            live = find_dock(target_id) if find_dock is not None else None
            return live.curves if live is not None else None

        run_result_set_load(
            plan, session, self.job_runner, dock_id=dock_id,
            find_curves=_find_curves,
            # The run draws only after _find_curves found this dock open.
            draw_curve=lambda curve: _append_curve_to_dock(dock, curve),
            on_message=context.log,
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
   .

    Any of `ref_ids` still queued for a read (ResultContentHandler.load_into_dock
    submitted a job but it has not landed) is dropped from the pending set too,
    so that read's landing in run_result_set_load sees it as no longer pending
    and discards the curves instead of adding them back after the user already
    unticked it.
    """
    if dock.curves.unload_result_sets(ref_ids):
        dock.clear_plot()
