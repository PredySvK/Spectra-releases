# =====================================================================
# FILE: gui/file_explorer/actions/channel_drop.py
# =====================================================================
"""
Stateless Service Action handling the routing of dropped channels onto workspace docks.
Strictly decoupled from direct Data I/O. Uses DTO configurations to decouple from UI.
Coordinates between the Presentation layer (Docks) and the Pipeline layer (DataAccessor, DSP Core).
All internal documentation strings and variable labels are standardly written in English.
"""

import dataclasses
from contextlib import nullcontext
import numpy as np

from core.block_kinds import PARAM_ORDER
from core.dsp_configs import SpectrumConfig
from core.channel_drop import build_drop_descriptor
from core.units import strip_channel_name_prefix
from session.data_pool import DeadLink, find_dropped_channel
from view_models.plot import overall_level_band_differs_from_dock
from view_models.analysis_kinds import (
    ANALYSIS_SPECTROGRAM, ANALYSIS_TIME, resolve_analysis_kind,
)
from orchestration import live_compute
from orchestration.live_compute import ComputeOrigin, build_cache_hit_line, resolve_cache_finder
from orchestration.dock_tasks import PURPOSE_DROP
from orchestration.channel_drop import (
    DropFacts,
    OrderDropInputs,
    OverallLevelDropInputs,
    decide_spectrogram_drop,
    drop_keys,
    read_plotted_keys,
    run_channel_drop,
)
from gui.handlers.dock_tab_title import set_dock_tab_title, update_dock_tab_title


def execute_channel_drop_processing(
    dock_instance, raw_descriptors: list, app_context, *,
    workspace, live_drop_handler=None, batch_label=None,
) -> bool:
    """
    Main routing execution entry point triggered by UI dock drop signals.
    Returns True if any items were successfully plotted, False otherwise.

    The order of the lanes, the claim-run-release skeleton and the error policy
    live in `orchestration.channel_drop.run_channel_drop`; this wraps the dock in
    the `DropTarget` it runs against.

    The two collaborators are passed in rather than read off the window
    (#242): `workspace` is the Workspace whose `dock_tasks` every background
    path goes through -- a spectrogram drop computes as the dock's own
    compute -- and `live_drop_handler` serves result-content docks.
    Only `workspace` is required: every background path runs through
    it, so a caller that forgot it would otherwise fail with an AttributeError
    deep inside a dispatcher instead of at the call. The handler serves one
    branch and is genuinely absent when a drop cannot reach that branch.
    """
    target = _DockDropTarget(dock_instance, app_context, workspace, live_drop_handler)
    return run_channel_drop(
        target, raw_descriptors, pending_drops=dock_instance.pending_drops,
        workers=live_compute, batch_label=batch_label)


class _DockDropTarget:
    """One dock and the shell around it, as the `DropTarget` a drop run needs."""

    def __init__(self, dock, app_context, workspace, live_drop_handler):
        from gui.workspace.graph_dock import GraphDock
        from gui.workspace.spectrogram_dock import SpectrogramDock

        self._dock = dock
        self._context = app_context
        self._workspace = workspace
        self._live_drop_handler = live_drop_handler
        self._is_graph = isinstance(dock, GraphDock)
        # An order dock holding h5 result-set curves (ADR §1.30,
        # ResultContentHandler.load_into_dock) can hold channels from several
        # source files at once, so it has no single dock-wide tacho to reuse --
        # routed separately, see live_channel_drop.LiveChannelDropHandler.
        curves = dock.curves if self._is_graph else None
        # Pending result-content live orders are one more way a drop is in flight.
        live_drops = getattr(dock, "live_drops", None)
        self.facts = DropFacts(
            self._is_graph, isinstance(dock, SpectrogramDock),
            getattr(dock, "analysis_kind", ANALYSIS_TIME),
            self._is_graph and dock.curves.holds_result_content,
            plotted_keys=frozenset(read_plotted_keys(
                curves.descriptors() if curves else [],
                curves.model.traces if curves and curves.model else [],
            )),
            live_pending_keys=frozenset(
                key for desc in (live_drops.pending_descriptors() if live_drops is not None else [])
                for key in drop_keys(desc)),
        )

    def log(self, message):
        self._context.log(message)

    def run_task(self, worker, *args, on_success, on_error, **run_kwargs):
        self._workspace.dock_tasks.run(
            self._dock.dock_id, worker, *args,
            on_success=on_success, on_error=on_error, purpose=PURPOSE_DROP, **run_kwargs)

    def open_imported_channels(self, descriptors):
        self._workspace.open_channels_tab(resolve_dropped_channels(descriptors, self._context))

    def result_content_batch(self, label):
        handler = self._live_drop_handler
        return handler.batch(label) if handler is not None else nullcontext()

    def serve_result_content(self, descriptor):
        handler = self._live_drop_handler
        return handler is not None and handler.handle_dropped_channel(self._dock, descriptor)

    def spectrum_config(self):
        return _spectrum_config_for_drop(self._dock, self._context)

    def restored_config(self, recipe):
        return self._workspace.resolve_restore_config(self.facts.analysis_kind, recipe)

    def drop_restore(self, resolved):
        project_path = getattr(getattr(self._context, "project_session", None), "path", None)
        return live_compute.DropRestore(
            project_path=project_path,
            subject=resolve_analysis_kind(self.facts.analysis_kind).display_name,
            resolved=resolved,
        )

    def _keep(self, desc, channel_name, result):
        """A dropped channel's curve is drawn: say it came from its Tab cache
        file, and keep it there."""
        if result.from_tab_cache:
            self._workspace.log_tab_cache_hit(self._dock, channel_name)
        self._workspace.keep_dropped_channel(self._dock, desc, result)

    def cache_finder(self):
        """The worker-thread cache lookup, or None when the ribbon switched the cache off."""
        return resolve_cache_finder(getattr(self._context, "project_session", None),
                                    getattr(self._context, "use_result_cache_lookup", True))

    def order_inputs(self):
        context = self._context
        return OrderDropInputs(
            config=context.order_tracking_settings,
            run_lookup=self._context.pool.run_lookup,
            dock_tacho=getattr(self._dock, "tacho_block", None),
            with_overall_level=context.order_tracking_overall_level,
        )

    def overall_level_inputs(self):
        return OverallLevelDropInputs(
            config=self._context.overall_level_settings,
            run_lookup=self._context.pool.run_lookup,
            dock_tacho=getattr(self._dock, "tacho_block", None),
        )

    def render_simple(self, rendered, *, is_spec):
        dock = self._dock
        # A SpectrogramDock holds no curves to coalesce; a GraphDock lands the
        # whole drop as one draw (#440).
        with nullcontext() if is_spec else dock.curves.coalesce_changes():
            for desc, data_block, spectrum_result in rendered:
                if is_spec:
                    _route_to_spectrogram(dock, data_block, desc, self._context, self._workspace)
                elif spectrum_result is not None:
                    if spectrum_result.from_cache:
                        self._context.log(build_cache_hit_line(
                            f"Spectrum for {desc['channel_name']}", spectrum_result.result_set_label))
                    _render_spectrum_overlay(dock, spectrum_result.blocks[0], desc)
                    self._keep(desc, desc["channel_name"], spectrum_result)
                else:
                    _route_to_time_domain(dock, data_block, desc, self._context)
        if not is_spec:
            # A SpectrogramDock has no curves --
            # update_dock_tab_title would read that as 0 and stomp the tab with
            # "Compare: 0 Channels".
            update_dock_tab_title(dock)

    def render_orders(self, rendered):
        for desc, ch_name, result in rendered:
            if result.from_cache:
                self._context.log(build_cache_hit_line(
                    f"Order tracking for {ch_name}", result.result_set_label))
            _render_order_overlay(self._dock, desc["file_name"], ch_name, result.blocks)
            self._keep(desc, ch_name, result)
        # The end-of-batch title update of the run already ran by the time
        # this lands, so this dock's tab must refresh its own count now that
        # the curves it was waiting on actually exist.
        update_dock_tab_title(self._dock)

    def render_overall_level(self, rendered):
        dock = self._dock
        with dock.curves.coalesce_changes():  # one draw for the whole drop (#440)
            for desc, ch_name, result in rendered:
                if result.from_cache:
                    self._context.log(build_cache_hit_line(
                        f"Overall Level for {ch_name}", result.result_set_label, what="settings"))
                _render_overall_level_overlay(dock, result.blocks[0], self._context)
                self._keep(desc, ch_name, result)
        update_dock_tab_title(dock)

    def refresh_title(self):
        update_dock_tab_title(self._dock)


def _route_to_time_domain(dock_instance, data_block, desc, app_context):
    """Renders raw time arrays onto a standard GraphDock."""
    file_name, ch_name = desc["file_name"], desc["channel_name"]
    dock_instance.add_curve(
        x=data_block.primary_axis.values.astype(np.float64),
        y=data_block.values.astype(np.float64),
        source_label=f"[{file_name}] {ch_name}",
        incoming_unit=data_block.value_unit,
        source_meta=data_block.display_meta(),
        block=data_block,
    )


def _spectrum_config_for_drop(dock_instance, app_context) -> SpectrumConfig:
    """
    Which FFT settings a newly dropped comparison curve is computed with (R1,
    ideas/session_persistence/PLAN.md §4).

    Default is the ribbon's current SpectrumConfig. When
    ``new_curve_config_from_trace`` is on and the dock already holds a base
    curve with a recorded ``compute_spec`` (Trace.compute_spec, S2), the drop
    instead inherits that curve's settings, so a comparison lands on the same
    FFT/window/format as what's already on screen -- comparing a curve
    computed with mismatched settings to one that was is not a comparison.
    ``remove_dc`` is not part of ``compute_spec`` (applied before the block
    exists, see plot_model_builder._compute_spec_for) and always falls back to
    the ribbon's current value.
    """
    ribbon_config = app_context.spectrum_settings
    if not getattr(app_context, "new_curve_config_from_trace", False):
        return ribbon_config

    model = dock_instance.curves.model
    base = next((t for t in model.traces if t.is_base), None) if model else None
    spec = base.compute_spec if base is not None else None
    if not spec:
        return ribbon_config

    return dataclasses.replace(
        ribbon_config,
        fft_size=spec.get("fft_size", ribbon_config.fft_size),
        window_type=spec.get("window_type", ribbon_config.window_type),
        amplitude_mode=spec.get("amplitude_mode", ribbon_config.amplitude_mode),
        spectrum_format=spec.get("spectrum_format", ribbon_config.spectrum_format),
        averaging_type=spec.get("averaging_type", ribbon_config.averaging_type),
        exponential_alpha=spec.get("exponential_alpha", ribbon_config.exponential_alpha),
    )


def _render_spectrum_overlay(dock_instance, result_block, desc):
    """Overlays an already-computed (or cached) spectrum onto the target dock;
    the block carries its channel's identity either way."""
    file_name, ch_name = desc["file_name"], desc["channel_name"]

    freqs = result_block.primary_axis.values
    amps, y_unit = result_block.values, result_block.value_unit
    dock_instance.add_curve(
        x=freqs.astype(np.float64),
        y=amps.astype(np.float64),
        source_label=f"[{file_name}] {ch_name}",
        incoming_unit=y_unit,
        source_meta=result_block.display_meta(),
        block=result_block,
    )


def _render_order_overlay(dock_instance, file_name, ch_name, blocks) -> None:
    """Renders each requested order -- and the Overall Level and Residual
    curves, which carry no order number -- as a separate curve overlay on the
    dock, landed as one draw (#440)."""
    with dock_instance.curves.coalesce_changes():
        for block in blocks:
            order = block.provenance.params.get(PARAM_ORDER)
            dock_instance.add_curve(
                x=block.primary_axis.values.astype(np.float64),
                y=block.values.astype(np.float64),
                source_label=f"Order {order} [{ch_name}]",
                incoming_unit=block.value_unit,
                source_meta=block.display_meta(),
                block=block,
                title=f"Order Compare: [{file_name}]",
            )


def _render_overall_level_overlay(dock_instance, result_block, app_context) -> None:
    """
    Adds one Overall Level curve to the dock (issue #125).

    The "different Nyquist" decision is a pure function
    over the Qt-free model (``overall_level_band_differs_from_dock``); this is
    the drop renderer that decides to log it, exactly once per curve added.
    """
    if not dock_instance.curves.is_empty and overall_level_band_differs_from_dock(dock_instance.curves.model, result_block):
        app_context.log(
            "WORKSPACE: Overall Level curves on this dock integrate different bands."
        )

    dock_instance.add_curve(
        x=result_block.primary_axis.values.astype(np.float64),
        y=result_block.values.astype(np.float64),
        source_meta=result_block.display_meta(),
        block=result_block,
    )


def _route_to_spectrogram(dock_instance, data_block, desc, app_context, workspace):
    """
    Pairs a channel dropped onto a spectrogram with the one it already holds
    and, once both are there, computes it as the dock's own compute (one
    `compute` slot: a Refresh supersedes it, it supersedes one in flight). A
    failure leaves the image already on screen, as a failed Refresh does.

    A spectrogram restored from the Tab cache shows its image without the raw
    channels it was computed from; the one a drop does not bring is read from
    the dock's measurement by that compute.
    """
    config = app_context.spectrogram_settings
    vib_block = getattr(dock_instance, "vib_block", None)
    decision = decide_spectrogram_drop(
        data_block,
        vib_block,
        getattr(dock_instance, "tacho_block", None),
        config.tracking_mode,
        channel_name=desc["channel_name"],
        measurement_path=_restored_measurement_path(dock_instance) if vib_block is None else None,
    )
    for message in decision.messages:
        app_context.log(message)
    if decision.is_rejected:
        return

    # Refresh, the cache lookup and the saved tab all read the channel from
    # run_index/channel_meta, not from the blocks -- keep them on the dropped one.
    dropped = None
    if data_block.channel_type != "tacho":
        dropped = _resolve_dropped_channel(desc, app_context)
        if isinstance(dropped, str):
            app_context.log(dropped)
            return

    dock_instance.vib_block = decision.vib_block
    dock_instance.tacho_block = decision.tacho_block
    if dropped is not None:
        dock_instance.run_index, dock_instance.channel_meta = dropped
    if not decision.should_compute:
        return

    _update_spectrogram_tab_title(dock_instance)
    workspace.dispatch_compute(
        dock_instance, origin=ComputeOrigin.REFRESH, vib_block=dock_instance.vib_block)


def _restored_measurement_path(dock_instance):
    """The file of a spectrogram that shows an image it holds no raw channels
    for (restored from the Tab cache); None for any other."""
    spectrogram = getattr(dock_instance, "spectrogram", None)
    run_index = getattr(dock_instance, "run_index", None)
    if spectrogram is None or spectrogram.model is None or run_index is None:
        return None
    return run_index.file_path


def resolve_dropped_channels(raw_descriptors: list, app_context) -> list:
    """
    A drop's descriptors as the `(run_index, channel_meta, label)` rows a
    double click on the same Data Pool rows hands to
    Workspace.open_channels_tab. A descriptor whose file or channel is not in
    the pool is refused with its reason in the log -- no bare run is made up.
    """
    rows = []
    for desc in raw_descriptors:
        resolved = _resolve_dropped_channel(desc, app_context)
        if isinstance(resolved, str):
            app_context.log(resolved)
            continue
        rows.append((*resolved, desc["channel_name"]))
    return rows


def build_channel_descriptors(rows: list) -> list:
    """
    The drop descriptors of `(run_index, channel_meta, label)` rows -- the
    inverse of `resolve_dropped_channels`, in the shape a drag out of the Data
    Pool carries.
    """
    return [build_drop_descriptor(run_index, channel_meta) for run_index, channel_meta, _ in rows]


def _resolve_dropped_channel(desc, app_context):
    """The pooled run and channel a descriptor names, or the log line saying why it is refused."""
    name = desc["channel_name"]
    run = app_context.pool.run_lookup(desc["file_path"])
    if isinstance(run, DeadLink):
        return f"ERROR: Cannot add '{name}' -- its file is not currently loaded."
    channel = find_dropped_channel(run, name, desc["channel_index"])
    if channel is None:
        return f"ERROR: Cannot add '{name}' -- its channel was not found on '{run.file_name}'."
    return run, channel


def _update_spectrogram_tab_title(dock_instance):
    """
    Mirrors the "Spec: <file> [<channel>]" title Workspace gives a
    freshly opened spectrogram dock, so a channel replace (see Session J)
    keeps the tab in sync instead of leaving it on the first drop's name.
    """
    vib_block = getattr(dock_instance, "vib_block", None)
    if vib_block is None or dock_instance.parentWidget() is None:
        return
    clean_name = strip_channel_name_prefix(vib_block.source.channel_name)
    prefix = resolve_analysis_kind(ANALYSIS_SPECTROGRAM).title_prefix
    set_dock_tab_title(dock_instance, f"{prefix}{vib_block.source.file_name} [{clean_name}]")
