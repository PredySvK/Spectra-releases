# =====================================================================
# FILE: gui/handlers/window_settings.py
# =====================================================================
"""
Window settings actions for layout, graph, units, and result-cache preferences.

Groups the Settings ribbon tab actions that modify QSettings and refresh
window layout or viewport rendering:
- "Reset Layout" clears dock layout and dialog geometry keys, restoring factory layout.
- "Reset All Settings" clears all application settings and restores factory layout.
- "Graph Settings" opens the GraphSettingsDialog, updates AppContext performance
  settings, and updates open viewports.
- Global units opens the shared unit dialog; cache controls persist the values
  used by subsequent batch runs.
- The View group's X axis unit (issue #459) is stored with the open project,
  not in QSettings, and redraws every open dock.

All internal documentation strings and variable labels are standardly written
in English.
"""

from typing import Optional
from PySide6.QtWidgets import QMessageBox, QWidget

from gui.dialogs.graph_settings_dialog import GraphSettingsDialog

__all__ = [
    "WindowSettingsHandler",
    "_LAYOUT_KEY_PREFIXES",
    "_LAYOUT_KEYS",
    "_RESET_LAYOUT_DETAILS",
    "_RESET_ALL_DETAILS",
]

# Keys in the per-window (Root/Spawns) QSettings that describe *where things are*,
# as opposed to how the DSP is configured. "Reset Layout" removes exactly these;
# "Reset All Settings" clears the whole group anyway.
_LAYOUT_KEY_PREFIXES = (
    "window_layout_state_",
    "explorer_dock_width_",
    "bottom_dock_height_",
    "bottom_tabs_visible_",
    "last_directory_",
    # Per-dialog remembered size/position (gui/dialogs/dialog_state.py).
    "dialog_geometry_",
)
_LAYOUT_KEYS = (
    "primary_startup_data_directory",
)

_RESET_LAYOUT_DETAILS = (
    "Reset Layout returns this window to its factory dock arrangement. It clears:\n"
    "\n"
    "  - Dock positions and sizes\n"
    "  - Which docks are visible\n"
    "  - Remembered sizes of pop-up dialogs (e.g. Metadata and Filter Settings)\n"
    "  - The last-viewed data folder this window reopens on startup\n"
    "\n"
    "It does NOT touch unit preferences, default graph/FFT settings, the "
    "recent-projects list or startup behaviour. It never touches a project "
    "file, a measurement file or a cached result."
)

_RESET_ALL_DETAILS = (
    "Reset All Settings returns the whole application to a fresh-install state. "
    "On top of everything Reset Layout does, it also clears:\n"
    "\n"
    "  - Global unit preferences (acceleration, pressure, voltage, speed)\n"
    "  - Default graph and FFT / spectrum / order-tracking settings\n"
    "  - The recent-projects list\n"
    "  - 'Open last project on startup' and other startup behaviour\n"
    "  - Downsampling / rendering performance preferences\n"
    "\n"
    "It never touches a project file, a measurement file or a cached result -- "
    "open projects and data on disk are left exactly as they are. Some changes "
    "take full effect only after a restart."
)


class WindowSettingsHandler:
    """
    Handles layout reset, settings, graph performance, and global units.

    Explicit dependencies injected via constructor:
    - app_context: application settings and performance state.
    - workspace_layout: manages dock layout and factory restoration.
    - workspace: applies graph performance settings to open viewports.
    - log_panel: system log widget for user feedback.
    - parent_widget: parent QWidget for modal dialogs.
    - explorer_panel: refresh target for global unit changes.
    """

    def __init__(
        self,
        app_context,
        workspace_layout,
        workspace,
        log_panel,
        parent_widget: Optional[QWidget] = None,
        *,
        explorer_panel,
    ) -> None:
        self.app_context = app_context
        self.workspace_layout = workspace_layout
        self.workspace = workspace
        self.log_panel = log_panel
        self.parent_widget = parent_widget
        self.explorer_panel = explorer_panel
        self._parent = parent_widget

    def apply_cache_compression(self, value: str) -> None:
        """Persist the compression used by subsequent result-cache writes."""
        self.app_context.result_cache_compression = value
        self.app_context.shared_settings.setValue("result_cache_compression", value)

    def apply_use_result_cache_lookup(self, value: bool) -> None:
        """Persist whether result-cache lookup is enabled for subsequent runs."""
        enabled = bool(value)
        self.app_context.use_result_cache_lookup = enabled
        self.app_context.shared_settings.setValue("use_result_cache_lookup", enabled)

    def apply_x_axis_unit(self, x_axis_unit: str) -> None:
        """Store the global X axis unit with the open project and redraw every dock in it."""
        session = self.app_context.project_session
        if x_axis_unit == session.x_axis_unit:
            return
        session.set_x_axis_unit(x_axis_unit)
        self.workspace.replot_docks_for_x_axis_unit_change()
        self.log_panel.log_message(f"SYSTEM: X axis unit set to {x_axis_unit}.")

    def open_global_units_dialog(self) -> None:
        """Open global unit preferences and refresh their GUI consumers."""
        from gui.dialogs.unit_settings_dialog import UnitSettingsDialog

        dialog = UnitSettingsDialog(
            app_context=self.app_context,
            parent=self.parent_widget,
            workspace=self.workspace,
            explorer_panel=self.explorer_panel,
        )
        dialog.exec()
        dialog.deleteLater()

    def _confirm(self, title: str, text: str, details: str) -> bool:
        box = QMessageBox(self.parent_widget)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        box.setInformativeText("Click 'Show Details' to see exactly what is cleared.")
        box.setDetailedText(details)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def reset_layout(self) -> None:
        """Clears the layout keys from this window's QSettings and restores the factory dock layout."""
        if not self._confirm(
            "Reset Layout",
            "Reset this window's dock layout to its default?",
            _RESET_LAYOUT_DETAILS,
        ):
            self.log_panel.log_message("SYSTEM: Reset Layout cancelled.")
            return

        settings = self.app_context.settings
        for key in settings.allKeys():
            if key in _LAYOUT_KEYS or key.startswith(_LAYOUT_KEY_PREFIXES):
                settings.remove(key)

        self.workspace_layout.restore_factory()
        self.log_panel.log_message("SYSTEM: Factory dock layout restored.")

    def reset_all_settings(self) -> None:
        """Wipes both QSettings groups (this window's and the shared one) and restores the factory layout."""
        if not self._confirm(
            "Reset All Settings",
            "Reset ALL application settings to their defaults?",
            _RESET_ALL_DETAILS,
        ):
            self.log_panel.log_message("SYSTEM: Reset All Settings cancelled.")
            return

        context = self.app_context
        # Everything in both groups is app state or user preference -- nothing
        # external -- so a full clear is the honest whitelist here.
        context.settings.clear()
        context.shared_settings.clear()

        self.workspace_layout.restore_factory()
        self.log_panel.log_message(
            "SYSTEM: All settings reset to defaults. Restart to fully apply unit and DSP defaults."
        )

    def open_graph_settings(self) -> None:
        """Triggers the default graphical throughput dialog box and applies updates."""
        context = self.app_context

        current_state = {
            "downsample_enabled": context.perf_downsample_enabled,
            "auto_mode_active": context.perf_auto_mode_active,
            "manual_factor": context.perf_manual_factor,
            "render_screen_only": context.perf_render_screen_only,
        }

        dialog = GraphSettingsDialog(
            current_state,
            self.parent_widget,
            settings=context.settings,
        )
        accepted = dialog.exec()
        updated_config = dialog.get_finalized_configurations() if accepted else None
        # Parented to the main window/parent_widget, so deleteLater ensures cleanup.
        dialog.deleteLater()

        if accepted:
            # Update the global AppContext state securely via centralized public method
            context.update_graph_settings(
                downsample_enabled=updated_config["downsample_enabled"],
                auto_mode_active=updated_config["auto_mode_active"],
                manual_factor=updated_config["manual_factor"],
                render_screen_only=updated_config["render_screen_only"],
            )

            self.log_panel.log_message(
                "SYSTEM: Graph performance criteria updated successfully. Syncing open viewports..."
            )

            self.workspace.apply_graph_performance_settings()
