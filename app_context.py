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
from dataclasses import replace
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from PySide6.QtCore import QObject, QSettings, Signal

from session.project import ProjectSession
from io_modules.project_store import prune_untitled_scan_cache
from io_modules.scan_cache import ScannedDirectory
from session.data_pool import Admission, DataPool, IntegrateResult
from session.settings import SettingsStore
from core.app_metadata import SETTINGS_ORGANIZATION, SETTINGS_ROOT, SETTINGS_SHARED
from core.legend_config import LegendConfig
from core.cursor_config import DEFAULT_CURSOR_FIELDS, DEFAULT_TRACK_TABLE_FIELDS, CursorConfig
from core.units import UnitPreferences
from core.dsp_configs import SpectrumConfig, SpectrogramConfig, OrderTrackingConfig, OverallLevelConfig
from core.tacho_cleaning import TACHO_CLEANING_PARAMS, TachoCleaning, resolve_tacho_cleaning
from core.recent_projects import (
    RecentProject, parse_recent, serialize_recent, promote as _promote_recent,
)


# QSettings key (shared_settings) for how many curves "Load Result Sets…" reads
# without asking first -- an application-wide tuning knob, not a per-window one.
# 500 is a starting point to revisit once a real project's limits are known.
# The data folder this window reopens on; Reset Layout removes it.
STARTUP_DIRECTORY_KEY = "primary_startup_data_directory"
_RESULT_CONTENT_CURVE_LIMIT_KEY = "result_content_curve_limit"
_DEFAULT_RESULT_CONTENT_CURVE_LIMIT = 500
# QSettings keys (shared_settings) of each tool's field list: one per tool, so the choices never mix.
_CURSOR_CONFIG_KEY = "cursor_config"
_TRACK_CURSOR_CONFIG_KEY = "track_cursor_config"
_LEGEND_DEFAULT_KEY = "legend_default_config"


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


def _tracked_config(name: str) -> property:
    """A tracked DSP config as the ribbon wrote it, handed out with the applied
    Tacho cleaning: it is a setting of the whole program, not of the ribbon
   , and every calculation reads its config here. Tacho cleaning
    values in an assigned config are therefore never the ones read back."""
    stored = f"_{name}"
    return property(
        lambda self: replace(getattr(self, stored), **self.tacho_cleaning.params),
        lambda self, config: setattr(self, stored, config),
        doc=f"The ribbon's '{name}' with the applied Tacho cleaning.")


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
    prefix_acceleration = _setting("prefix_acceleration")
    prefix_pressure = _setting("prefix_pressure")
    prefix_voltage = _setting("prefix_voltage")
    prefix_speed = _setting("prefix_speed")
    prefix_frequency = _setting("prefix_frequency")
    prefix_time = _setting("prefix_time")
    decimals_acceleration = _setting("decimals_acceleration")
    decimals_pressure = _setting("decimals_pressure")
    decimals_voltage = _setting("decimals_voltage")
    decimals_speed = _setting("decimals_speed")
    decimals_frequency = _setting("decimals_frequency")
    decimals_time = _setting("decimals_time")
    db_reference_acceleration = _setting("db_reference_acceleration")
    db_reference_pressure = _setting("db_reference_pressure")
    db_reference_voltage = _setting("db_reference_voltage")
    highlight_other_opacity = _setting("highlight_other_opacity")
    track_table_opacity = _setting("track_table_opacity")
    theme = _setting("theme")
    graph_theme = _setting("graph_theme")
    # The Tools tab switches: one for every graph, not project state.
    cursor_enabled = _setting("cursor_enabled")
    cursor_pinned = _setting("cursor_pinned")
    highlight_enabled = _setting("highlight_enabled")
    track_cursor_enabled = _setting("track_cursor_enabled")
    track_cursor_pinned = _setting("track_cursor_pinned")
    track_cursor_highlight_enabled = _setting("track_cursor_highlight_enabled")
    spectrogram_settings = _tracked_config("spectrogram_settings")
    order_tracking_settings = _tracked_config("order_tracking_settings")
    overall_level_settings = _tracked_config("overall_level_settings")

    @property
    def tacho_cleaning(self) -> TachoCleaning:
        """The applied Tacho cleaning; each value is the setting of its name."""
        return resolve_tacho_cleaning(
            {name: self.settings_store.value(name) for name in TACHO_CLEANING_PARAMS})

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
        self.cursor_config: CursorConfig = self._load_cursor_config()
        # The Track table's own columns (Track cursor Settings), apart from the Cursor Box's.
        self.track_cursor_config: CursorConfig = self._load_cursor_config(
            _TRACK_CURSOR_CONFIG_KEY, DEFAULT_TRACK_TABLE_FIELDS)
        # The legend every new graph starts with (Legend Settings' Default column, plot §1.296).
        self.legend_default_config: LegendConfig = self._load_legend_default()
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
            prefix_acceleration=self.prefix_acceleration,
            prefix_pressure=self.prefix_pressure,
            prefix_voltage=self.prefix_voltage,
            prefix_speed=self.prefix_speed,
            prefix_frequency=self.prefix_frequency,
            prefix_time=self.prefix_time,
            decimals_acceleration=self.decimals_acceleration,
            decimals_pressure=self.decimals_pressure,
            decimals_voltage=self.decimals_voltage,
            decimals_speed=self.decimals_speed,
            decimals_frequency=self.decimals_frequency,
            decimals_time=self.decimals_time,
            db_reference_acceleration=self.db_reference_acceleration,
            db_reference_pressure=self.db_reference_pressure,
            db_reference_voltage=self.db_reference_voltage,
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

    def _load_config(self, key: str, from_dict, default):
        """A tool's saved choice from shared settings; `default` if absent or unreadable."""
        try:
            return from_dict(json.loads(str(self.shared_settings.value(key, ""))))
        except (ValueError, AttributeError):
            return default

    def _remember_config(self, key: str, config) -> None:
        """Keeps a tool's choice under `key` for every project and every later start."""
        self.shared_settings.setValue(key, json.dumps(config.to_dict()))

    def _load_cursor_config(self, key: str = _CURSOR_CONFIG_KEY,
                            default_fields: Tuple[str, ...] = DEFAULT_CURSOR_FIELDS) -> CursorConfig:
        """A tool's field list from shared settings; `default_fields` if absent or unreadable.

        One path for every tool that keeps a config (`_load_config`): each has its own `key`,
        so their choices never mix. The Cursor Box's is `cursor_config`.
        """
        return self._load_config(key, lambda data: CursorConfig.from_dict(data, default_fields),
                                 CursorConfig(default_fields))

    def _load_legend_default(self) -> LegendConfig:
        """The Default legend from shared settings; the factory legend if absent or unreadable."""
        return self._load_config(_LEGEND_DEFAULT_KEY, LegendConfig.from_dict, LegendConfig())

    def set_legend_default_config(self, config: LegendConfig) -> None:
        """Keeps the legend every new graph starts with, for every project and every later start."""
        self.legend_default_config = config
        self._remember_config(_LEGEND_DEFAULT_KEY, config)

    def remember_cursor_config(self, key: str, config: CursorConfig) -> None:
        """Keeps a tool's field list under `key` for every project and every later start."""
        self._remember_config(key, config)

    def set_cursor_config(self, config: CursorConfig) -> None:
        """Keeps the Cursor Box fields for every project and every later start."""
        self.cursor_config = config
        self.remember_cursor_config(_CURSOR_CONFIG_KEY, config)

    def set_track_cursor_config(self, config: CursorConfig) -> None:
        """Keeps the Track table columns for every project and every later start."""
        self.track_cursor_config = config
        self.remember_cursor_config(_TRACK_CURSOR_CONFIG_KEY, config)

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

        saved_dir = self.settings.value(STARTUP_DIRECTORY_KEY, None)
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
            self.settings.setValue(STARTUP_DIRECTORY_KEY, result.stored_path)

    def integrate_scanned_directory(self, directory_path: str, scanned: ScannedDirectory, *,
                                    admission: Admission = Admission.folder()) -> int:
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
            directory_path, scanned, admission=admission)
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
