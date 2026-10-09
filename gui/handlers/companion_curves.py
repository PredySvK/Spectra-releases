"""Add optional paired order curves through the workspace's drop route."""

from core.block_kinds import PARAM_ORDER
from PySide6.QtCore import QObject
from orchestration.companion_curves import run_companion_curves
from orchestration.dock_tasks import PURPOSE_DROP


def _curve_identities(dock):
    model = dock.curves.model
    return {
        (meta["file_path"], meta["channel_index"], spec[PARAM_ORDER])
        for trace in (model.traces if model else [])
        for meta, spec in ((trace.meta_ref or {}, trace.compute_spec or {}),)
        if trace.x_quantity == "rpm" and "file_path" in meta
        and "channel_index" in meta and spec.get(PARAM_ORDER) is not None
    }


class CompanionCurvesHandler(QObject):
    """Observe newly landed orders; resolve their partners on a dock worker."""

    def __init__(self, app_context, dock_tasks, route_channel_drop):
        super().__init__()
        self.app_context = app_context
        self.dock_tasks = dock_tasks
        self.route_channel_drop = route_channel_drop

    def handle_curves_added(self, dock):
        session = getattr(self.app_context, "project_session", None)
        if session is None or not session.channel_pairs:
            return
        current = _curve_identities(dock)
        previous = getattr(dock, "_companion_seen", set())
        # Partners never look for partners of their own (#509); a removed one
        # is forgotten, so dropping it again by hand counts as the user's.
        added = getattr(dock, "_companion_added", set()) - (previous - current)
        dock._companion_added = added
        fresh = current - previous - added
        dock._companion_seen = current
        if not fresh:
            return

        def on_success(rows):
            current = _curve_identities(dock)
            descriptors = {}
            for origin, descriptor in rows:
                if origin not in current:
                    continue
                key = (descriptor["file_path"], descriptor["channel_index"])
                order = descriptor["orders_to_extract"][0]
                if (*key, order) in current:
                    continue
                if key not in descriptors:
                    descriptors[key] = {**descriptor, "orders_to_extract": []}
                if order not in descriptors[key]["orders_to_extract"]:
                    descriptors[key]["orders_to_extract"].append(order)
            if descriptors:
                dock._companion_added = getattr(dock, "_companion_added", set()) | {
                    (d["file_path"], d["channel_index"], order)
                    for d in descriptors.values() for order in d["orders_to_extract"]}
                self.route_channel_drop(dock, list(descriptors.values()))

        self.dock_tasks.run(
            dock.dock_id, run_companion_curves, session,
            tuple(self.app_context.pool.loaded_runs), tuple(fresh),
            tuple(session.channel_pairs),
            purpose=PURPOSE_DROP, on_success=on_success,
            on_error=lambda message: self.app_context.log(f"ERROR: Companion curves: {message}"),
        )
