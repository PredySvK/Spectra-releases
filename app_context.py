# =====================================================================
# FILE: app_context.py
# =====================================================================
"""
Decoupled session-specific operational shared state repository.
Maintains strict boundaries utilizing dual-group isolated QSettings engines.
Acts as the single source of truth for all app settings.
Does NOT perform any direct Data I/O.
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Optional
from PySide6.QtCore import QObject, QSettings, Signal

from session.project import ProjectSession
from io_modules.project_store import DirectoryIndex, prune_untitled_scan_cache
from session.data_pool import DataPool, IntegrateResult
from session.settings import SettingsStore
from core.app_metadata import SETTINGS_ORGANIZATION, SETTINGS_ROOT, SETTINGS_SHARED
from core.cursor_config import CursorConfig
from core.units import UnitPreferences
from core.dsp_configs import SpectrumConfig, SpectrogramConfig, OrderTrackingConfig, OverallLevelConfig
from core.recent_projects import (
    RecentProject, parse_recent, serialize_recent, promote as _promote_recent,
)


# QSettings key (shared_settings) for how many curves "Load Result Sets…" reads
# without asking first -- an application-wide tuning knob, not a per-window one.
# 500 is a starting point to revisit once a real project's limits are known.
_RESULT_CONTENT_CURVE_LIMIT_KEY = "result_content_curve_limit"
_DEFAULT_RESULT_CONTENT_CURVE_LIMIT = 500


class _QSettingsStorage:
    """The Settings store's storage: the shared QSettings group."""

    def __init__(self, settings: QSettings):
        self._settings = settings

    def read(self, key: str):
        return self._settings.value(key)

    def write(self, key: str, value) -> None:
        self._settings.setValue(key, value)

    def remove(self, key: str) -> None:
        self._settings.remove(key)


def build_settings_store() -> SettingsStore:
    """A Settings store over the shared QSettings group, for main.py to read Theme before the window exists."""
    return SettingsStore(_QSettingsStorage(QSettings(SETTINGS_ORGANIZATION, SETTINGS_SHARED)))


def _setting(key: str) -> property:
    return property(lambda self: self.settings_store.value(key),
                    doc=f"The applied '{key}' setting; written only through settings_store.")


class AppContext(QObject):
    # Every Settings store change, as {key: new value}.
    settings_changed = Signal(dict)

    use_result_cache_lookup = _setting("use_result_cache_lookup")
    result_cache_compression = _setting("result_cache_compression")
    perf_downsample_enabled = _setting("perf_downsample_enabled")
    perf_auto_mode_active = _setting("perf_auto_mode_active")
    perf_manual_factor = _setting("perf_manual_factor")
    perf_render_screen_only = _setting("perf_render_screen_only")
    global_unit_acceleration = _setting("global_unit_acceleration")
    global_unit_pressure = _setting("global_unit_pressure")
    global_unit_voltage = _setting("global_unit_voltage")
    global_unit_speed = _setting("global_unit_speed")
    highlight_other_opacity = _setting("highlight_other_opacity")
    theme = _setting("theme")
    graph_theme = _setting("graph_theme")

    def __init__(self):
        super().__init__()
        # Central logging hook
        self.logger_callback = None

        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_ROOT)

        # Kept separate from self.settings because units, cache compression and
        # other application-wide preferences are conceptually distinct from
        # window geometry / layout state, even though both are QSettings today.
        self.shared_settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_SHARED)
        # The Settings window's application values: read and written only here.
        self.settings_store = SettingsStore(_QSettingsStorage(self.shared_settings))
        self.settings_store.subscribe(self.settings_changed.emit)

        # There is always a project. Until the user saves one it is Untitled and
        # has no file, which is enough to browse data and tune an FFT against --
        # a path is only demanded by actions that record a decision (see
        # ProjectSession.ensure_saved).
        self.project_session = ProjectSession()

        # The folder the user last pointed the browser at. It seeds file dialogs
        # and is what a restart restores, but it is no longer what defines the
        # working set -- that is the pool below, which may hold several folders
        # at once.
        self.active_directory: Optional[str] = None

        # The Data Pool -- the working set of measurements and the merged
        # metadata schema over them. A module of its own (session/data_pool.py)
        # that knows nothing of Qt, QSettings or the session role; the shell
        # holds it and turns its IntegrateResult into last-viewed-folder moves,
        # startup-pointer writes and log lines (see integrate_scanned_directory).
        self.pool = DataPool(self.project_session)

        self.current_analysis_mode: str = "project"

        # The ribbon writes its current DTO here whenever a control changes (see
        # each tab's _push_dsp_config); Workspace and the drop router read
        # from here instead of reaching into ribbon widgets directly. That is what
        # lets both be exercised in a test with a plain AppContext and no ribbon,
        # or any other GUI object, behind it.
        self.spectrum_settings = SpectrumConfig()
        self.spectrogram_settings = SpectrogramConfig()
        self.order_tracking_settings = OrderTrackingConfig()
        self.overall_level_settings = OverallLevelConfig()
        # The Order Tracking tab's "Overall Level + Residual" checkbox (ADR
        # §1.141): kept beside order_tracking_settings, not in it, because that
        # config is an order cut's cache identity.
        self.order_tracking_overall_level: bool = False
        self.band_rms_cursors_enabled: bool = False
        # The hover Cursor (Tools tab, `C`): one switch for every graph, not project state.
        # Remembered across starts (shared_settings); the Cursor defaults to on.
        self.cursor_enabled: bool = self._load_tool_flag("cursor_enabled", True)
        self.highlight_enabled: bool = self._load_tool_flag("highlight_enabled", False)
        self.cursor_pinned: bool = self._load_tool_flag("cursor_pinned", False)
        self.cursor_config: CursorConfig = self._load_cursor_config()
        # Default False = current behaviour: a dropped comparison curve is
        # computed with the ribbon's current SpectrumConfig. True = it instead
        # inherits compute_spec off the dock's base trace, so a dropped curve
        # matches what is already on screen (session_persistence PLAN.md §4
        # R1). A working habit, not a graph property -- QSettings like other
        # ribbon toggles, never written to the project (see
        # execute_channel_drop_processing).
        self.new_curve_config_from_trace: bool = False

    def log(self, message: str):
        if self.logger_callback:
            self.logger_callback(message)

    def unit_preferences(self) -> UnitPreferences:
        """Snapshot of the global display units, for code that must not depend on AppContext itself.
        The X axis unit is the open project's (issue #459), the other four this application's."""
        return UnitPreferences(
            acceleration=self.global_unit_acceleration,
            pressure=self.global_unit_pressure,
            voltage=self.global_unit_voltage,
            speed=self.global_unit_speed,
            x_axis_unit=self.project_session.x_axis_unit,
        )

    # ---- recent projects ----------------------------------------------

    def recent_projects_detailed(self) -> List[RecentProject]:
        """
        Every remembered project, most recent first -- including ones whose file
        is no longer on disk, so the Welcome screen can show them greyed out.

        Stored as a JSON string rather than a QSettings list: a one-element list
        comes back from the registry as a bare string, which would silently turn
        a single recent project into a list of its characters.
        """
        return parse_recent(self.shared_settings.value("recent_projects", ""))

    def recent_projects(self) -> List[str]:
        """
        Paths of remembered projects, most recent first.

        Existence is deliberately not checked here on the GUI thread -- doing so
        blocks on unreachable network shares (issue #412). Views verify existence
        asynchronously instead.
        """
        return [e.path for e in self.recent_projects_detailed()]

    def remember_project(self, project_path: str) -> None:
        """Moves a project to the front of the recent list, stamped with the current time."""
        if not project_path:
            return
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        updated = _promote_recent(self.recent_projects_detailed(), project_path, now)
        self.shared_settings.setValue("recent_projects", serialize_recent(updated))

    def _load_tool_flag(self, key: str, default: bool) -> bool:
        return bool(self.shared_settings.value(key, default, type=bool))

    def remember_tool_flag(self, key: str, value: bool) -> None:
        """Keeps a Tools tab switch (Cursor / Highlight / Pin) for every later start."""
        self.shared_settings.setValue(key, bool(value))

    def _load_cursor_config(self) -> CursorConfig:
        """Cursor Box fields from shared settings; defaults if absent or unreadable."""
        try:
            return CursorConfig.from_dict(json.loads(str(self.shared_settings.value("cursor_config", ""))))
        except (ValueError, AttributeError):
            return CursorConfig()

    def set_cursor_config(self, config: CursorConfig) -> None:
        """Keeps the Cursor Box fields for every project and every later start."""
        self.cursor_config = config
        self.shared_settings.setValue("cursor_config", json.dumps(config.to_dict()))

    @property
    def result_content_curve_limit(self) -> int:
        """How many curves "Load Result Sets…" reads without asking first."""
        return int(self.shared_settings.value(
            _RESULT_CONTENT_CURVE_LIMIT_KEY, _DEFAULT_RESULT_CONTENT_CURVE_LIMIT))

    def clear_stored_settings(self) -> None:
        """Wipe both QSettings groups and return every setting to its default (Reset All Settings).

        Everything in both groups is app state or user preference -- nothing
        external -- so a full clear is the honest whitelist; the store's reset
        then reports every setting, so nothing keeps showing a stale value.
        """
        self.settings.clear()
        self.shared_settings.clear()
        self.settings_store.reset()

    def initialize_session_directory(self):
        """
        Restores the folder the window was last pointed at.

        Only the path is restored here. Loading used to be attempted a second
        time from this method, duplicating the scan logic with a different list
        of file extensions -- and its result was overwritten moments later by the
        startup action, which loads the folder anyway.
        """
        # Untitled scan caches accumulate in a shared temp area; clear the old
        # ones once per primary-window start.
        prune_untitled_scan_cache()

        saved_dir = self.settings.value("primary_startup_data_directory", None)
        if saved_dir and os.path.exists(str(saved_dir)):
            self.active_directory = str(saved_dir)

    # ---- the data pool ----------------------------------------------------
    #
    # Data Pool state and rules live in session/data_pool.py; callers reach
    # it as app_context.pool. The three methods below stay on the shell because
    # each does work the pool deliberately does not -- the active_directory
    # move, the startup pointer, the log lines.

    def apply_integrate_effects(self, result: IntegrateResult) -> None:
        """Apply shell effects reported by a Data Pool integration."""
        if result.unit_corrections:
            self.log(f"PROJECT: Applied {result.unit_corrections} unit correction(s) from the project.")
        if result.metadata_synced:
            self.log(f"PROJECT: Synced metadata for {result.metadata_synced} source(s).")
        if result.is_new_folder:
            self.active_directory = result.stored_path
            self.settings.setValue("primary_startup_data_directory", result.stored_path)

    def integrate_scanned_directory(self, directory_path: str, runs_list, schema_master: dict,
                                    only_files=None, admit_unknown: bool = False,
                                    *, index: DirectoryIndex) -> int:
        """
        Folds a scanned folder into the pool and applies the shell-only effects.

        The pool does the bookkeeping and reports back an IntegrateResult; the
        shell turns that into the log lines, and -- only for a folder new to the
        pool -- the last-viewed-folder move and the startup pointer. A
        background re-scan of folders already pooled (project open, folder
        watcher) must not move either. Returns the runs gained.

        Not how a folder gets into the pool from the window any more: the
        ingest is orchestration.data_pool.PoolIngestUseCase (#208), which calls
        the pool itself and hands the IntegrateResult back for the GUI to run
        through apply_integrate_effects. What is left here is the same two
        steps composed for a caller that has already scanned and is not running
        a job -- and the seam the §1.24 rules above are tested against.
        """
        result = self.pool.integrate_scanned_directory(
            directory_path, runs_list, schema_master, only_files, admit_unknown,
            index=index
        )
        self.apply_integrate_effects(result)
        return result.gained

    def add_pool_directory(self, directory_path: str, only_files=None,
                           admit_unknown: bool = False) -> int:
        """Scans a folder and adds it to the pool, keeping what is already there."""
        result = self.pool.add_pool_directory(directory_path, only_files, admit_unknown)
        self.apply_integrate_effects(result)
        return result.gained

    def restore_pool_from_project(self) -> int:
        """
        Fills the pool from the project, then falls back active_directory onto a
        recovered folder only when the browser has nothing to point at --
        active_directory is the last-viewed folder, not a function of pool order.
        """
        restored = self.pool.restore_pool_from_project()
        if not self.active_directory and restored:
            self.active_directory = restored[0]
        return len(self.pool.loaded_runs)
