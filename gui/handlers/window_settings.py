# =====================================================================
# FILE: gui/handlers/window_settings.py
# =====================================================================
"""
Window settings actions for layout, graph, units, and result-cache preferences.

Groups the Settings window actions that modify QSettings and refresh
window layout or viewport rendering:
- "Reset Layout" clears dock layout and dialog geometry keys, restoring factory layout.
- "Reset All Settings" clears all application settings and restores factory layout.
- Graph Rendering applies AppContext performance settings to open viewports.
- The Settings window (gui/settings) reads its field values here and hands back
  the changed ones on Apply; the result-cache fields persist the values used by
  subsequent batch runs.
- The X axis unit (issue #459, Settings › Units) is stored with the open project,
  not in QSettings, and redraws every open dock.

All internal documentation strings and variable labels are standardly written
in English.
"""

from typing import Optional
from PySide6.QtWidgets import QMessageBox, QWidget

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
_GRAPH_KEYS = (
    "perf_downsample_enabled",
    "perf_auto_mode_active",
    "perf_manual_factor",
    "perf_render_screen_only",
)
_UNIT_KEYS = (
    "global_unit_acceleration",
    "global_unit_pressure",
    "global_unit_voltage",
    "global_unit_speed",
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
        self._applying_panels = False

    def read_settings_values(self) -> dict:
        """The applied value of every Settings window field, keyed like the fields."""
        context = self.app_context
        return {
            **self.read_panel_values(),
            "open_last_project_on_startup": context.shared_settings.value(
                "open_last_project_on_startup", False, type=bool),
            "check_for_updates_on_startup": context.shared_settings.value(
                "check_for_updates_on_startup", True, type=bool),
            "result_cache_compression": context.result_cache_compression,
            "use_result_cache_lookup": context.use_result_cache_lookup,
            **{key: getattr(context, key) for key in (*_UNIT_KEYS, *_GRAPH_KEYS)},
            "highlight_other_opacity": context.highlight_other_opacity,
            "theme": context.theme,
            "graph_theme": context.graph_theme,
            "x_axis_unit": context.project_session.x_axis_unit,
        }

    def read_panel_values(self) -> dict:
        """Panel visibility as Settings window fields ("panel_explorer", ...)."""
        return {f"panel_{key}": on for key, on in self.workspace_layout.panel_visibility().items()}

    def notify_panel_values(self, *_args) -> None:
        if not self._applying_panels:
            self.app_context.settings_changed.emit(self.read_panel_values())

    def apply_panel_values(self, changed: dict) -> None:
        """Show/hide panels immediately for preview, Apply or restore."""
        # Docks report half-done states while they move; only the final one counts,
        # since the Settings window lets a reported panel state win over an edit.
        self._applying_panels = True
        try:
            self.workspace_layout.apply_panel_visibility(
                {key.removeprefix("panel_"): on for key, on in changed.items()})
        finally:
            self._applying_panels = False
        self.notify_panel_values()

    def apply_settings(self, changed: dict) -> None:
        """Commit the Settings window's changed values (synchronous: a few QSettings writes, ADR §1.137)."""
        from view_models.settings import SETTINGS_IMMEDIATE_KEYS

        panels = {key: value for key, value in changed.items() if key in SETTINGS_IMMEDIATE_KEYS}
        if panels:
            self.apply_panel_values(panels)
        for key in ("open_last_project_on_startup", "check_for_updates_on_startup"):
            if key in changed:
                self.app_context.shared_settings.setValue(key, changed[key])
        if "theme" in changed:
            self.app_context.theme = changed["theme"]
            self.app_context.shared_settings.setValue("theme", changed["theme"])
            QMessageBox.information(self.parent_widget, "Theme", "Theme applies after restart.")
        if "graph_theme" in changed:
            self.app_context.graph_theme = changed["graph_theme"]
            self.app_context.shared_settings.setValue("graph_theme", changed["graph_theme"])
            QMessageBox.information(self.parent_widget, "Graph theme", "Graph theme applies after restart.")
        if "result_cache_compression" in changed:
            self.apply_cache_compression(changed["result_cache_compression"])
        if "use_result_cache_lookup" in changed:
            self.apply_use_result_cache_lookup(changed["use_result_cache_lookup"])
        if any(key in changed for key in _GRAPH_KEYS):
            values = {key: changed.get(key, getattr(self.app_context, key)) for key in _GRAPH_KEYS}
            self.app_context.update_graph_settings(
                downsample_enabled=values["perf_downsample_enabled"],
                auto_mode_active=values["perf_auto_mode_active"],
                manual_factor=values["perf_manual_factor"],
                render_screen_only=values["perf_render_screen_only"],
            )
            self.workspace.apply_graph_performance_settings()
            self.log_panel.log_message("SYSTEM: Graph performance criteria updated successfully.")
        if "highlight_other_opacity" in changed:
            self.app_context.set_highlight_other_opacity(changed["highlight_other_opacity"])
            self.workspace.apply_highlight_opacity()
        changed_units = [key for key in _UNIT_KEYS if key in changed]
        if changed_units:
            self.apply_units({key: changed[key] for key in changed_units})
        if "x_axis_unit" in changed:
            self.apply_x_axis_unit(changed["x_axis_unit"])

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

    def apply_units(self, units: dict) -> None:
        """Persist the application units and refresh their consumers: open graphs and the Explorer."""
        for key, unit in units.items():
            self.app_context.update_unit_setting(key, unit)
        self.app_context.log("SYSTEM: Centralized global engineering units preferred markers updated.")
        self._refresh_unit_consumers()

    def _refresh_unit_consumers(self) -> None:
        self.workspace.replot_time_docks_for_unit_change()
        if self.explorer_panel is not None and hasattr(self.explorer_panel, "rebuild_tree_view"):
            self.explorer_panel.rebuild_tree_view()

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

    def reset_layout(self) -> bool:
        """Clears the layout keys from this window's QSettings and restores the factory dock layout."""
        if not self._confirm(
            "Reset Layout",
            "Reset this window's dock layout to its default?",
            _RESET_LAYOUT_DETAILS,
        ):
            self.log_panel.log_message("SYSTEM: Reset Layout cancelled.")
            return False

        settings = self.app_context.settings
        for key in settings.allKeys():
            if key in _LAYOUT_KEYS or key.startswith(_LAYOUT_KEY_PREFIXES):
                settings.remove(key)

        self.workspace_layout.restore_factory()
        self.log_panel.log_message("SYSTEM: Factory dock layout restored.")
        return True

    def reset_all_settings(self) -> bool:
        """Wipes both QSettings groups (this window's and the shared one) and restores the factory layout."""
        if not self._confirm(
            "Reset All Settings",
            "Reset ALL application settings to their defaults?",
            _RESET_ALL_DETAILS,
        ):
            self.log_panel.log_message("SYSTEM: Reset All Settings cancelled.")
            return False

        context = self.app_context
        # Everything in both groups is app state or user preference -- nothing
        # external -- so a full clear is the honest whitelist here.
        context.settings.clear()
        context.shared_settings.clear()
        # The in-memory values follow, so nothing (Settings window included)
        # keeps showing a value that is no longer stored.
        context.read_shared_settings()
        self.workspace.apply_graph_performance_settings()
        self.workspace.apply_highlight_opacity()
        self._refresh_unit_consumers()

        self.workspace_layout.restore_factory()
        self.log_panel.log_message(
            "SYSTEM: All settings reset to defaults. Restart to fully apply DSP defaults."
        )
        return True
