# =====================================================================
# FILE: gui/workspace/live_compute.py
# =====================================================================
"""
A dock as `orchestration.live_compute.BaseCurveTarget`: what the Base curve
compute does to a tab, drawn and written onto the widget. When and in what order
is the compute's own.
"""

from gui.handlers.dock_tab_label import update_dock_tab_label
from gui.workspace.plot_title import set_plot_title
from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from view_models.plot import NOTHING_PENDING, resolve_curve_channel_key


class DockBaseCurveTarget:
    """One dock of `workspace`, for the time one step of its compute takes."""

    def __init__(self, workspace, dock):
        self._workspace = workspace
        self._dock = dock

    @property
    def analysis_kind(self):
        return self._dock.analysis_kind

    @property
    def run_index(self):
        return self._dock.run_index

    @property
    def channel_meta(self):
        return self._dock.channel_meta

    @property
    def tacho_block(self):
        return self._dock.tacho_block

    def show_status(self, text):
        set_plot_title(self._dock.plot_widget, text)

    def hold_read_channels(self, vib_block, tacho_block):
        if vib_block is not None and isinstance(self._dock, SpectrogramDock):
            self._dock.vib_block = vib_block
        if tacho_block is not None:
            self._dock.tacho_block = tacho_block

    def draw(self, blocks):
        if isinstance(self._dock, SpectrogramDock):
            self._dock.plot_block(blocks[0])
        else:
            self._dock.plot_blocks(list(blocks))

    def clear_compute_failed(self):
        if self._dock.compute_failed:
            self._dock.compute_failed = False
            update_dock_tab_label(self._dock)

    def take_pending_restore(self):
        # A spectrogram holds no overlays and no result sets.
        if not isinstance(self._dock, GraphDock):
            return NOTHING_PENDING
        return self._dock.curves.take_pending_restore()

    def abort_restore(self):
        if isinstance(self._dock, GraphDock):
            self._dock.curves.abort_restore()

    def load_result_sets(self, result_set_ids):
        handler = self._workspace.result_content_handler
        if handler is not None:
            handler.load_into_dock(self._dock, list(result_set_ids))

    def drop_overlays(self, overlays, *, from_refresh):
        self._workspace.route_channel_drop(
            self._dock, list(overlays), mark_work_changed=False, from_refresh=from_refresh)

    def refresh_tab_label(self):
        update_dock_tab_label(self._dock)

    def restored_spec(self):
        return self._workspace.open_tabs.restored_spec(self._dock)

    def close(self):
        self._workspace.close_dock(self._dock, mark_work_changed=False)

    def show_dead_link(self, dead_link):
        dock = self._dock
        dock.dead_link = dead_link
        dock.run_index = None
        dock.channel_meta = None
        self.abort_restore()
        update_dock_tab_label(dock)

    def mark_compute_failed(self):
        self._dock.compute_failed = True
        update_dock_tab_label(self._dock)

    def base_recipe(self):
        dock = self._dock
        if isinstance(dock, SpectrogramDock):
            model = dock.spectrogram.model
            return model.compute_spec if model is not None else None
        base = dock.curves.base_trace
        return base.compute_spec if base is not None else None

    def dropped_curves(self, channel_key):
        model = self._dock.curves.model
        return [trace for trace in (model.traces if model is not None else [])
                if trace.is_dropped_channel and resolve_curve_channel_key(trace) == channel_key]
