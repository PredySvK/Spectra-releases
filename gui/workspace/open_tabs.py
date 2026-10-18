# =====================================================================
# FILE: gui/workspace/open_tabs.py
# =====================================================================
"""
The open-tabs lifecycle: capturing the tab set for a Save, rebuilding it on
Open, and the per-dock state those two (and a failed read) share.

`OpenTabs` is owned by `Workspace`, which keeps the public names callers know
(`capture_open_tabs_spec`, `restore_open_tabs`) as thin delegates. The capture
is handed to `ProjectSession.set_open_tabs_capture`, so every write -- not only
an explicit Save -- stores the tabs as they are now. It drives the workspace only through `build_shell` /
`dispatch_compute`, the same pair a fresh open uses.

Three facts about a dock live here instead of as attributes written onto the
widget (the dock does not know them, so they are not its attributes):

- *dead link* -- the recipe's file is missing or unreadable; the tab is a
  "Missing" placeholder and Save still writes its recipe back.
- *restored spec* -- the whole saved `TabSpec` the tab was rebuilt from, kept
  while the tab stays a placeholder so its overlays and result sets survive a Save.
- *compute origin* -- why the compute in flight was started (fresh open,
  restore, refresh); a failure does to the tab what
  `live_compute.plan_compute_failure` says for that origin.
- *tab cache file* -- the name of the base curve's Tab cache file, which
  Save writes into the base `TraceSpec`, and one per dropped channel, which
  Save writes into that overlay's `TraceSpec`.
"""

import weakref
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.jobs import job_step
from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from io_modules.measurement_files import canonical_path
from core.channel_drop import RECIPE_KEY, TAB_CACHE_KEY, build_drop_descriptor
from orchestration.live_compute import (
    FAILURE_CLOSE_TAB, FAILURE_MARK_FAILED, FAILURE_MARK_MISSING, PHASE_READ,
    ComputeOrigin, plan_compute_failure,
)
from orchestration.open_tabs import (
    build_base_trace_spec, build_overlay_trace_specs, build_tab_spec,
)
from session.data_pool import DeadLink
from session.open_tabs import TabSpec, TraceSpec, build_restore_plan
from session.project import channel_label_for

@dataclass
class _DockOpenState:
    dead_link: Optional[DeadLink] = None
    restored_spec: Optional[TabSpec] = None
    origin: Optional[ComputeOrigin] = None
    # The tab text a restored tab had before its compute failed, given back
    # once a later compute lands.
    tab_text_before_failure: Optional[str] = None
    tab_cache_file: Optional[str] = None
    # A dropped channel's Tab cache file, by `build_channel_key(file_path, channel_index)`.
    overlay_tab_cache_files: Dict[Tuple[str, int], str] = field(default_factory=dict)


class OpenTabs:
    def __init__(self, workspace):
        self._ws = workspace
        # Weak, so a closed dock takes its state with it.
        self._states: "weakref.WeakKeyDictionary[Any, _DockOpenState]" = weakref.WeakKeyDictionary()

    # ---- per-dock state --------------------------------------------------
    def _state(self, dock) -> _DockOpenState:
        return self._states.setdefault(dock, _DockOpenState())

    def dead_link(self, dock) -> Optional[DeadLink]:
        return self._state(dock).dead_link

    def mark_dead_link(self, dock, link: DeadLink) -> None:
        self._state(dock).dead_link = link

    def restored_spec(self, dock) -> Optional[TabSpec]:
        return self._state(dock).restored_spec

    def mark_restored(self, dock, spec: TabSpec) -> None:
        state = self._state(dock)
        state.restored_spec = spec
        base = next((t for t in spec.traces if t.is_base), None)
        state.tab_cache_file = base.tab_cache_file if base is not None else None

    def tab_cache_file(self, dock) -> Optional[str]:
        """The name of `dock`'s base-curve Tab cache file; None when it has none."""
        return self._state(dock).tab_cache_file

    def set_tab_cache_file(self, dock, name: Optional[str]) -> None:
        self._state(dock).tab_cache_file = name

    def overlay_tab_cache_file(self, dock, channel_key: Tuple[str, int]) -> Optional[str]:
        """The name of the Tab cache file of the channel dropped on `dock`
        (`channel_key` from `build_channel_key`); None when it has none."""
        return self._state(dock).overlay_tab_cache_files.get(channel_key)

    def set_overlay_tab_cache_file(self, dock, channel_key: Tuple[str, int],
                                   name: Optional[str]) -> None:
        names = self._state(dock).overlay_tab_cache_files
        if name:
            names[channel_key] = name
        else:
            names.pop(channel_key, None)

    def origin_in_flight(self, dock) -> Optional[ComputeOrigin]:
        """Why the compute in flight for `dock` was started; None when none is."""
        return self._state(dock).origin

    def start_compute(self, dock, *, origin: ComputeOrigin) -> None:
        """A compute is in flight for `dock`, started for `origin`."""
        self._state(dock).origin = origin

    def land_compute(self, dock) -> None:
        """The compute in flight landed: its origin no longer applies, and a
        tab marked failed by an earlier one gets its title back."""
        state = self._state(dock)
        state.origin = None
        if state.tab_text_before_failure is not None:
            idx = self._ws.tabs.indexOf(dock)
            if idx != -1:
                self._ws.tabs.setTabText(idx, state.tab_text_before_failure)
            state.tab_text_before_failure = None

    # ---- failed compute --------------------------------------------------
    def fail_compute(self, dock, phase: str, message: str) -> None:
        """
        The one step for a compute that will not land, for every kind:
        logs why, then does what `plan_compute_failure` says for how the
        compute was started and which `phase` failed. Nothing pending is
        given back by a later base curve unless the tab stays a restored one
        waiting for it.
        """
        ws = self._ws
        state = self._state(dock)
        origin, state.origin = state.origin, None
        if phase == PHASE_READ:
            ws.app_context.log(f"ERROR: IO block read exception: {message}")
        else:
            ws.app_context.log(f"ERROR: {message}")

        action = plan_compute_failure(origin, phase)
        if action == FAILURE_CLOSE_TAB:
            ws._remove_dock_tab(dock)
        elif action == FAILURE_MARK_MISSING and self.restored_spec(dock) is not None:
            self._mark_unreadable(dock)
        elif action == FAILURE_MARK_FAILED and self.restored_spec(dock) is not None:
            self._mark_failed(dock)
        else:
            # The recompute will not land: a pending restore left in place
            # would be re-dropped by the next unrelated base curve (audit 02,
            # finding S3/3.9).
            if isinstance(dock, GraphDock):
                dock.curves.abort_restore()
            dock.plot_widget.setTitle("Computation failed - see System Log")

    def _mark_unreadable(self, dock) -> None:
        """
        A restored tab whose file could not be read: the same "Missing"
        placeholder a `DeadLink` gets (#385). The pool snapshot still lists a
        file whose drive is not mounted this session, so the tab resolved live
        and only its read can tell. Dropping it would let the next Save write
        `open_tabs` without it, and it would never come back once the drive
        does.
        """
        ws = self._ws
        base = self.restored_spec(dock).traces[0]
        self.mark_dead_link(dock, DeadLink(base.source_id, base.channel_name, reason="file_unreadable"))
        dock.run_index = None
        dock.channel_meta = None
        if isinstance(dock, GraphDock):
            dock.curves.abort_restore()
        dock.plot_widget.setTitle("Source file could not be read - see System Log")
        idx = ws.tabs.indexOf(dock)
        if idx != -1:
            ws.tabs.setTabText(idx, f"⚠ Missing: {base.channel_name}")
        ws.app_context.log(
            f"WARNING: could not restore '{base.channel_name}' (file_unreadable)."
        )

    def _mark_failed(self, dock) -> None:
        """
        A restored tab whose file read but whose compute failed (an empty
        Overall Level band, say). The file is fine, so this is no dead link:
        the tab stays live with its channel, Save keeps it with its saved
        overlays and result sets (`capture`, `awaiting_base`), and a Refresh
        with other settings lands it -- its pending restore is kept for that.
        """
        ws = self._ws
        base = self.restored_spec(dock).traces[0]
        dock.plot_widget.setTitle("Computation failed - see System Log")
        idx = ws.tabs.indexOf(dock)
        if idx != -1:
            state = self._state(dock)
            if state.tab_text_before_failure is None:
                state.tab_text_before_failure = ws.tabs.tabText(idx)
            ws.tabs.setTabText(idx, f"⚠ Failed: {base.channel_name}")
        ws.app_context.log(
            f"WARNING: could not restore '{base.channel_name}' (compute failed) -- "
            f"change the settings and Refresh."
        )

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
        model = dock.curves.model if hasattr(dock, "curves") else None
        if model is not None:
            base_trace = next((t for t in getattr(model, "traces", []) if t.is_base), None)
            if base_trace is not None:
                compute_spec = base_trace.compute_spec
        elif isinstance(dock, SpectrogramDock) and dock.spectrogram.model is not None:
            compute_spec = dock.spectrogram.model.compute_spec
        return TraceSpec(
            source_id=canonical_path(dock.run_index.file_path),
            channel_name=channel_label_for(dock.run_index, dock.channel_meta),
            compute_spec=compute_spec,
            is_base=True,
            tab_cache_file=self.tab_cache_file(dock),
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
                                         self._state(dock).overlay_tab_cache_files)

    def capture(self) -> List[Dict[str, Any]]:
        """
        The workspace's tabs -> one `TabSpec` dict per live analytical dock, in
        tab order.

        The startup placeholder is excluded on purpose (ideas/
        session_persistence/PLAN.md §1 "Čo NIE je v rozsahu"). A dock loaded
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
                dead_link=self.dead_link(dock),
                restored=self.restored_spec(dock),
                awaiting_base=awaiting_base,
                overlays=self._overlay_trace_specs(dock),
                # A set whose read is still queued is saved too -- a Refresh
                # puts every loaded set back in that state for a moment (#427).
                loaded_result_set_ids=(
                    sorted(dock.curves.loaded_or_pending_result_set_ids) if hasattr(dock, "curves") else []
                ),
                filter_selections=(
                    panel.selection_store.export_local_selections_for_dock(dock.dock_id)
                    if panel is not None else {}
                ),
                evaluation_config=dock.evaluation_config,
            )
            if spec is not None:
                specs.append(spec.to_dict())
        return specs

    # ---- restore ---------------------------------------------------------
    def restore(self) -> None:
        """
        Rebuilds every dock the project's `open_tabs` (S5) recorded, split
        the same way a fresh open already is (`build_shell` / `dispatch_compute`,
        S4): every shell goes up first, synchronously, so the tab strip is
        complete the moment the project opens; the background reads + DSP that
        then fill each one in are paced through QtJobRunner rather than firing
        all N at once -- a project reopened with eight tabs would otherwise
        start eight disk reads in the same instant (PLAN.md §6 risk).

        The job's steps do no real work themselves -- no disk, no DSP; both
        happen inside `dispatch_compute`, which touches Qt (dock titles,
        `dock_tasks`) and so must run on the GUI thread, exactly where
        QtJobRunner's `on_step` callback lands. The steps exist only so
        QtJobRunner's own queue paces *when* each `dispatch_compute` call
        happens, and so the restore shows up as one cancellable entry in the
        Jobs dock instead of an instantaneous, unwatchable burst -- letting the
        user close a tab that is still mid-restore the same way they could
        cancel any other multi-file background job.

        Call once, right after the pool is populated -- `session.data_pool` needs `app_context.pool.loaded_runs` filled in, which
        `restore_pool_from_project` already does synchronously from the
        project's own stored snapshot before this can run (see
        ProjectDocumentHandler.load_project_pool). Same call site as
        `FilterRoutingHandler.restore_filter_state`
        (ProjectDocumentHandler.open_project).
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
            )
            # What `capture` writes back, whole, for as long as this tab stays
            # a "Missing" placeholder -- resolved dead here or turned into one
            # by a failed read (fail_compute) -- so its overlays
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
            on_step=lambda _payload, index: ws.dispatch_compute(docks[index], origin=ComputeOrigin.RESTORE),
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
