# =====================================================================
# FILE: gui/handlers/live_channel_drop.py
# =====================================================================
"""
The live-channel-drop half of a result-content dock (ARCHITECTURE_DECISIONS
§1.30). Split out of the Filter panel routing (gui.handlers.filter_routing)
in ADR §1.43 -- the two only ever shared a file, never a concern.

Dropping a channel onto a dock that already has multi-source h5 content has no
single dock-wide tacho to reuse (gui.file_explorer.actions.channel_drop routes
it here instead of the ordinary single-tacho order-overlay path), and a
result-content dock's Parameter Set may already fix which FFT/tracking settings
a newly-dropped channel should be computed with.

The whole read/lookup/compute runs through LiveOrderResults on a
background thread (ADR §1.54): its worker asks the result-set cache first and
rebuilds a hit from the stored amplitudes, or computes a miss -- no dialog, and
no HDF5 read on the GUI thread. A result already memoised from an earlier drop
is still added synchronously here, via the same
gui.handlers.result_content._append_curve_to_dock incremental path
result-set curves already use, so re-dropping a channel costs O(1).
"""
import dataclasses

from contextlib import nullcontext
from core.block_kinds import PARAM_ORDER
from core.dsp_configs import OrderTrackingConfig
from selection.channel_identity import build_channel_key
from selection.parameter_sets import build_parameter_sets, default_primary_index
from io_modules.measurement_files import file_stamp
from orchestration.channel_drop import plan_result_content_drop
from gui.handlers.dock_tab_title import update_dock_tab_title


def _order_tracking_config_from_params(params: dict) -> OrderTrackingConfig:
    # ParameterSet.params carries the full ResultSetRef.params, which includes
    # identity-only keys the dataclass does not know (algorithm_version, and
    # lineage on a branched graph). Passing them straight through raised
    # TypeError and the dropped channel silently never reached the dock.
    known = {f.name for f in dataclasses.fields(OrderTrackingConfig)}
    return OrderTrackingConfig(**{k: v for k, v in params.items() if k in known})


def _append_live_curves(dock, blocks, *, file_path, file_name, channel_index, channel_name, channel_type) -> None:
    """One live order cut per block onto `dock`. The meta carries the file and
    channel index so the curve is adopted/saved like any other (ADR §1.98, §1.102)."""
    from gui.handlers.result_content import _append_curve_to_dock

    meta = {"file_path": file_path, "file_name": file_name,
            "channel_index": channel_index, "channel_type": channel_type}
    with dock.curves.coalesce_changes():  # one draw for all the orders (#440)
        for block in blocks:
            order_value = float(block.provenance.params[PARAM_ORDER])
            _append_curve_to_dock(dock, {
                "x": block.primary_axis.values, "y": block.values,
                "label": f"[live] {file_name} · {channel_name} · Order {order_value:g}",
                "unit": block.value_unit, "meta": meta,
                "x_quantity": "rpm", "compute_spec": {PARAM_ORDER: order_value},
            })


class LiveChannelDropHandler:
    """
    Handles live channel drops onto result-content docks and syncs completed
    background computations into open docks (ARCHITECTURE_DECISIONS §1.30, §1.54).

    Dependencies:
        app_context: Application context (pool, settings, project_session, log).
        live_order_results: LiveOrderResults managing worker requests.
        workspace_tabs: QTabWidget or tabs collection holding open workspace docks.
    """

    def __init__(self, app_context, live_order_results, workspace_tabs=None):
        self.app_context = app_context
        self.live_order_results = live_order_results
        self.workspace_tabs = workspace_tabs

    def _resolve_drop_config(self, dock):
        """
        The settings a channel dropped onto `dock` should be computed with: the
        most-used Parameter Set's settings (`default_primary_index`) when this dock
        has more than one loaded result set's worth of distinct FFT/tracking
        settings, the settings of the single one when there is no ambiguity, or the
        Order Tracking ribbon's live settings when this dock has no result set loaded
        at all (ARCHITECTURE_DECISIONS §1.30 -- a Parameter Set is dock content now,
        not a project-wide Compare selection; §1.56 dropped the manual "primary"
        override, so the busiest set always wins).

        Returns (OrderTrackingConfig, a short label for what was used).
        """
        context = self.app_context
        session = getattr(context, "project_session", None)
        project = getattr(session, "project", None) if session else None

        # A set still being read counts too: after a Refresh or a reopened tab
        # the re-dropped channels arrive before their dock's sets land (#427).
        loaded_ids = dock.curves.loaded_or_pending_result_set_ids
        parameter_sets = build_parameter_sets(project, loaded_ids) if project else []

        if len(parameter_sets) > 1:
            chosen_index = default_primary_index(parameter_sets)
            chosen = next((ps for ps in parameter_sets if ps.index == chosen_index), parameter_sets[0])
            return _order_tracking_config_from_params(chosen.params), chosen.label

        if len(parameter_sets) == 1:
            chosen = parameter_sets[0]
            return _order_tracking_config_from_params(chosen.params), chosen.label

        return getattr(context, "order_tracking_settings", None), "the Order Tracking ribbon's live"

    def batch(self, label: str):
        """Channels requested inside this block share one job (#468)."""
        results = self.live_order_results
        return results.batch(label) if results is not None else nullcontext()

    def handle_dropped_channel(self, dock, desc: dict) -> bool:
        """
        Routes a channel dropped from the File Explorer onto a result-content dock
        (see gui.file_explorer.actions.channel_drop). Unlike an ordinary
        order-overlay drop, such a dock can hold channels from several different
        source files at once, so there is no single dock-wide tacho to reuse --
        this resolves its own file's tacho instead.

        The cache is checked on the worker (matching the FFT settings this dock's
        Parameter Set is currently using, see _resolve_drop_config); a miss is
        computed there silently -- like an order drop onto an ordinary graph, no
        dialog (ADR §1.54). A live result already memoised from an earlier drop is
        added to `dock` immediately; everything else is dispatched to
        LiveOrderResults and folded in later by _sync_manual_live_channels,
        once a live-compute burst settles (main_window.py). Returns whether the drop
        was accepted -- not proof a curve has landed on screen yet.
        """
        context = self.app_context

        file_path = desc["file_path"]
        key_id = build_channel_key(file_path, desc["channel_index"])

        drops = dock.live_drops
        if key_id in drops.claimed:
            return False  # already dropped onto this dock once -- nothing new to do

        config, _ = self._resolve_drop_config(dock)
        use_cache = getattr(context, "use_result_cache_lookup", True)
        pool_runs = getattr(getattr(context, "pool", None), "loaded_runs", []) or []
        decision = plan_result_content_drop(
            desc,
            {run.file_path: run for run in pool_runs},
            drops.claimed,
            config,
            file_stamp(file_path),
            use_cache=use_cache,
        )
        if not decision.accepted:
            if decision.message is not None and hasattr(context, "log"):
                context.log(decision.message)
            return False

        run = decision.run
        channel_name = decision.channel_name
        tacho_meta = decision.tacho_meta
        channel_meta = decision.channel_meta

        key = decision.memo_key
        live_results = self.live_order_results
        ready = live_results.result_for(key) if live_results is not None else None
        if ready is not None:
            drops.claim(key_id)
            _append_live_curves(
                dock, ready, file_path=file_path, file_name=run.file_name,
                channel_index=desc["channel_index"], channel_name=channel_name,
                channel_type=desc["channel_type"])
            return True

        drops.claim(key_id)
        drops.add_pending({
            "file_path": file_path, "file_name": run.file_name,
            "channel_index": desc["channel_index"],
            "channel_name": channel_name, "channel_type": desc["channel_type"],
            # The key the worker was asked under: settings may change before it
            # lands, so sync must not recompute the key from the current config.
            "memo_key": key,
        })
        if live_results is not None:
            live_results.request(key, run, tacho_meta, channel_meta, config)
        return True

    def _sync_manual_live_channels(self, dock) -> None:
        """
        Folds curves in for any of `dock.live_drops.pending` whose worker result
        has landed since it was requested -- called once a live-compute burst
        settles (main_window.py's timer). Both a cache hit (rebuilt on the worker)
        and a genuine compute arrive this way now; only a result already memoised
        from an earlier drop is folded in synchronously by
        handle_dropped_channel above and never reaches this list.
        """
        drops = dock.live_drops
        if not drops.pending:
            return

        live_results = self.live_order_results
        if live_results is None:
            return

        added_any = False
        with dock.curves.coalesce_changes():  # every landed channel in one draw (#440)
            for entry in drops.take_pending():
                key = entry["memo_key"]
                order_blocks = live_results.result_for(key)
                if order_blocks is None:
                    if live_results.is_pending(key):
                        drops.add_pending(entry)
                    else:
                        # Failed, cancelled or evicted: nothing will ever land, so
                        # release the channel to let the user drop it again.
                        drops.release(
                            build_channel_key(entry["file_path"], entry["channel_index"]))
                    continue

                added_any = True
                _append_live_curves(
                    dock, order_blocks, file_path=entry["file_path"], file_name=entry["file_name"],
                    channel_index=entry["channel_index"], channel_name=entry["channel_name"],
                    channel_type=entry["channel_type"])

        if added_any:
            # A cache hit's tab-title refresh runs synchronously from
            # execute_channel_drop_processing; a live compute lands well after
            # that call has returned, so it has to trigger its own.
            update_dock_tab_title(dock)

    def refresh_pending(self) -> None:
        """
        Called once main_window.py's live-compute settle timer expires -- folds
        curves into whichever open docks
        are still waiting on one. A dock closed since the drop simply has nothing
        left in its drops.pending to fold in.
        """
        tabs = self.workspace_tabs
        if tabs is None:
            return
        count = tabs.count() if hasattr(tabs, "count") else len(tabs)
        for index in range(count):
            dock = tabs.widget(index) if hasattr(tabs, "widget") else tabs[index]
            if dock.live_drops.pending:
                self._sync_manual_live_channels(dock)

