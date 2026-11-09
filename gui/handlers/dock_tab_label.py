"""GUI-only helpers for updating workspace Tab labels."""

from typing import List

from PySide6.QtWidgets import QTabWidget

from gui.workspace.graph_dock import GraphDock
from gui.workspace.spectrogram_dock import SpectrogramDock
from view_models.tab_label import (
    TabLabel,
    TabSource,
    build_tab_label,
)


def resolve_dock_sources(dock_instance) -> List[TabSource]:
    """Resolves the TabSource items represented on `dock_instance`."""
    if isinstance(dock_instance, GraphDock):
        model = dock_instance.curves.model
        if model is not None and model.traces:
            return [_trace_source(trace, dock_instance) for trace in model.traces]

    if isinstance(dock_instance, SpectrogramDock) and dock_instance.vib_block is not None:
        source = dock_instance.vib_block.source
        if source.file_name or source.channel_name:
            return [TabSource(file_name=source.file_name, channel_name=source.channel_name)]

    # No content yet (e.g. before the initial compute completes): what the dock was opened on.
    run_index = dock_instance.run_index
    channel_meta = dock_instance.channel_meta
    if run_index is not None or channel_meta is not None:
        file_name = run_index.file_name if run_index is not None else ""
        channel_name = channel_meta.name if channel_meta is not None else ""
        return [TabSource(file_name=file_name, channel_name=channel_name)]

    return []


def _trace_source(trace, dock_instance) -> TabSource:
    """One curve of a graph dock as a TabSource; its base curve is named after the dock's channel."""
    meta = trace.meta_ref or {}
    file_name = meta.get("file_name", "") or trace.file_name
    if not file_name and trace.is_base and dock_instance.run_index is not None:
        file_name = dock_instance.run_index.file_name

    channel_name = meta.get("channel_name", "") or trace.channel_name
    if trace.is_base and dock_instance.channel_meta is not None:
        channel_name = dock_instance.channel_meta.name

    return TabSource(file_name=file_name, channel_name=channel_name, result_set_id=trace.result_set_id)


def resolve_dock_tab_label(dock_instance) -> TabLabel:
    """Builds the TabLabel for `dock_instance` from its state, warnings included."""
    return build_tab_label(
        dock_instance.analysis_kind,
        resolve_dock_sources(dock_instance),
        dead_link=dock_instance.dead_link,
        compute_failed=dock_instance.compute_failed,
        custom_label=dock_instance.custom_tab_label,
    )


def set_dock_tab_label(dock_instance, label: str, tooltip: str):
    """Sets the label and tooltip of the QTabWidget tab that hosts `dock_instance`."""
    current_parent = dock_instance.parentWidget()
    while current_parent is not None:
        if isinstance(current_parent, QTabWidget):
            index = current_parent.indexOf(dock_instance)
            if index != -1:
                current_parent.setTabText(index, label)
                current_parent.setTabToolTip(index, tooltip)
            break
        current_parent = current_parent.parentWidget()


def update_dock_tab_label(dock_instance) -> TabLabel:
    """Rewrites the tab's label and tooltip from the dock's state -- the one
    writer of a live tab's text, so no other text can go stale under it (#900)."""
    tab_label = resolve_dock_tab_label(dock_instance)
    set_dock_tab_label(dock_instance, tab_label.label, tab_label.tooltip)
    return tab_label
