# =====================================================================
# FILE: gui/handlers/window_settings.py
# =====================================================================
"""
Window settings actions for layout, graph, units, and result-cache preferences.

Groups the Settings window actions that modify QSettings and refresh
window layout or viewport rendering:
- "Reset Layout" clears dock layout and dialog geometry keys, restoring factory layout.
- "Reset All Settings" clears all application settings and restores factory layout.
- The Settings window (gui/settings) reads its field values here and hands back
  the changed ones on Apply. Application settings go to the Settings store; what a
  change sets off in this window (redraw graphs, rebuild the Explorer, a restart
  note) is the reaction table, subscribed to the store, so a change from anywhere
  -- Apply, Cursor Settings, Reset All Settings -- reacts the same.
- The X axis unit (issue #459, Settings › Units) is stored with the open project,
  not in QSettings, and redraws every open dock.

All internal documentation strings and variable labels are standardly written
in English.
"""

from typing import Callable, Optional
from PySide6.QtWidgets import QMessageBox, QWidget

from app_context import STARTUP_DIRECTORY_KEY
from core.settings import SETTING_DEFINITIONS, TOOL_SWITCH_KEYS
from gui.dialogs.dialog_state import is_dialog_geometry_key
from gui.workspace.workspace_layout import layout_settings_keys

__all__ = [
    "WindowSettingsHandler",
    "_RESET_LAYOUT_DETAILS",
    "_RESET_ALL_DETAILS",
]

_RESTART_KEYS = frozenset(key for key, definition in SETTING_DEFINITIONS.items()
                           if definition.applies_after_restart)
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
    Handles layout reset, the Settings window's values and what a settings change sets off.

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
        self._reactions = self.build_settings_reactions()
        # What this process draws with; a restart setting only needs a restart when it differs.
        self._running_values = {key: app_context.settings_store.value(key) for key in _RESTART_KEYS}
        app_context.settings_store.subscribe(self.react_to_settings)

    def read_settings_values(self) -> dict:
        """The applied value of every Settings window field, keyed like the fields."""
        store = self.app_context.settings_store
        return {
            **self.read_panel_values(),
            **{key: store.value(key) for key in SETTING_DEFINITIONS},
            "x_axis_unit": self.app_context.project_session.x_axis_unit,
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
        # The store tells react_to_settings what actually changed.
        self.app_context.settings_store.apply(
            {key: value for key, value in changed.items() if key in SETTING_DEFINITIONS})
        if "x_axis_unit" in changed:
            self.apply_x_axis_unit(changed["x_axis_unit"])

    def build_settings_reactions(self) -> tuple[tuple[frozenset, Callable[[dict], None]], ...]:
        """Key group -> what a change in it sets off in this window; a group reacts once per change."""
        return (
            (frozenset(key for key in SETTING_DEFINITIONS if key.startswith("perf_")),
             self._react_to_graph_performance),
            (frozenset(key for key in SETTING_DEFINITIONS if key.startswith(("global_unit_", "prefix_", "decimals_", "db_reference_"))),
             self._react_to_units),
            (frozenset({"highlight_other_opacity"}), lambda _changed: self.workspace.apply_highlight_opacity()),
            (frozenset({"track_table_opacity"}), lambda _changed: self.workspace.apply_track_table_opacity()),
            (TOOL_SWITCH_KEYS, lambda changed: self.workspace.apply_tool_switches(changed)),
            (_RESTART_KEYS, self._react_to_restart_settings),
        )

    def react_to_settings(self, changed: dict) -> None:
        """Run the reaction of every key group with a changed key."""
        for keys, reaction in self._reactions:
            group_changed = {key: value for key, value in changed.items() if key in keys}
            if group_changed:
                reaction(group_changed)

    def _react_to_graph_performance(self, _changed: dict) -> None:
        self.workspace.apply_graph_performance_settings()
        self.log_panel.log_message("SYSTEM: Graph performance criteria updated successfully.")

    def _react_to_units(self, _changed: dict) -> None:
        self.app_context.log("SYSTEM: Centralized global engineering units preferred markers updated.")
        self.workspace.replot_time_docks_for_unit_change()
        if self.explorer_panel is not None and hasattr(self.explorer_panel, "rebuild_tree_view"):
            self.explorer_panel.rebuild_tree_view()

    def _react_to_restart_settings(self, changed: dict) -> None:
        from view_models.settings import SETTINGS_PAGES

        changed = {key: value for key, value in changed.items() if value != self._running_values[key]}
        if not changed:
            return
        labels = {field.key: field.label for page in SETTINGS_PAGES for field in page.fields}
        names = " and ".join(labels[key] for key in changed)
        verb = "applies" if len(changed) == 1 else "apply"
        QMessageBox.information(self.parent_widget, "Restart needed", f"{names} {verb} after restart.")

    def apply_x_axis_unit(self, x_axis_unit: str) -> None:
        """Store the global X axis unit with the open project and redraw every dock in it."""
        session = self.app_context.project_session
        if x_axis_unit == session.x_axis_unit:
            return
        session.set_x_axis_unit(x_axis_unit)
        self.workspace.replot_docks_for_x_axis_unit_change()
        self.log_panel.log_message(f"SYSTEM: X axis unit set to {x_axis_unit}.")

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

        # Each writer names its own keys; this only asks.
        settings = self.app_context.settings
        layout_keys = {*layout_settings_keys(), STARTUP_DIRECTORY_KEY}
        for key in settings.allKeys():
            if key in layout_keys or is_dialog_geometry_key(key):
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

        # Reports every setting, so the reaction table refreshes what shows them.
        self.app_context.clear_stored_settings()
        self.workspace_layout.restore_factory()
        self.log_panel.log_message(
            "SYSTEM: All settings reset to defaults. Restart to fully apply DSP defaults."
        )
        return True
