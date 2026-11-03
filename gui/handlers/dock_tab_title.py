"""GUI-only helpers for updating workspace tab titles."""

from typing import List, Optional

from PySide6.QtWidgets import QTabWidget

from view_models.tab_label import (
    TabLabel,
    TabSource,
    build_tab_label,
)


def resolve_dock_sources(dock_instance) -> List[TabSource]:
    """Resolves the TabSource items represented on `dock_instance`."""
    sources: List[TabSource] = []
    curves = getattr(dock_instance, "curves", None)
    if curves is not None and getattr(curves, "model", None) is not None:
        traces = curves.model.traces
        if traces:
            for t in traces:
                meta = getattr(t, "meta_ref", None) or {}
                file_name = (
                    meta.get("file_name", "")
                    or getattr(t, "file_name", "")
                )
                if not file_name and getattr(t, "is_base", False) and getattr(dock_instance, "run_index", None):
                    file_name = dock_instance.run_index.file_name

                channel_name = (
                    meta.get("channel_name", "")
                    or getattr(t, "channel_name", "")
                )
                if getattr(t, "is_base", False) and getattr(dock_instance, "channel_meta", None):
                    channel_name = dock_instance.channel_meta.name

                sources.append(
                    TabSource(
                        file_name=file_name,
                        channel_name=channel_name,
                        result_set_id=getattr(t, "result_set_id", ""),
                    )
                )
            return sources

    # If dock has vib_block (e.g. SpectrogramDock)
    vib_block = getattr(dock_instance, "vib_block", None)
    if vib_block is not None and hasattr(vib_block, "source"):
        file_name = getattr(vib_block.source, "file_name", "")
        channel_name = getattr(vib_block.source, "channel_name", "")
        if file_name or channel_name:
            return [TabSource(file_name=file_name, channel_name=channel_name)]

    # If dock has run_index and channel_meta (e.g. before initial compute completes, or SpectrogramDock)
    run_index = getattr(dock_instance, "run_index", None)
    channel_meta = getattr(dock_instance, "channel_meta", None)
    if run_index is not None or channel_meta is not None:
        file_name = run_index.file_name if run_index is not None else ""
        channel_name = channel_meta.name if channel_meta is not None else ""
        return [TabSource(file_name=file_name, channel_name=channel_name)]

    return sources


def resolve_dock_tab_label(dock_instance, *, custom_label: Optional[str] = None) -> TabLabel:
    """Builds the TabLabel for `dock_instance`."""
    analysis_kind = getattr(dock_instance, "analysis_kind", "")
    sources = resolve_dock_sources(dock_instance)
    dead_link = getattr(dock_instance, "dead_link", None)
    if custom_label is None:
        custom_label = getattr(dock_instance, "custom_tab_label", None)
    return build_tab_label(
        analysis_kind,
        sources,
        dead_link=dead_link,
        custom_label=custom_label,
    )


def set_dock_tab_title(dock_instance, title: str, tooltip: str = ""):
    """Sets the label and tooltip of the QTabWidget tab that hosts `dock_instance`."""
    current_parent = dock_instance.parentWidget()
    while current_parent is not None:
        if isinstance(current_parent, QTabWidget):
            index = current_parent.indexOf(dock_instance)
            if index != -1:
                current_parent.setTabText(index, title)
                if tooltip:
                    current_parent.setTabToolTip(index, tooltip)
            break
        current_parent = current_parent.parentWidget()


def update_dock_tab_title(dock_instance, *, custom_label: Optional[str] = None) -> TabLabel:
    """Dynamically updates the QTabWidget label and tooltip using view_models.tab_label."""
    tab_label = resolve_dock_tab_label(dock_instance, custom_label=custom_label)
    set_dock_tab_title(dock_instance, tab_label.label, tab_label.tooltip)
    return tab_label
