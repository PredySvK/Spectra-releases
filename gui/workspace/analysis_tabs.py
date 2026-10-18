"""
The four frequency/amplitude-domain analyses -- spectrum, spectrogram, order
tracking, overall level -- mixed into Workspace. Each open/refresh pair
shares the single `_dispatch_compute`: `Workspace.dispatch_compute` picks it
by `dock.analysis_kind`, `open_acc_*_tab` calls `build_shell` (workspace.py)
then `dispatch_compute(dock, origin=ComputeOrigin.FRESH_OPEN)`, and
`refresh_active_*` calls it with `ComputeOrigin.REFRESH` on the dock already
in front. `_dispatch_compute` starts one background task,
`live_compute.run_live_compute` -- cache lookup, read and DSP for the dock's
base channel -- and the result comes back through
`land_live_result`, a failure through `report_computation_failure`, both
tagged with `dock.dock_id` (`ideas/session_persistence/PLAN.md` S4). The
origin is only read on failure: what happens to the tab is
`live_compute.plan_compute_failure`'s one table.

Mixed into Workspace rather than built as a separate collaborator,
same reasoning as the Workspace owning the open tabs: this code
reaches directly into `self.tabs`, `self.app_context`, `self.tracking_scratch`
and the dock-open/task-dispatch helpers (`_connect_dock_signals`,
`_remove_dock_tab`, `open_tabs`, `_require_active_dock`,
`self.dock_tasks`) that
Workspace already owns.

This mixin owns no instance state of its own, so there is no `_init_analysis_tabs`
here. The one piece of per-refresh state involved, the graph's pending
restore, lives in the dock's `GraphCurves`, not on `self`: a Refresh starts
it here (`refresh_active_spectrum`, `refresh_active_order_tracking`,
`refresh_active_overall_level` -> `curves.begin_refresh`), and
`_restore_pending_overlays` in workspace.py takes it once
`land_live_result` there lands the base curve. `_restore_pending_overlays` stays on that side
because it is plot-callback machinery, not analysis-specific.

`open_specific_channel_tab` (the time-domain tab) is deliberately not part of
this mixin even though it dispatches into `open_acc_spectrum_tab` /
`open_acc_spectrogram_tab` / `open_acc_order_tracking_tab` /
`open_acc_overall_level_tab` by analysis mode: it has no refresh counterpart
and no DSP config DTO, so it does not share the open/refresh/DTO shape the other
four do, and it also acts as the routing entry point double-click handlers call
regardless of mode -- reason enough to leave it as dock-infrastructure-adjacent
in workspace.py rather than folding it into an "analysis tabs" module
built around a shape it doesn't have.

Rule: the DSP config DTOs (`SpectrumConfig`, `SpectrogramConfig`,
`OrderTrackingConfig`, `OverallLevelConfig`) travel whole in the
`LiveRequest`, never unpacked into loose arguments.

`refresh_last_n_curves` (S8, ideas/session_persistence/PLAN.md) is the one
addition that is not an open/refresh pair: "Refresh All" needed no new code
(a plain Refresh already recomputes every curve, see its own docstring), so
the ribbon's ``RefreshSplitButton`` only adds a second action for a narrower
recompute of the most recently added curves.
"""

import dataclasses
from typing import Dict

from core.block_kinds import KIND_ORDER_CUT
from core.channel_drop import TAB_CACHE_KEY
from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from io_modules.tab_cache import build_tab_cache_name, write_tab_cache_file
from orchestration import live_compute, tab_cache
from orchestration.dock_tasks import PURPOSE_COMPUTE, PURPOSE_TAB_CACHE
from orchestration.live_compute import ComputeOrigin, build_cache_hit_line, resolve_cache_finder
from selection.channel_identity import build_channel_key
from selection.tacho import tacho_missing
from session.data_pool import ResolvedTrace
from session.tab_cache import build_referenced_tab_cache_names
from view_models.analysis_kinds import (
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTROGRAM,
    ANALYSIS_SPECTRUM,
    resolve_analysis_kind,
    resolve_analysis_mode_of_kind,
)
from view_models.plot import resolve_curve_channel_key


@dataclasses.dataclass(frozen=True)
class _AnalysisKindSpec:
    """
    What the workspace shows about one Analysis kind's compute -- its refresh
    title and how a cache hit is logged. How it is read and computed is
    `live_compute.run_live_compute`'s; everything else about the kind
    (settings, display name, Block kind) is its `view_models.analysis_kinds`
    entry.
    """
    refresh_title: str
    log_has_fft: bool


_DISPATCH_SPECS: Dict[str, _AnalysisKindSpec] = {
    ANALYSIS_SPECTRUM: _AnalysisKindSpec(refresh_title="⏳ Recalculating 1D Spectrum...", log_has_fft=True),
    ANALYSIS_SPECTROGRAM: _AnalysisKindSpec(refresh_title="⏳ Recalculating...", log_has_fft=True),
    ANALYSIS_ORDERS: _AnalysisKindSpec(refresh_title="⏳ Reading channel...", log_has_fft=True),
    ANALYSIS_OVERALL_LEVEL: _AnalysisKindSpec(refresh_title="⏳ Reading channel...", log_has_fft=False),
}


class AnalysisTabsMixin:
    """Spectrum, spectrogram, order-tracking and overall-level tab open/refresh, mixed into Workspace."""

    # =========================================================================
    # 1D SPECTRUM ROUTING
    # =========================================================================
    def open_acc_spectrum_tab(self, run_index, channel_meta):
        dock = self.build_shell(ANALYSIS_SPECTRUM, ResolvedTrace(run_index, channel_meta))
        # A newly opened tab is a recipe the project does not have yet --
        # unlike a View change (a checked filter value), losing it silently
        # on close is exactly what the user opens a tab to avoid (session_persistence
        # follow-up, 2026-09-04: PLAN.md's S5 "no dirty tracking" call reversed here).
        self._mark_project_dirty()
        self.dispatch_compute(dock, origin=ComputeOrigin.FRESH_OPEN)

    def refresh_active_spectrum(self):
        dock = self._require_active_dock(ANALYSIS_SPECTRUM, "Refresh Spectrum")
        if dock is None:
            return

        # land_live_result (reached once the recompute lands) resets the
        # graph to just the base curve -- the overlays on screen at that moment
        # are captured and re-dropped (BUGS.md I1, #285, GraphCurves.begin_refresh).
        dock.curves.begin_refresh()
        self.dispatch_compute(dock, origin=ComputeOrigin.REFRESH)

    def refresh_last_n_curves(self, n: int) -> None:
        """
        Ribbon "Refresh Last N" (S8, ideas/session_persistence/PLAN.md): recomputes
        only the N most recently added curves on the active spectrum/order dock
        with the ribbon's current config, leaving every other curve exactly as
        it is. A plain Refresh already recomputes everything (see
        RefreshSplitButton's docstring); this exists for "I dropped one more
        comparison channel, only recompute that one" without disturbing curves
        already tuned by an earlier partial refresh.

        The base curve is always the *oldest* curve on a dock (it is drawn
        before anything can be dropped onto it), so "last N" only ever reaches
        it once N covers every curve on the dock -- at that point this is
        exactly a plain Refresh, and delegates there rather than duplicating
        it. Below that, only overlay curves are touched, which needs no new
        per-curve removal: the target overlays are dropped through `dock.
        curves.remove_overlays` (cheap -- no disk I/O, the surviving curves'
        arrays are already in memory, and GraphCurves redraws what remains),
        and the removed curves are re-added through `execute_channel_drop_
        processing`, the exact entry point a real drag uses, so they get a
        real recompute under the current ribbon config rather than a re-plot
        of stale data.
        """
        analysis_kind = getattr(self.tabs.currentWidget(), "analysis_kind", None)
        if analysis_kind not in (ANALYSIS_SPECTRUM, ANALYSIS_ORDERS, ANALYSIS_OVERALL_LEVEL):
            self.app_context.log(
                f"WARNING: Refresh Last {n} needs an active spectrum, order "
                f"tracking or Overall Level tab (current tab is '{analysis_kind or 'empty'}')."
            )
            return

        dock = self._require_active_dock(analysis_kind, f"Refresh Last {n}")
        if dock is None or dock.curves.model is None:
            return

        # An order-tracking dock's own extra order cuts (order 2, 3, ...) share
        # the base channel's (file_path, channel_index) but are not flagged
        # is_base -- overlay_drop_descriptors would otherwise mistake them
        # for a droppable "overlay" of the base channel itself.
        base_key = None
        if dock.run_index is not None and dock.channel_meta is not None:
            base_key = (str(dock.run_index.file_path), int(dock.channel_meta.index))

        overlays = [
            d for d in dock.curves.overlay_drop_descriptors()
            if (d["file_path"], d["channel_index"]) != base_key
        ]

        if n < 1 or n >= len(overlays) + 1:
            # N reaches back to the base curve -- same set a plain Refresh covers.
            if analysis_kind == ANALYSIS_SPECTRUM:
                self.refresh_active_spectrum()
            elif analysis_kind == ANALYSIS_ORDERS:
                self.refresh_active_order_tracking()
            else:
                self.refresh_active_overall_level()
            return

        targets = overlays[-n:]
        target_keys = {(t["file_path"], t["channel_index"]) for t in targets}

        def _is_target(trace):
            meta = trace.meta_ref or {}
            return (str(meta.get("file_path", "")), int(meta.get("channel_index", 0))) in target_keys

        dock.curves.remove_overlays(_is_target)

        self.route_channel_drop(dock, targets, mark_work_changed=False)

    # =========================================================================
    # 2D SPECTROGRAM / WATERFALL ROUTING
    # =========================================================================
    def open_acc_spectrogram_tab(self, run_index, channel_meta):
        dock = self.build_shell(ANALYSIS_SPECTROGRAM, ResolvedTrace(run_index, channel_meta))
        self._mark_project_dirty()  # see open_acc_spectrum_tab
        self.dispatch_compute(dock, origin=ComputeOrigin.FRESH_OPEN)

    def refresh_active_spectrogram(self):
        # "spectrogram" is exclusive to SpectrogramDock, but _require_active_dock's
        # return type spans both dock kinds -- narrow it before touching
        # vib_block/tacho_block, which GraphDock doesn't carry.
        dock = self._require_active_dock(ANALYSIS_SPECTROGRAM, "Refresh Spectrogram")
        if dock is None or not isinstance(dock, SpectrogramDock):
            return
        self.dispatch_compute(dock, origin=ComputeOrigin.REFRESH)

    # =========================================================================
    # ORDER TRACKING ROUTING
    # =========================================================================
    def open_acc_order_tracking_tab(self, run_index, channel_meta):
        # Gated before build_shell, not inside it: unlike a DeadLink (S3),
        # "this file simply has no tacho channel at all" is not something a
        # resolver call discovers -- and unlike spectrogram's RPM mode, order
        # tracking has no other mode to fall back to, so there is nothing
        # useful to show in an empty dock. Kept as today's log-and-return.
        if tacho_missing(run_index):
            self.app_context.log(f"ERROR: Order Tracking strictly requires a Tacho channel in '{run_index.file_name}'.")
            return

        dock = self.build_shell(ANALYSIS_ORDERS, ResolvedTrace(run_index, channel_meta))
        self._mark_project_dirty()  # see open_acc_spectrum_tab
        self.dispatch_compute(dock, origin=ComputeOrigin.FRESH_OPEN)

    def refresh_active_order_tracking(self):
        dock = self._require_active_dock(ANALYSIS_ORDERS, "Extract Order Cuts")
        if dock is None:
            return

        if tacho_missing(getattr(dock, "run_index", None), tacho_bound=dock.tacho_block is not None):
            self.app_context.log("ERROR: This order tab has no tacho channel bound to it.")
            return

        # See refresh_active_spectrum: land_live_result resets the dock to
        # just the base channel.
        dock.curves.begin_refresh()
        self.dispatch_compute(dock, origin=ComputeOrigin.REFRESH)

    # =========================================================================
    # OVERALL LEVEL ROUTING
    # =========================================================================
    def open_acc_overall_level_tab(self, run_index, channel_meta):
        # Only rpm tracking requires a tacho channel; in time mode, tacho is not
        # used.
        config = self.app_context.overall_level_settings
        if tacho_missing(run_index, tracking_mode=config.tracking_mode):
            self.app_context.log(
                f"ERROR: Overall Level tracked against RPM needs a Tacho channel in "
                f"'{run_index.file_name}'. Switch Tracking Mode to 'Free Run (Time)' to view this channel."
            )
            return

        dock = self.build_shell(ANALYSIS_OVERALL_LEVEL, ResolvedTrace(run_index, channel_meta))
        self._mark_project_dirty()  # see open_acc_spectrum_tab
        self.dispatch_compute(dock, origin=ComputeOrigin.FRESH_OPEN)

    def refresh_active_overall_level(self):
        dock = self._require_active_dock(ANALYSIS_OVERALL_LEVEL, "Refresh Overall Level")
        if dock is None:
            return

        config = self.app_context.overall_level_settings
        run_index = getattr(dock, "run_index", None)
        if tacho_missing(run_index, tacho_bound=dock.tacho_block is not None,
                         tracking_mode=config.tracking_mode):
            file_name = run_index.file_name if run_index else "unknown"
            self.app_context.log(
                f"ERROR: Overall Level tracked against RPM needs a Tacho channel in "
                f"'{file_name}'. Switch Tracking Mode to 'Free Run (Time)' to view this channel."
            )
            return

        dock.curves.begin_refresh()  # see refresh_active_spectrum
        self.dispatch_compute(dock, origin=ComputeOrigin.REFRESH)

    # =========================================================================
    # UNIFIED COMPUTE DISPATCH
    # =========================================================================
    def _dispatch_compute(self, dock, kind: str, *, origin: ComputeOrigin, vib_block=None) -> None:
        """
        Starts the one background task that brings `dock` its base curve for
        the four frequency/amplitude-domain kinds: cache lookup, read and DSP
        all run in `live_compute.run_live_compute` on the dock's `compute`
        slot, so a newer request -- or a closed dock -- drops it (ADR §1.84,
        §1.167). What comes back lands through `land_live_result`, a failure
        through `report_computation_failure`, which `origin` tells what to do
        with the tab.
        """
        entry = _DISPATCH_SPECS.get(kind)
        if entry is None:
            self.app_context.log(f"ERROR: _dispatch_compute: unknown analysis kind '{kind}'.")
            return

        analysis_kind = resolve_analysis_kind(kind)
        config = getattr(self.app_context, resolve_analysis_mode_of_kind(kind).settings_name)
        tab_cache_path, compute_notices = None, ()
        if origin is ComputeOrigin.RESTORE:
            config, restore_line = self._restore_config(dock, kind)
            compute_notices = (restore_line,)
            tab_cache_path = tab_cache.resolve_tab_cache_read_path(
                self._project_path(), self.open_tabs.tab_cache_file(dock))

        if hasattr(dock, "plot_widget"):
            dock.plot_widget.setTitle(entry.refresh_title if origin is ComputeOrigin.REFRESH else "⏳ Loading...")
        self.open_tabs.start_compute(dock, origin=origin)

        finder = resolve_cache_finder(getattr(self.app_context, "project_session", None),
                                      getattr(self.app_context, "use_result_cache_lookup", True))
        request = live_compute.LiveRequest(
            run_index=dock.run_index,
            channel_meta=dock.channel_meta,
            block_kind=analysis_kind.block_kind,
            config=config,
            # A refresh reuses the tacho the dock already holds; an open reads the file's.
            tacho_block=getattr(dock, "tacho_block", None) if origin is ComputeOrigin.REFRESH else None,
            with_overall_level=(analysis_kind.block_kind == KIND_ORDER_CUT
                                and bool(getattr(self.app_context, "order_tracking_overall_level", False))),
            vib_block=vib_block,
            tab_cache_path=tab_cache_path,
            compute_notices=compute_notices,
        )
        self.dock_tasks.run(
            dock.dock_id, live_compute.run_live_compute, request, finder, self.tracking_scratch,
            purpose=PURPOSE_COMPUTE,
            on_success=lambda result: self._land_computed_result(dock.dock_id, result, origin),
            on_error=lambda message: self.report_computation_failure(
                dock.dock_id, message, phase=live_compute.PHASE_READ),
        )

    def resolve_restore_config(self, kind: str, recipe) -> "live_compute.RestoreConfig":
        """
        The config a restored curve on a `kind` tab computes with: `recipe`
        laid over the ribbon's config of that kind. The base
        curve and every restored dropped channel resolve it here.
        """
        ribbon_config = getattr(self.app_context, resolve_analysis_mode_of_kind(kind).settings_name)
        return live_compute.resolve_restore_config(recipe, ribbon_config)

    def _restore_config(self, dock, kind: str):
        """
        A restored tab computes with its base curve's saved recipe, the
        ribbon filling in only what the recipe does not carry -- and one log
        line says which values those were; it is logged
        only if the curve is computed, not read from the Tab cache. A Refresh
        or a fresh open never comes here: they compute with the ribbon.
        Returns `(config, line)`.
        """
        spec = self.open_tabs.restored_spec(dock)
        base = next((t for t in spec.traces if t.is_base), None) if spec is not None else None
        resolved = self.resolve_restore_config(kind, base.compute_spec if base is not None else None)
        line = live_compute.build_restore_config_line(live_compute.build_curve_subject(
            resolve_analysis_kind(kind).display_name, getattr(dock.channel_meta, "name", "")), resolved)
        return resolved.config, line

    # =========================================================================
    # TAB CACHE
    # =========================================================================
    def _land_computed_result(self, dock_id: str, result, origin: ComputeOrigin) -> None:
        """
        A computed tab's base curve lands like every other one; then, when it
        came from a measurement, it is kept in the Tab cache. Which tabs go
        there is decided by this being the path of a computed tab -- a time
        tab or an Imported result is only read and never reaches it.
        """
        if not self.land_live_result(dock_id, result):
            return
        dock = self.find_dock_by_id(dock_id)
        if dock is not None and not result.from_tab_cache:
            self._write_tab_cache(dock, result, origin)

    def _write_tab_cache(self, dock, result, origin: ComputeOrigin) -> None:
        """
        Keeps the base curve in the Tab cache. The name is the dock's at once,
        so a Save made while the write is still running already points at it.
        """
        channel_name = getattr(dock.channel_meta, "name", "") or ""

        def forget(name: str) -> None:
            if self.open_tabs.tab_cache_file(dock) == name:
                self.open_tabs.set_tab_cache_file(dock, None)

        name = self.write_tab_cache_file(
            dock, key="base", channel_name=channel_name, blocks=result.blocks,
            recipe=_base_recipe(dock),
            saved_name=self.open_tabs.tab_cache_file(dock) if origin is ComputeOrigin.RESTORE else None,
            on_failed=forget)
        self.open_tabs.set_tab_cache_file(dock, name)

    def keep_dropped_channel(self, dock, descriptor, result) -> None:
        """
        A channel dropped on `dock` and computed from its measurement -- a
        result-set hit too, so the tab outlives that set -- goes into the Tab
        cache like the base curve; a restored one shown from its file keeps
        that file's name. The drop lanes that compute call this
        once the curve is drawn; a curve from a loaded result set never comes
        here and keeps being read from its set.
        """
        open_tabs = self.open_tabs
        channel_key = build_channel_key(descriptor["file_path"], descriptor["channel_index"])
        saved_name = descriptor.get(TAB_CACHE_KEY)
        if result.from_tab_cache:
            open_tabs.set_overlay_tab_cache_file(dock, channel_key, saved_name)
            return

        def forget(name: str) -> None:
            if open_tabs.overlay_tab_cache_file(dock, channel_key) == name:
                open_tabs.set_overlay_tab_cache_file(dock, channel_key, None)

        name = self.write_tab_cache_file(
            dock, key=("dropped", channel_key),
            channel_name=descriptor.get("channel_name", ""), blocks=result.blocks,
            recipe=_overlay_recipe(dock, channel_key),
            saved_name=saved_name, on_failed=forget)
        open_tabs.set_overlay_tab_cache_file(dock, channel_key, name)

    def write_tab_cache_file(self, dock, *, key, channel_name: str, blocks, recipe,
                             saved_name=None, on_failed=None) -> str:
        """
        The one way any curve of a computed tab goes into the Tab cache (base,
        spectrogram, dropped channel); returns the name its `TraceSpec` saves.

        With a project folder the file is written on a dock task now. An
        Untitled project has none: the result is held in memory under `key`
        ("this curve of this tab" -- a newer result under the same key
        replaces it) and written after the first Save
        (`write_held_tab_cache_files`). `on_failed(name)` runs when the write
        fails, so the owner stops naming a file that is not there.
        """
        write = tab_cache.plan_tab_cache_write(
            self._project_path(), dock.dock_id, channel_name, saved_name=saved_name)
        if write is None:
            # The shape a written file's name has, so the first Save already names it.
            name = build_tab_cache_name(dock.dock_id, channel_name)
            self.held_tab_cache_writes.hold(key, tab_cache.HeldTabCacheWrite(
                dock_id=dock.dock_id, name=name, channel_name=channel_name,
                blocks=tuple(blocks), recipe=recipe, on_failed=on_failed))
            return name
        self._start_tab_cache_write(dock.dock_id, write, channel_name, blocks, recipe, on_failed)
        return write.name

    def write_held_tab_cache_files(self) -> None:
        """
        After a Save: what the project held while it was Untitled goes to
        disk now, on dock tasks -- only the curves the saved project names.
        """
        session = getattr(self.app_context, "project_session", None)
        project_path = self._project_path()
        if not project_path or not len(self.held_tab_cache_writes):
            return
        names = build_referenced_tab_cache_names(session.project.open_tabs)
        for held in self.held_tab_cache_writes.take(names):
            if self.find_dock_by_id(held.dock_id) is None:
                continue
            write = tab_cache.plan_tab_cache_write(
                project_path, held.dock_id, held.channel_name, saved_name=held.name)
            if write is not None:
                self._start_tab_cache_write(held.dock_id, write, held.channel_name,
                                            held.blocks, held.recipe, held.on_failed)

    def _start_tab_cache_write(self, dock_id: str, write, channel_name: str, blocks, recipe,
                               on_failed) -> None:
        self.dock_tasks.run(
            dock_id, write_tab_cache_file, write.path, tuple(blocks), recipe,
            purpose=PURPOSE_TAB_CACHE,
            on_error=lambda message: self._tab_cache_write_failed(
                channel_name, write.name, message, on_failed),
        )

    def _tab_cache_write_failed(self, channel_name: str, name: str, message: str, on_failed) -> None:
        """
        The curve stops naming the file that was not written; when a Save
        already named it, the saved project is now behind and is marked so --
        the next Save drops the name instead of keeping a missing file.
        """
        if on_failed is not None:
            on_failed(name)
        session = getattr(self.app_context, "project_session", None)
        if session is not None and name in build_referenced_tab_cache_names(session.project.open_tabs):
            session.mark_view_changed()
        self.app_context.log(
            f"WARNING: tab cache for {channel_name} not written "
            f"({message}); the tab will be computed again when the project is reopened.")

    def _project_path(self):
        """The project file's path; None while the project is Untitled."""
        return getattr(getattr(self.app_context, "project_session", None), "path", None)

    def log_tab_cache_hit(self, dock, channel_name: str) -> None:
        """The "loaded from tab cache" line of a channel of `dock` shown from its file."""
        analysis_kind = resolve_analysis_kind(dock.analysis_kind)
        self.app_context.log(tab_cache.build_tab_cache_hit_line(
            live_compute.build_curve_subject(analysis_kind.display_name, channel_name)))

    def _log_cache_hit(self, dock, result) -> None:
        analysis_kind = resolve_analysis_kind(dock.analysis_kind)
        entry = _DISPATCH_SPECS.get(dock.analysis_kind)
        what = "FFT settings" if entry is None or entry.log_has_fft else "settings"
        channel_name = getattr(dock.channel_meta, "name", "")
        self.app_context.log(build_cache_hit_line(
            live_compute.build_curve_subject(analysis_kind.display_name, channel_name),
            result.result_set_label, what=what))


def _base_recipe(dock):
    """The recipe `dock`'s base result was computed with: a spectrogram keeps
    it on its model, a graph on its base curve. None while it has none."""
    if isinstance(dock, SpectrogramDock):
        model = dock.spectrogram.model
        return model.compute_spec if model is not None else None
    base = dock.curves.base_trace
    return base.compute_spec if base is not None else None


def _overlay_recipe(dock, channel_key):
    """The recipe of the curve dropped on `dock` from the channel
    `channel_key` names -- what its Tab cache file keeps next to the blocks."""
    model = dock.curves.model
    for trace in (model.traces if model is not None else []):
        if not trace.is_base and resolve_curve_channel_key(trace) == channel_key:
            return trace.compute_spec
    return None
