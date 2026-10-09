# =====================================================================
# FILE: gui/workspace/open_tabs.py
# =====================================================================
"""
The open-tabs lifecycle: capturing the tab set for a Save, rebuilding it on
Open, and the per-dock state those two (and a failed read) share.

`OpenTabs` is owned by `Workspace`, which keeps the public names callers know
(`capture_open_tabs_spec`, `persist_open_tabs`, `restore_open_tabs`) as thin
delegates. It drives the workspace only through `build_shell` /
`dispatch_compute`, the same pair a fresh open uses.

Three facts about a dock live here instead of as attributes written onto the
widget (the dock does not know them, so they are not its attributes):

- *dead link* -- the recipe's file is missing or unreadable; the tab is a
  "Missing" placeholder and Save still writes its recipe back.
- *restored spec* -- the whole saved `TabSpec` the tab was rebuilt from, kept
  while the tab stays a placeholder so its overlays and result sets survive a Save.
- *compute origin* -- whether the compute in flight is a fresh open (a failure
  drops the tab) or a refresh (a failure keeps the plot). Overall Level only.
"""

import weakref
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.jobs import job_step
from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from io_modules.measurement_files import canonical_path
from orchestration.open_tabs import (
    build_base_trace_spec, build_drop_descriptor, build_overlay_trace_specs, build_tab_spec,
)
from session.data_pool import DeadLink
from session.open_tabs import TabSpec, TraceSpec, build_restore_plan
from session.project import channel_label_for

# ui_state key the open-tab recipes are saved under (core.project_model.
# NVHProject.ui_state) -- restored once, right after the pool is populated
# (ProjectDocumentHandler.open_project), same shot as
# gui.handlers.filter_routing.FILTER_STATE_KEY.
OPEN_TABS_KEY = "open_tabs"


@dataclass
class _DockOpenState:
    dead_link: Optional[DeadLink] = None
    restored_spec: Optional[TabSpec] = None
    fresh_open: Optional[bool] = None


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
        self._state(dock).restored_spec = spec

    def start_compute(self, dock, *, is_fresh_open: bool) -> None:
        """A compute whose failure is told apart by how the tab was opened."""
        self._state(dock).fresh_open = is_fresh_open

    def finish_compute(self, dock) -> Optional[bool]:
        """Clears and returns how the compute in flight was opened, None if none was marked."""
        state = self._state(dock)
        is_fresh_open, state.fresh_open = state.fresh_open, None
        return is_fresh_open

    # ---- failed read -----------------------------------------------------
    def drop_unreadable_fresh_open(self, dock) -> None:
        """
        A fresh open whose read failed: there is nothing on screen yet, so a
        tab the user just opened is dropped. A tab `restore` rebuilt is kept
        instead, as the same "Missing" placeholder a `DeadLink` gets (#385):
        the pool snapshot still lists a file whose drive is not mounted this
        session, so the tab resolved live and only its read can tell. Dropping
        it would let the next Save write `open_tabs` without it, and it would
        never come back once the drive does.
        """
        ws = self._ws
        restored = self.restored_spec(dock)
        if restored is None:
            ws._remove_dock_tab(dock)
            return

        base = restored.traces[0]
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
        return TraceSpec(
            source_id=canonical_path(dock.run_index.file_path),
            channel_name=channel_label_for(dock.run_index, dock.channel_meta),
            compute_spec=compute_spec,
            is_base=True,
        )

    def _overlay_trace_specs(self, dock) -> List[TraceSpec]:
        """
        Every non-base curve on `dock` as a `TraceSpec`, the identity its base
        curve is saved under (#291). A `SpectrogramDock` has no `GraphCurves`
        (one `ImageItem`, no overlay concept) -- it saves none.
        """
        if not isinstance(dock, GraphDock):
            return []
        return build_overlay_trace_specs(dock.curves, self._ws.app_context.pool.loaded_runs)

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

    def persist(self) -> None:
        """
        Writes the current tab set into the project's `ui_state`.

        Called once, right before `session.save()`/`save_as()`
        (ProjectDocumentHandler.save_project/_as). Capturing at Save
        time needs no snapshot diffing to get right: whatever is open at the
        moment of Save is exactly what gets written -- this method itself
        never calls `session.mark_dirty()`.

        Dirty-tracking for *when to prompt* is separate and lives at the
        actual open/close/overlay-drop call sites (open_acc_spectrum_tab,
        close_specific_tab, channel_drop.execute_channel_drop_processing) --
        reversed 2026-09-04 from this method's original "no dirty tracking,
        opening a tab is routine navigation" call: losing an open graph
        silently on close is exactly the loss session_persistence exists to
        prevent, so it needs the same "unsaved changes" prompt as any other
        project change (ideas/session_persistence/PLAN.md S5).
        """
        session = self._ws.app_context.project_session
        session.project.ui_state[OPEN_TABS_KEY] = self.capture()

    # ---- restore ---------------------------------------------------------
    def restore(self) -> None:
        """
        Rebuilds every dock `ui_state[OPEN_TABS_KEY]` (S5) recorded, split
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
        raw_specs = ws.app_context.project_session.project.ui_state.get(OPEN_TABS_KEY) or []
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
            # by a failed read (drop_unreadable_fresh_open) -- so its overlays
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
                        overlays=[build_drop_descriptor(o) for o in restored_tab.overlays],
                        result_set_ids=spec.loaded_result_set_ids,
                    )
                docks.append(dock)

        if not docks:
            return

        steps = [job_step(dock.dock_id, lambda: None) for dock in docks]
        ws.job_manager.submit(
            f"Restoring workspace -- {len(docks)} tab(s)", steps, lane="batch",
            on_step=lambda _payload, index: ws.dispatch_compute(docks[index], is_fresh_open=True),
        )
