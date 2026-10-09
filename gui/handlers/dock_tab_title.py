"""GUI-only helpers for updating workspace tab titles."""

from PySide6.QtWidgets import QTabWidget


def set_dock_tab_title(dock_instance, title):
    """Sets the label of the QTabWidget tab that hosts `dock_instance`."""
    current_parent = dock_instance.parentWidget()
    while current_parent is not None:
        if isinstance(current_parent, QTabWidget):
            index = current_parent.indexOf(dock_instance)
            if index != -1:
                current_parent.setTabText(index, title)
            break
        current_parent = current_parent.parentWidget()


def update_dock_tab_title(dock_instance):
    """Dynamically updates the QTabWidget label to reflect active curve counts."""
    curves = getattr(dock_instance, "curves", None)  # a SpectrogramDock has none
    total = len(curves.descriptors()) if curves is not None else 0
    set_dock_tab_title(dock_instance, f"Compare: {total} Channels")
