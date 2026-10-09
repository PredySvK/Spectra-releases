"""
The four frequency/amplitude-domain analyses -- spectrum, spectrogram, order
tracking, overall level -- mixed into Workspace. Each open/refresh pair
shares the single `_dispatch_compute` implementation via `_DISPATCH_SPECS`:
`Workspace.dispatch_compute` picks it by `dock.analysis_kind`,
`open_acc_*_tab` calls `build_shell` (workspace.py) then
`dispatch_compute(dock, is_fresh_open=True)`, and `refresh_active_*` calls
`dispatch_compute(dock, is_fresh_open=False)` on the dock already in front --
the only thing `is_fresh_open` changes is what happens on failure (drop the empty
tab vs. leave the existing plot in place, see `_abort_refresh`). Order tracking
adds a further shared `_execute_order_tracking_request` its own two branches fund
into. `_dispatch_compute` checks the background result cache, falls back to
reading channels through `dock_tasks`, hands the DSP config DTO whole to
`self.spectral_requests`, and waits for the result to come back through
the matching `plot_*` callback tagged with `dock.dock_id`
(`ideas/session_persistence/PLAN.md` S4).

Mixed into Workspace rather than built as a separate collaborator,
same reasoning as the Workspace owning the open tabs: this code
reaches directly into `self.tabs`, `self.app_context`, `self.spectral_requests`
and the dock-open/task-dispatch helpers (`_connect_dock_signals`,
`_remove_dock_tab`, `open_tabs`, `_require_active_dock`,
`self.dock_tasks`) that
Workspace already owns.

This mixin owns no instance state of its own, so there is no `_init_analysis_tabs`
here. The one piece of per-refresh state involved, the graph's pending
restore, lives in the dock's `GraphCurves`, not on `self`: a Refresh starts
it here (`refresh_active_spectrum`, `refresh_active_order_tracking`,
`refresh_active_overall_level` -> `curves.begin_refresh`), and
`_restore_pending_overlays` in workspace.py takes it once the
`plot_frequency_block`/`plot_order_cuts`/`plot_overall_level_block` callbacks
there land the base curve. `_restore_pending_overlays` stays on that side
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
`OrderTrackingConfig`, `OverallLevelConfig`) are passed whole to the controller,
never unpacked into loose arguments (test_dsp_config_forwarding.py guards this).

`refresh_last_n_curves` (S8, ideas/session_persistence/PLAN.md) is the one
addition that is not an open/refresh pair: "Refresh All" needed no new code
(a plain Refresh already recomputes every curve, see its own docstring), so
the ribbon's ``RefreshSplitButton`` only adds a second action for a narrower
recompute of the most recently added curves.
"""

import dataclasses
from typing import Callable, Dict, Optional

import numpy as np

from core.block_kinds import KIND_ORDER_CUT, PARAM_ORDER
from core.data_block import NVHDataBlock, SourceRef
from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from orchestration import live_compute
from orchestration.dock_tasks import PURPOSE_COMPUTE
from orchestration.live_compute import read_spectrogram_channels
from io_modules.data_accessor import DataAccessor
from selection.tacho import tacho_missing
from session.data_pool import ResolvedTrace
from view_models.analysis_kinds import (
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTROGRAM,
    ANALYSIS_SPECTRUM,
    resolve_analysis_kind,
    resolve_analysis_mode_of_kind,
)
from signal_processing.result_blocks import (
    resolve_sampling_frequency,
    build_order_cut_blocks,
    computation_params,
)


def _build_read_spectrum(mixin: "AnalysisTabsMixin", dock, config, *, is_fresh_open: bool):
    def _on_loaded(data_block):
        try:
            # Called for its exception, not its value: an unresolvable sampling
            # rate has to be reported here, where the dock can be closed and the
            # user told, rather than surfacing as a worker error later.
            resolve_sampling_frequency(data_block)
        except Exception as e:
            if is_fresh_open:
                mixin.app_context.log(str(e))
                mixin._remove_dock_tab(dock)
            else:
                mixin._abort_refresh(dock, str(e))
            return

        mixin.spectral_requests.request_1d_spectrum(
            time_block=data_block, config=config, widget_tag=dock.dock_id
        )

    return DataAccessor.fetch_channel_data, (dock.run_index, dock.channel_meta), _on_loaded


def _build_read_spectrogram(mixin: "AnalysisTabsMixin", dock, config, *, is_fresh_open: bool):
    def _on_loaded(payload):
        vib_block, tacho_block, tacho_meta_used = payload
        dock.vib_block = vib_block

        if tacho_block is not None:
            dock.tacho_block = tacho_block
            if tacho_meta_used is not None:
                mixin.app_context.log(f"SYSTEM: Auto-linked Tacho [{tacho_meta_used.name}] for RPM Tracking.")

        final_tacho = dock.tacho_block
        if config.tracking_mode == "rpm" and final_tacho is None:
            # The old message claimed "Switching to Time mode" but nothing
            # switched -- tracking_mode is untouched and the next Refresh
            # does the same thing. Tell the truth and get the dock out of
            # its "⏳ Loading..." limbo (audit 02, finding S3/3.4).
            mixin.app_context.log(
                "ERROR: RPM Tracking is on but this file has no tacho channel. "
                "Set the ribbon to Time mode to view this channel."
            )
            if is_fresh_open:
                mixin._remove_dock_tab(dock)
            else:
                dock.plot_widget.setTitle("Spectrogram unavailable - no tacho channel")
            return

        dock.plot_widget.setTitle("⏳ Computing Tracked Waterfall...")

        mixin.spectral_requests.request_tracked_waterfall(
            vib_block=dock.vib_block,
            tacho_block=final_tacho,
            config=config,
            widget_tag=dock.dock_id,
        )

    need_tacho = config.tracking_mode == "rpm" and dock.tacho_block is None
    tacho_candidates = list(dock.run_index.available_channels.items()) if need_tacho else []
    return read_spectrogram_channels, (dock.run_index, dock.channel_meta, tacho_candidates), _on_loaded


def _build_read_orders(mixin: "AnalysisTabsMixin", dock, config, *, is_fresh_open: bool):
    def _on_loaded(payload):
        vib_block, tacho_block = payload
        dock.tacho_block = tacho_block
        mixin._execute_order_tracking_request(dock, config, vib_block, tacho_block)

    # A fresh open always loads the file's tacho; a refresh reuses the dock's.
    tacho_block = None if is_fresh_open else getattr(dock, "tacho_block", None)
    return (live_compute.read_order_channels,
            (dock.run_index, dock.channel_meta, tacho_block), _on_loaded)


def _build_read_overall_level(mixin: "AnalysisTabsMixin", dock, config, *, is_fresh_open: bool):
    def _on_loaded(payload):
        vib_block, tacho_block = payload
        dock.tacho_block = tacho_block
        # Read by report_computation_failure to tell an open-time failure
        # (drop the empty tab) from a refresh failure (leave the existing
        # plot alone) -- cleared there and in plot_overall_level_block.
        mixin.open_tabs.start_compute(dock, is_fresh_open=is_fresh_open)
        dock.plot_widget.setTitle("⏳ Computing Overall Level...")

        mixin.spectral_requests.request_overall_level(
            vib_block=vib_block, tacho_block=tacho_block, config=config,
            widget_tag=dock.dock_id,
        )

    tacho_block = None if is_fresh_open else getattr(dock, "tacho_block", None)
    return (live_compute.read_overall_level_channels,
            (dock.run_index, dock.channel_meta, tacho_block, config.tracking_mode == "rpm"),
            _on_loaded)


def _orders_precheck(mixin: "AnalysisTabsMixin", dock, config) -> bool:
    if not config.orders_to_extract:
        mixin._abort_refresh(dock, "ERROR: No Target Orders specified.")
        return False
    return True


def _orders_plot_cache_hit(mixin: "AnalysisTabsMixin", dock, cached, raw_channel_name: str, config) -> None:
    # The same identity a fresh read stamps (DataAccessor._build_source_ref).
    # Left at SourceRef's unset -1, the order-2.. curves no longer match the
    # base channel's (file_path, channel_index), so a later Refresh re-drops
    # them as an "overlay" -- and a -1 read is the file's last column (#379).
    source = SourceRef(
        file_path=getattr(dock.run_index, "file_path", "") if dock.run_index else "",
        file_name=getattr(dock.run_index, "file_name", "") if dock.run_index else "",
        channel_index=getattr(dock.channel_meta, "index", -1) if dock.channel_meta else -1,
        channel_name=raw_channel_name,
        excel_metadata=(getattr(dock.run_index, "metadata", None) or {}) if dock.run_index else {},
    )
    source_block = NVHDataBlock.time_response(
        name=raw_channel_name,
        values=np.empty(0),
        times=np.empty(0),
        value_unit=getattr(cached.blocks[0], "value_unit", "") or getattr(dock.channel_meta, "unit", "") or "",
        channel_type=getattr(dock.channel_meta, "type", "accelerometer") if dock.channel_meta else "accelerometer",
        source=source,
    )
    blocks = build_order_cut_blocks(
        source_block, cached.blocks[0].axes[0].values,
        {order: block.values
         for order, block in zip(config.orders_to_extract, cached.blocks)},
        window_type=config.window_type, fft_size=config.fft_size,
        value_unit=cached.blocks[0].value_unit, computation=computation_params(config),
    )
    if getattr(cached, "result_set_label", None):
        blocks = [
            dataclasses.replace(b, metadata={**b.metadata, "result_set_label": cached.result_set_label})
            for b in blocks
        ]
    mixin.plot_order_cuts(dock.dock_id, blocks)


@dataclasses.dataclass(frozen=True)
class _AnalysisKindSpec:
    """
    How one Analysis kind is read, computed and plotted -- the part of it that
    reaches into the workspace. Everything else about the kind (settings,
    display name, Block kind) is its `view_models.analysis_kinds` entry.
    """
    refresh_title: str
    log_has_fft: bool
    finder_attr: str = "find_cached_block_background"
    precheck: Optional[Callable] = None
    build_read: Optional[Callable] = None
    plot_cache_hit: Optional[Callable] = None
    is_cache_hit: Callable = lambda cached: cached is not None


_SPECTRUM_SPEC = _AnalysisKindSpec(
    refresh_title="⏳ Recalculating 1D Spectrum...",
    log_has_fft=True,
    finder_attr="find_cached_block_background",
    build_read=_build_read_spectrum,
    plot_cache_hit=lambda mixin, dock, cached, raw_name, config: mixin.plot_frequency_block(dock.dock_id, cached),
)

_SPECTROGRAM_SPEC = _AnalysisKindSpec(
    refresh_title="⏳ Recalculating...",
    log_has_fft=True,
    finder_attr="find_cached_block_background",
    build_read=_build_read_spectrogram,
    plot_cache_hit=lambda mixin, dock, cached, raw_name, config: mixin.plot_spectrogram_block(dock.dock_id, cached),
)

_ORDERS_SPEC = _AnalysisKindSpec(
    refresh_title="⏳ Reading channel...",
    log_has_fft=True,
    finder_attr="find_cached_result_background",
    precheck=_orders_precheck,
    is_cache_hit=lambda cached: cached is not None and bool(getattr(cached, "blocks", None)),
    build_read=_build_read_orders,
    plot_cache_hit=_orders_plot_cache_hit,
)

_OVERALL_LEVEL_SPEC = _AnalysisKindSpec(
    refresh_title="⏳ Reading channel...",
    log_has_fft=False,
    finder_attr="find_cached_block_background",
    build_read=_build_read_overall_level,
    plot_cache_hit=lambda mixin, dock, cached, raw_name, config: mixin.plot_overall_level_block(dock.dock_id, cached),
)

_DISPATCH_SPECS: Dict[str, _AnalysisKindSpec] = {
    ANALYSIS_SPECTRUM: _SPECTRUM_SPEC,
    ANALYSIS_SPECTROGRAM: _SPECTROGRAM_SPEC,
    ANALYSIS_ORDERS: _ORDERS_SPEC,
    ANALYSIS_OVERALL_LEVEL: _OVERALL_LEVEL_SPEC,
}


class AnalysisTabsMixin:
    """Spectrum, spectrogram, order-tracking and overall-level tab open/refresh, mixed into Workspace."""

    def _abort_refresh(self, dock, message):
        """
        A refresh/open path that returns before it dispatches still has to undo
        what it did up front: the "⏳ ..." title and, on a refresh, the pending
        restore in its `GraphCurves`. Left in place, the title implies work is
        still in progress, and the stale restore is silently taken (and its
        curves re-dropped) by the next unrelated plot on this dock (audit 02,
        finding S3/3.9). Safe when nothing is pending (the open paths).
        """
        self.app_context.log(message)
        if isinstance(dock, GraphDock):
            dock.curves.abort_restore()
        if hasattr(dock, "plot_widget"):
            dock.plot_widget.setTitle("Computation aborted - see System Log")

    # =========================================================================
    # 1D SPECTRUM ROUTING
    # =========================================================================
    def open_acc_spectrum_tab(self, run_index, channel_meta):
        dock = self.build_shell(ANALYSIS_SPECTRUM, ResolvedTrace(run_index, channel_meta))
        # A newly opened tab is a recipe the project does not have yet --
        # unlike ui_state elsewhere (FilterPanel selection), losing it silently
        # on close is exactly what the user opens a tab to avoid (session_persistence
        # follow-up, 2026-09-04: PLAN.md's S5 "no dirty tracking" call reversed here).
        self._mark_project_dirty()
        self.dispatch_compute(dock, is_fresh_open=True)

    def refresh_active_spectrum(self):
        dock = self._require_active_dock(ANALYSIS_SPECTRUM, "Refresh Spectrum")
        if dock is None:
            return

        # plot_frequency_block (reached once the recompute lands) resets the
        # graph to just the base curve -- the overlays on screen at that moment
        # are captured and re-dropped (BUGS.md I1, #285, GraphCurves.begin_refresh).
        dock.curves.begin_refresh()
        self.dispatch_compute(dock, is_fresh_open=False)

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

        self.route_channel_drop(dock, targets, mark_dirty=False)

    # =========================================================================
    # 2D SPECTROGRAM / WATERFALL ROUTING
    # =========================================================================
    def open_acc_spectrogram_tab(self, run_index, channel_meta):
        dock = self.build_shell(ANALYSIS_SPECTROGRAM, ResolvedTrace(run_index, channel_meta))
        self._mark_project_dirty()  # see open_acc_spectrum_tab
        self.dispatch_compute(dock, is_fresh_open=True)

    def refresh_active_spectrogram(self):
        # "spectrogram" is exclusive to SpectrogramDock, but _require_active_dock's
        # return type spans both dock kinds -- narrow it before touching
        # vib_block/tacho_block, which GraphDock doesn't carry.
        dock = self._require_active_dock(ANALYSIS_SPECTROGRAM, "Refresh Spectrogram")
        if dock is None or not isinstance(dock, SpectrogramDock):
            return
        self.dispatch_compute(dock, is_fresh_open=False)

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
        self.dispatch_compute(dock, is_fresh_open=True)

    def refresh_active_order_tracking(self):
        dock = self._require_active_dock(ANALYSIS_ORDERS, "Extract Order Cuts")
        if dock is None:
            return

        if tacho_missing(getattr(dock, "run_index", None), tacho_bound=dock.tacho_block is not None):
            self.app_context.log("ERROR: This order tab has no tacho channel bound to it.")
            return

        # See refresh_active_spectrum: _execute_order_tracking_request's
        # plot_order_cuts call resets the dock to just the base channel.
        dock.curves.begin_refresh()
        self.dispatch_compute(dock, is_fresh_open=False)

    # =========================================================================
    # OVERALL LEVEL ROUTING
    # =========================================================================
    def open_acc_overall_level_tab(self, run_index, channel_meta):
        # Only rpm tracking requires a tacho channel; in time mode, tacho is not
        # used (ADR §1.62 point 7 and 19, issue #124).
        config = self.app_context.overall_level_settings
        if tacho_missing(run_index, tracking_mode=config.tracking_mode):
            self.app_context.log(
                f"ERROR: Overall Level tracked against RPM needs a Tacho channel in "
                f"'{run_index.file_name}'. Switch Tracking Mode to 'Free Run (Time)' to view this channel."
            )
            return

        dock = self.build_shell(ANALYSIS_OVERALL_LEVEL, ResolvedTrace(run_index, channel_meta))
        self._mark_project_dirty()  # see open_acc_spectrum_tab
        self.dispatch_compute(dock, is_fresh_open=True)

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
        self.dispatch_compute(dock, is_fresh_open=False)

    # =========================================================================
    # UNIFIED COMPUTE DISPATCH
    # =========================================================================
    def _dispatch_compute(self, dock, kind: str, *, is_fresh_open: bool) -> None:
        """
        Shared background read + cache lookup + DSP compute dispatcher for the
        four frequency/amplitude-domain kinds (spectrum, spectrogram, orders,
        overall_level).

        Owns the cache-guard (`use_cache` check, `finder is None` check,
        `file_path`/`channel_meta` check, fall back to live compute), background
        worker task management via `dock_tasks`, and uniform error handling
        (including restoring the dock title via `_abort_refresh` on refresh failures).
        """
        entry = _DISPATCH_SPECS.get(kind)
        if entry is None:
            self.app_context.log(f"ERROR: _dispatch_compute: unknown analysis kind '{kind}'.")
            return

        analysis_kind = resolve_analysis_kind(kind)
        config = getattr(self.app_context, resolve_analysis_mode_of_kind(kind).settings_name)
        if entry.precheck is not None and not entry.precheck(self, dock, config):
            return

        if hasattr(dock, "plot_widget"):
            dock.plot_widget.setTitle("⏳ Loading..." if is_fresh_open else entry.refresh_title)

        def _on_failed(message):
            if is_fresh_open:
                self.app_context.log(f"ERROR: IO block read exception: {message}")
                self.open_tabs.drop_unreadable_fresh_open(dock)
            else:
                self._abort_refresh(dock, f"ERROR: IO block read exception: {message}")

        read, read_args, on_loaded = entry.build_read(self, dock, config, is_fresh_open=is_fresh_open)

        use_cache = getattr(self.app_context, "use_result_cache_lookup", True)
        project_session = getattr(self.app_context, "project_session", None)
        finder = getattr(project_session, entry.finder_attr, None)
        file_path = getattr(getattr(dock, "run_index", None), "file_path", None)
        channel_meta = getattr(dock, "channel_meta", None)

        # The Overall Level curve comes from the same computation as the orders, never
        # beside cached ones (ADR §1.141 point 10).
        with_overall_level = (analysis_kind.block_kind == KIND_ORDER_CUT
                              and self.app_context.order_tracking_overall_level)
        if (not use_cache or with_overall_level or finder is None or not file_path
                or channel_meta is None):
            self.dock_tasks.run(
                dock.dock_id, read, *read_args,
                purpose=PURPOSE_COMPUTE, on_success=on_loaded, on_error=_on_failed,
            )
            return

        raw_channel_name = channel_meta.name
        config_dict = dataclasses.asdict(config)

        def _on_lookup_or_read(result):
            is_hit, value = result
            if is_hit:
                cached = value
                # This path plots directly, without going through request_*(), so it
                # must supersede any recompute still running for the previous FFT
                # settings itself (audit 02, finding S3/3.2).
                self.spectral_requests.invalidate(dock.dock_id)
                label = getattr(cached, "result_set_label", None) or (
                    cached.metadata.get("result_set_label", "") if hasattr(cached, "metadata") else ""
                )
                fft_suffix = " -- FFT settings unchanged, no recompute needed." if entry.log_has_fft else " -- settings unchanged, no recompute needed."
                self.app_context.log(
                    f"PROJECT: {analysis_kind.display_name} for {raw_channel_name} loaded from result set '{label}'"
                    f"{fft_suffix}"
                )
                entry.plot_cache_hit(self, dock, cached, raw_channel_name, config)
            else:
                on_loaded(value)

        lookup_args = (file_path, raw_channel_name, config_dict)
        if analysis_kind.block_kind == KIND_ORDER_CUT:
            wanted_block_params = [
                {PARAM_ORDER: float(order)} for order in config.orders_to_extract
            ]
            lookup_args = (file_path, raw_channel_name, config_dict, wanted_block_params)

        # A miss reads on the same worker task, right after the lookup -- not
        # from a GUI callback queued behind the new tab's first paint (#504).
        self.dock_tasks.run(
            dock.dock_id, live_compute.lookup_or_read_for_dock,
            (finder, analysis_kind.block_kind, *lookup_args), entry.is_cache_hit, read, read_args,
            channel_index=getattr(channel_meta, "index", None),
            purpose=PURPOSE_COMPUTE, on_success=_on_lookup_or_read, on_error=_on_failed,
        )

    def _execute_order_tracking_request(self, graph_sheet, config,
                                        vib_block, tacho_block):
        """
        The one call site for `request_order_extraction`: both the fresh-open
        and the refresh read land here once the channels are in memory, so N
        configured orders are always one DSP call producing N curves.

        A cache hit does not come through here -- `_orders_plot_cache_hit`
        rebuilds those curves from the stored amplitudes instead.
        """
        graph_sheet.plot_widget.setTitle("⏳ Extracting Orders... Please wait.")

        self.spectral_requests.request_order_extraction(
            vib_block=vib_block, tacho_block=tacho_block, config=config,
            widget_tag=graph_sheet.dock_id,
            with_overall_level=self.app_context.order_tracking_overall_level,
        )
