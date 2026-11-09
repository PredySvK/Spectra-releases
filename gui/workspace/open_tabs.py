# =====================================================================
# FILE: gui/workspace/open_tabs.py
# =====================================================================
"""
The open-tabs lifecycle: capturing the tab set for a Save and rebuilding it on
Open.

`OpenTabs` is owned by `Workspace`, which keeps the public names callers know
(`capture_open_tabs_spec`, `restore_open_tabs`) as thin delegates. The capture
is handed to `ProjectSession.set_open_tabs_capture`, so every write -- not only
an explicit Save -- stores the tabs as they are now. It drives the workspace only through `build_shell` /
`base_curve_compute.start`, the same pair a fresh open uses.

One fact about a dock lives here instead of as an attribute written onto the
widget, the *restored spec*: the whole saved `TabSpec` the tab was rebuilt from,
kept while the tab stays a placeholder so its overlays and result sets survive a
Save. A Dead link and a failed compute are the dock's own: its Tab label is
built from them.

The names of the Tab cache files a tab's curves save are not kept here: `capture` takes them
from the workspace's `tab_cache.TabCacheFiles`, and `restore` fills it with
the names the saved traces carry.
"""

import weakref
from typing import Any, Dict, List, Optional

from core.jobs import job_step
from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from io_modules.measurement_files import canonical_path
from core.channel_drop import RECIPE_KEY, TAB_CACHE_KEY, build_drop_descriptor
from orchestration.live_compute import ComputeOrigin
from orchestration.open_tabs import (
    build_base_trace_spec, build_overlay_trace_specs, build_tab_spec,
)
from orchestration.tab_cache import TabCacheCurve
from session.data_pool import DeadLink
from session.open_tabs import TabSpec, TraceSpec, build_restore_plan
from session.project import channel_label_for

class OpenTabs:
    def __init__(self, workspace):
        self._ws = workspace
        # Weak, so a closed dock takes its state with it.
        self._restored_specs: "weakref.WeakKeyDictionary[Any, TabSpec]" = weakref.WeakKeyDictionary()

    def restored_spec(self, dock) -> Optional[TabSpec]:
        return self._restored_specs.get(dock)

    def mark_restored(self, dock, spec: TabSpec) -> None:
        self._restored_specs[dock] = spec
        self._ws.tab_cache_files.restore_tab(dock.dock_id, spec.traces)

    # ---- capture ---------------------------------------------------------
    def _base_trace_spec(self, dock) -> Optional[TraceSpec]:
        """The live recipe for `dock`'s base curve, None while it has no run yet.
        A graph opened with several channels at once has no run of its own and
        is named by its base curve instead."""
        if dock.run_index is None or dock.channel_meta is None:
            if isinstance(dock, GraphDock):
                return build_base_trace_spec(dock.curves, self._ws.app_context.pool.loaded_runs)
            return None
        compute_spec = None
        model = dock.curves.model if isinstance(dock, GraphDock) else None
        if model is not None:
            base_trace = next((t for t in model.traces if t.is_base), None)
            if base_trace is not None:
                compute_spec = base_trace.compute_spec
        elif isinstance(dock, SpectrogramDock) and dock.spectrogram.model is not None:
            compute_spec = dock.spectrogram.model.compute_spec
        return TraceSpec(
            source_id=canonical_path(dock.run_index.file_path),
            channel_name=channel_label_for(dock.run_index, dock.channel_meta),
            compute_spec=compute_spec,
            is_base=True,
            tab_cache_file=self._ws.tab_cache_files.name(TabCacheCurve(dock.dock_id)),
        )

    def _overlay_trace_specs(self, dock) -> List[TraceSpec]:
        """
        Every non-base curve on `dock` as a `TraceSpec`, the identity its base
        curve is saved under (#291). A `SpectrogramDock` has no `GraphCurves`
        (one `ImageItem`, no overlay concept) -- it saves none.
        """
        if not isinstance(dock, GraphDock):
            return []
        return build_overlay_trace_specs(dock.curves, self._ws.app_context.pool.loaded_runs,
                                         self._ws.tab_cache_files.dropped_channel_names(dock.dock_id))

    def capture(self) -> List[Dict[str, Any]]:
        """
        The workspace's tabs -> one `TabSpec` dict per live analytical dock, in
        tab order.

        The startup placeholder is excluded on purpose (session persistence plan, "out of scope"). A dock loaded
        with h5 content instead of a run+channel (ARCHITECTURE_DECISIONS
        §1.30) is not excluded by identity any more -- it simply has no base
        trace to recover here yet (_base_trace_spec returns None without a
        run_index/channel_meta), the same way an empty dock does; today that
        is only ever the placeholder itself (no other path opens a dock
        without a base channel), so it never actually loses h5 content here.
        """
        ws = self._ws
        placeholder = ws.placeholder_graph
        panel = ws.filter_panel
        specs: List[Dict[str, Any]] = []
        for idx in range(ws.tabs.count()):
            dock = ws.tabs.widget(idx)
            if dock is placeholder:
                continue
            if not isinstance(dock, (GraphDock, SpectrogramDock)):
                continue
            # Until a restored graph's base curve lands, its saved overlays and
            # result sets are not on the dock (#384).
            awaiting_base = (
                isinstance(dock, GraphDock)
                and not (dock.curves.model is not None and any(t.is_base for t in dock.curves.model.traces))
            )
            spec = build_tab_spec(
                analysis_kind=dock.analysis_kind,
                dock_id=dock.dock_id,
                base=self._base_trace_spec(dock),
                dead_link=dock.dead_link,
                restored=self.restored_spec(dock),
                awaiting_base=awaiting_base,
                overlays=self._overlay_trace_specs(dock),
                # A set whose read is still queued is saved too -- a Refresh
                # puts every loaded set back in that state for a moment (#427).
                loaded_result_set_ids=(
                    sorted(dock.curves.loaded_or_pending_result_set_ids) if isinstance(dock, GraphDock) else []
                ),
                filter_selections=(
                    panel.selection_store.export_local_selections_for_dock(dock.dock_id)
                    if panel is not None else {}
                ),
                evaluation_config=dock.evaluation_config,
                custom_label=dock.custom_tab_label,
                legend_config=dock.curves.legend_config if isinstance(dock, GraphDock) else None,
            )
            if spec is not None:
                specs.append(spec.to_dict())
        return specs

    # ---- restore ---------------------------------------------------------
    def restore(self) -> None:
        """
        Rebuilds every dock the project's `open_tabs` (S5) recorded, split
        the same way a fresh open already is (`build_shell` / `base_curve_compute.start`,
        S4): every shell goes up first, synchronously, so the tab strip is
        complete the moment the project opens; the background reads + DSP that
        then fill each one in are paced through QtJobRunner rather than firing
        all N at once -- a project reopened with eight tabs would otherwise
        start eight disk reads in the same instant (PLAN.md §6 risk).

        The job's steps do no real work themselves -- no disk, no DSP; both
        happen inside `base_curve_compute.start`, which touches Qt (dock titles,
        `dock_tasks`) and so must run on the GUI thread, exactly where
        QtJobRunner's `on_step` callback lands. The steps exist only so
        QtJobRunner's own queue paces *when* each `start` call
        happens, and so the restore shows up as one cancellable entry in the
        Jobs dock instead of an instantaneous, unwatchable burst -- letting the
        user close a tab that is still mid-restore the same way they could
        cancel any other multi-file background job.

        Call once, right after the pool is populated -- `session.data_pool` needs `app_context.pool.loaded_runs` filled in, which
        `restore_pool_from_project` already does synchronously from the
        project's own stored snapshot before this can run (see
        ProjectDocumentHandler.load_project_pool). Same call site as
        `FilterRoutingHandler.restore_filter_state`
        (orchestration.project_swap).
        """
        ws = self._ws
        raw_specs = ws.app_context.project_session.project.open_tabs
        if not raw_specs:
            return

        restore_plan = build_restore_plan(raw_specs, ws.app_context.pool.loaded_runs)
        for notice in restore_plan.notices:
            if hasattr(ws.app_context, "log"):
                ws.app_context.log(f"WARNING: {notice}")

        panel = ws.filter_panel
        docks = []
        for restored_tab in restore_plan.tabs:
            spec = restored_tab.spec
            resolved = restored_tab.resolved
            dock = ws.build_shell(
                spec.analysis_kind, resolved,
                evaluation_config=restored_tab.evaluation_config,
                dock_id=spec.dock_id,
                custom_tab_label=spec.custom_label,
                legend_config=spec.legend_config,
            )
            # What `capture` writes back, whole, for as long as this tab stays
            # a "Missing" placeholder -- resolved dead here or turned into one
            # by a failed read (`BaseCurveCompute.fail`) -- so its overlays
            # and result sets survive a Save along with it.
            self.mark_restored(dock, spec)
            if spec.filter_selections and panel is not None:
                # build_shell already applied the active filter once, against
                # this dock's still-empty (profile, dock) selection -- reapply
                # now that its saved Local content has actually landed, or a
                # restored graph would silently ignore its own saved filter
                # until the user switched tabs away and back (T5).
                panel.selection_store.import_local_selections_for_dock(
                    dock.dock_id, spec.filter_selections)
                if ws.filter_routing is not None:
                    ws.filter_routing.apply_active_filter_to_dock(dock)
            if not isinstance(resolved, DeadLink):
                # Re-dropped / reloaded once the base curve lands
                # (`_restore_pending_overlays`, the same consumer a Refresh
                # feeds), each overlay from the channel the pool resolved it
                # to now. A SpectrogramDock saves neither (S7).
                if isinstance(dock, GraphDock) and (restored_tab.overlays or spec.loaded_result_set_ids):
                    dock.curves.expect_saved_restore(
                        overlays=[_overlay_descriptor(o) for o in restored_tab.overlays],
                        result_set_ids=spec.loaded_result_set_ids,
                    )
                docks.append(dock)

        if not docks:
            return

        steps = [job_step(dock.dock_id, lambda: None) for dock in docks]
        ws.job_runner.submit(
            f"Restoring workspace -- {len(docks)} tab(s)", steps, lane="batch",
            on_step=lambda _payload, index: ws.base_curve_compute.start(
                docks[index].dock_id, origin=ComputeOrigin.RESTORE),
        )


def _overlay_descriptor(overlay) -> dict:
    """The drop descriptor a restored overlay is re-dropped with: its channel
    and, when the project saved them, its own recipe (#726) and Tab cache
    file (#729, ADR §1.178)."""
    descriptor = build_drop_descriptor(overlay.run_index, overlay.channel_meta)
    if overlay.compute_spec:
        descriptor[RECIPE_KEY] = overlay.compute_spec
    if overlay.tab_cache_file:
        descriptor[TAB_CACHE_KEY] = overlay.tab_cache_file
    return descriptor
