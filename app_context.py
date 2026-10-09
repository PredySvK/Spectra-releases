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
from PySide6.QtCore import QSettings

from session.project import ProjectSession
from io_modules.project_store import DirectoryIndex, prune_untitled_scan_cache
from session.data_pool import DataPool, IntegrateResult
from core.app_metadata import SETTINGS_ORGANIZATION, SETTINGS_ROOT, SETTINGS_SHARED
from core.cursor_config import CursorConfig
from core.graphic_configs import GRAPHIC_SYSTEM_DEFAULTS
from core.units import UnitPreferences
from core.dsp_configs import SpectrumConfig, SpectrogramConfig, OrderTrackingConfig, OverallLevelConfig
from core.recent_projects import (
    RecentProject, parse_recent, serialize_recent, promote as _promote_recent,
)


class AppContext:
    def __init__(self):
        # Central logging hook
        self.logger_callback = None

        self.settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_ROOT)

        # Kept separate from self.settings because units, cache compression and
        # other application-wide preferences are conceptually distinct from
        # window geometry / layout state, even though both are QSettings today.
        self.shared_settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_SHARED)

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

        # Unit and performance preferences live in shared_settings rather than
        # self.settings to keep them conceptually separate from window geometry
        # and layout state.
        self.global_unit_acceleration: str = str(self.shared_settings.value("global_unit_acceleration", "g"))
        self.global_unit_pressure: str = str(self.shared_settings.value("global_unit_pressure", "Pa"))
        self.global_unit_voltage: str = str(self.shared_settings.value("global_unit_voltage", "V"))
        self.global_unit_speed: str = str(self.shared_settings.value("global_unit_speed", "rpm"))

        # How result-cache shards are stored: "" (none), "lzf" or "gzip".
        # Off by default -- the fastest write, and h5py reads a compressed file
        # transparently, so the setting only ever affects what is written next;
        # existing result sets stay readable whatever it is set to.
        compression = str(self.shared_settings.value("result_cache_compression", "") or "")
        self.result_cache_compression: str = compression if compression in ("lzf", "gzip") else ""

        # Global toggle for using cached results during spectrum/order lookup.
        # True by default; stored in shared_settings so it applies application-wide.
        self.use_result_cache_lookup: bool = bool(self.shared_settings.value(
            "use_result_cache_lookup", True, type=bool
        ))

        for config_key, (default_value, data_type) in GRAPHIC_SYSTEM_DEFAULTS.items():
            loaded_value = self.shared_settings.value(config_key, default_value, type=data_type)
            setattr(self, config_key, loaded_value)

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
        self.highlight_other_opacity: int = int(self.shared_settings.value("highlight_other_opacity", 25, type=int))
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

    def update_graph_settings(self, downsample_enabled: bool, auto_mode_active: bool, manual_factor: int,
                              render_screen_only: bool):
        self.perf_downsample_enabled = downsample_enabled
        self.perf_auto_mode_active = auto_mode_active
        self.perf_manual_factor = manual_factor
        self.perf_render_screen_only = render_screen_only

        self.shared_settings.setValue("perf_downsample_enabled", downsample_enabled)
        self.shared_settings.setValue("perf_auto_mode_active", auto_mode_active)
        self.shared_settings.setValue("perf_manual_factor", manual_factor)
        self.shared_settings.setValue("perf_render_screen_only", render_screen_only)

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

    def set_highlight_other_opacity(self, percent: int) -> None:
        """Keeps how visible the non-highlighted curves stay (0-100 %) for every later start."""
        self.highlight_other_opacity = max(0, min(100, int(percent)))
        self.shared_settings.setValue("highlight_other_opacity", self.highlight_other_opacity)

    def _load_cursor_config(self) -> CursorConfig:
        """Cursor Box fields from shared settings (ADR §1.149); defaults if absent or unreadable."""
        try:
            return CursorConfig.from_dict(json.loads(str(self.shared_settings.value("cursor_config", ""))))
        except (ValueError, AttributeError):
            return CursorConfig()

    def set_cursor_config(self, config: CursorConfig) -> None:
        """Keeps the Cursor Box fields for every project and every later start."""
        self.cursor_config = config
        self.shared_settings.setValue("cursor_config", json.dumps(config.to_dict()))

    def update_unit_setting(self, attr_name: str, unit_value: str):
        if hasattr(self, attr_name):
            setattr(self, attr_name, unit_value)
            self.shared_settings.setValue(attr_name, unit_value)

    def initialize_session_directory(self):
        """
        Restores the folder the window was last pointed at.

        Only the path is restored here. Loading used to be attempted a second
        time from this method, duplicating the scan logic with a different list
        of file extensions -- and its result was overwritten moments later by the
        startup action, which loads the folder anyway.
        """
        # Untitled scan caches accumulate in a shared temp area; clear the old
        # ones once per primary-window start (ADR §1.22).
        prune_untitled_scan_cache()

        saved_dir = self.settings.value("primary_startup_data_directory", None)
        if saved_dir and os.path.exists(str(saved_dir)):
            self.active_directory = str(saved_dir)

    # ---- the data pool ----------------------------------------------------
    #
    # Data Pool state and rules live in session/data_pool.py; callers reach
    # it as app_context.pool. The three methods below stay on the shell because
    # each does work the pool deliberately does not -- the active_directory
    # move, the startup pointer, the log lines (ADR §1.52).

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
        watcher) must not move either (ADR §1.24). Returns the runs gained.

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
