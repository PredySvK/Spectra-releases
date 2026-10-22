# =====================================================================
# FILE: gui/workspace/channel_drop.py
# =====================================================================
"""
Stateless Service Action handling the routing of dropped channels onto workspace docks.
Strictly decoupled from direct Data I/O. Uses DTO configurations to decouple from UI.
Coordinates between the Presentation layer (Docks) and the Pipeline layer (DataAccessor, DSP Core).
All internal documentation strings and variable labels are standardly written in English.
"""

from contextlib import nullcontext
import numpy as np

from core.block_kinds import PARAM_ORDER
from core.units import strip_channel_name_prefix
from view_models.analysis_kinds import (
    ANALYSIS_SPECTROGRAM, ANALYSIS_TIME, resolve_analysis_kind,
)
from orchestration import live_compute
from orchestration.live_compute import ComputeOrigin, resolve_cache_finder
from orchestration.dock_tasks import PURPOSE_DROP
from orchestration.channel_drop import (
    DropFacts,
    OrderDropInputs,
    OverallLevelDropInputs,
    SpectrogramDropInputs,
    SpectrumDropInputs,
    drop_keys,
    read_plotted_keys,
    resolve_dropped_channels,
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

    The order of the lanes, the claim-run-release skeleton, the landing of
    every result and the error policy live in
    `orchestration.channel_drop.run_channel_drop`; this wraps the dock in the
    `DropTarget` it runs against, which only draws.

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
        context = self._context
        self._workspace.open_channels_tab(
            resolve_dropped_channels(descriptors, context.pool.run_lookup, context.log))

    def result_content_batch(self, label):
        handler = self._live_drop_handler
        return handler.batch(label) if handler is not None else nullcontext()

    def serve_result_content(self, descriptor):
        handler = self._live_drop_handler
        return handler is not None and handler.handle_dropped_channel(self._dock, descriptor)

    def spectrum_inputs(self):
        """The ribbon config, the "new curve takes the trace's settings"
        choice and the compute spec and display settings of the dock's base trace, if it has one."""
        context = self._context
        model = self._dock.curves.model
        base = next((t for t in model.traces if t.is_base), None) if model else None
        return SpectrumDropInputs(
            config=context.spectrum_settings,
            config_from_trace=getattr(context, "new_curve_config_from_trace", False),
            base_compute_spec=base.compute_spec if base is not None else None,
            base_spectrum_format=base.spectrum_format if base is not None else "",
            base_amplitude_mode=base.amplitude_mode if base is not None else "",
        )

    def restored_config(self, recipe):
        return self._workspace.resolve_restore_config(self.facts.analysis_kind, recipe)

    def drop_restore(self, resolved):
        project_path = getattr(getattr(self._context, "project_session", None), "path", None)
        return live_compute.DropRestore(
            project_path=project_path,
            subject=resolve_analysis_kind(self.facts.analysis_kind).display_name,
            resolved=resolved,
        )

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

    def drawing(self):
        # A SpectrogramDock holds no curves to coalesce.
        return self._dock.curves.coalesce_changes() if self._is_graph else nullcontext()

    def draw_time_curve(self, descriptor, block):
        _add_curve(self._dock, block, source_label=_source_label(descriptor),
                   incoming_unit=block.value_unit)

    def draw_spectrum_curve(self, descriptor, block):
        # The block carries its channel's identity, computed or from a cache.
        _add_curve(self._dock, block, source_label=_source_label(descriptor),
                   incoming_unit=block.value_unit)

    def draw_order_curves(self, descriptor, channel_name, blocks):
        for block in blocks:
            order = block.provenance.params.get(PARAM_ORDER)
            _add_curve(self._dock, block, source_label=f"Order {order} [{channel_name}]",
                       incoming_unit=block.value_unit,
                       title=f"Order Compare: [{descriptor['file_name']}]")

    def draw_overall_level_curve(self, block):
        _add_curve(self._dock, block)

    def plot_model(self):
        return self._dock.curves.model

    def keep(self, descriptor, result):
        self._workspace.keep_dropped_channel(self._dock, descriptor, result)

    def spectrogram_inputs(self):
        dock = self._dock
        return SpectrogramDropInputs(
            vib_block=getattr(dock, "vib_block", None),
            tacho_block=getattr(dock, "tacho_block", None),
            tracking_mode=self._context.spectrogram_settings.tracking_mode,
            restored_measurement_path=_restored_measurement_path(dock),
            run_lookup=self._context.pool.run_lookup,
        )

    def hold_spectrogram_channels(self, vib_block, tacho_block, dropped):
        dock = self._dock
        dock.vib_block = vib_block
        dock.tacho_block = tacho_block
        if dropped is not None:
            dock.run_index, dock.channel_meta = dropped

    def run_spectrogram_compute(self):
        """The dock's own compute (one `compute` slot: a Refresh supersedes
        it, it supersedes one in flight); a failure leaves the image already
        on screen, as a failed Refresh does."""
        dock = self._dock
        _update_spectrogram_tab_title(dock)
        self._workspace.dispatch_compute(
            dock, origin=ComputeOrigin.REFRESH, vib_block=dock.vib_block)

    def refresh_title(self):
        update_dock_tab_title(self._dock)


def _source_label(descriptor):
    return f"[{descriptor['file_name']}] {descriptor['channel_name']}"


def _add_curve(dock, block, **labels):
    """One curve of ``block`` on ``dock``; ``labels`` are add_curve's own
    (an Overall Level curve is added without any, as it always was)."""
    dock.add_curve(
        x=block.primary_axis.values.astype(np.float64),
        y=block.values.astype(np.float64),
        source_meta=block.display_meta(),
        block=block,
        **labels,
    )


def _restored_measurement_path(dock_instance):
    """The file of a spectrogram that shows an image it holds no raw channels
    for (restored from the Tab cache); None for any other."""
    spectrogram = getattr(dock_instance, "spectrogram", None)
    run_index = getattr(dock_instance, "run_index", None)
    if spectrogram is None or spectrogram.model is None or run_index is None:
        return None
    return run_index.file_path


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
