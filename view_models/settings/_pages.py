"""The Settings page tree as data: adding a page is adding a SettingsPage here."""

from dataclasses import dataclass

from core.axis_projections import X_AXIS_HZ, X_AXIS_NATIVE, X_AXIS_RPM
from core.settings import DECIMALS_CHOICES, SETTING_DEFINITIONS
from core.units import DB_REFERENCE_UNITS, DISPLAY_BASE_UNIT_GROUPS
from view_models.display_prefix import resolve_display_prefix_setting_choices


@dataclass(frozen=True)
class SettingsField:
    """One draft field. ``key`` is a core.settings key, a panel toggle or a project value.

    A setting that applies after restart says so in its note on its own, and an
    "integer" field takes its range from its core.settings key.
    """

    key: str
    label: str
    # "choice", "flag", "integer", non-negative "number", "positive" number, positive
    # "scientific" or immediate "toggle"
    kind: str
    choices: tuple[tuple[str, object], ...] = ()
    description: str = ""
    group: str = ""  # heading above the field on the page; "" = none
    note: str = ""  # shown under the field, not only as a tooltip
    minimum: int = 0
    maximum: int = 100
    suffix: str = ""
    enabled_when: tuple[tuple[str, object], ...] = ()
    project: bool = False  # lives in the open project, not in the application settings

    def __post_init__(self):
        definition = SETTING_DEFINITIONS.get(self.key)
        if definition is not None and definition.applies_after_restart and not self.note:
            object.__setattr__(self, "note", "Applies after restart.")
        if self.kind == "integer":
            if definition is None or definition.minimum is None:
                raise ValueError(f"integer field {self.key!r} is not an integer setting")
            object.__setattr__(self, "minimum", definition.minimum)
            object.__setattr__(self, "maximum", definition.maximum)


@dataclass(frozen=True)
class UnitsRow:
    """One row of the Units page: a quantity with the keys of its editors.

    ``unit_key`` / ``reference_key`` are None where the quantity has no unit choice
    or no dB reference. ``preview_unit`` is the fixed unit of a row without
    ``unit_key`` (Hz, s); with ``unit_key`` the preview takes the unit from the draft.
    """

    label: str
    prefix_key: str
    decimals_key: str
    unit_key: str | None = None
    reference_key: str | None = None
    preview_unit: str = ""

    @property
    def keys(self) -> tuple[str, ...]:
        """Every field key the row shows."""
        return tuple(k for k in (self.unit_key, self.prefix_key, self.decimals_key, self.reference_key) if k)


@dataclass(frozen=True)
class SettingsPage:
    """One page; ``path`` is its place in the tree, section names first.

    ``rows`` are fields drawn as table rows above the rest of ``fields``.
    """

    page_id: str
    path: tuple[str, ...]
    fields: tuple[SettingsField, ...]
    rows: tuple[UnitsRow, ...] = ()


def _unit_field(key: str, label: str, domain: int) -> SettingsField:
    units = DISPLAY_BASE_UNIT_GROUPS[domain]
    return SettingsField(key, label, "choice", tuple((unit, unit) for unit in units), group="Application")


def _prefix_field(key: str, label: str, default_unit: str) -> SettingsField:
    choices = resolve_display_prefix_setting_choices(default_unit)
    return SettingsField(key, label, "choice", choices, group="Application")


def _db_reference_field(quantity: str, label: str) -> SettingsField:
    unit = {"m/s2": "m/s²"}.get(DB_REFERENCE_UNITS[quantity], DB_REFERENCE_UNITS[quantity])
    return SettingsField(
        f"db_reference_{quantity}", f"{label} dB reference", "scientific",
        description=f"The {label.lower()} that is 0 dB wherever a value is shown in dB, "
                    f"in {unit} whatever the unit chosen.",
        group="Application", suffix=unit)


def _decimals_field(key: str, label: str) -> SettingsField:
    choices = tuple((c.capitalize() if c == "auto" else c, c) for c in DECIMALS_CHOICES)
    return SettingsField(key, label, "choice", choices, group="Application")


_UNITS_ROWS: tuple[UnitsRow, ...] = (
    UnitsRow("Acceleration", "prefix_acceleration", "decimals_acceleration",
             "global_unit_acceleration", "db_reference_acceleration"),
    UnitsRow("Pressure", "prefix_pressure", "decimals_pressure",
             "global_unit_pressure", "db_reference_pressure"),
    UnitsRow("Voltage", "prefix_voltage", "decimals_voltage",
             "global_unit_voltage", "db_reference_voltage"),
    UnitsRow("Speed", "prefix_speed", "decimals_speed", "global_unit_speed"),
    UnitsRow("Frequency", "prefix_frequency", "decimals_frequency", preview_unit="Hz"),
    UnitsRow("Time", "prefix_time", "decimals_time", preview_unit="s"),
)


SETTINGS_PAGES: tuple[SettingsPage, ...] = (
    SettingsPage(
        "layout",
        ("Layout",),
        (
            SettingsField("panel_explorer", "Explorer", "toggle", group="Panels"),
            SettingsField("panel_filters", "Filters", "toggle", group="Panels"),
            SettingsField("panel_log", "System Log", "toggle", group="Panels"),
            SettingsField("panel_jobs", "Jobs", "toggle", group="Panels"),
            SettingsField("panel_evaluation", "Evaluation", "toggle", group="Panels"),
            SettingsField("open_last_project_on_startup", "Open last project on startup", "flag", group="Startup"),
        ),
    ),
    SettingsPage(
        "units",
        ("Units",),
        (
            _unit_field("global_unit_acceleration", "Acceleration", 0),
            _prefix_field("prefix_acceleration", "Acceleration prefix", "g"),
            _decimals_field("decimals_acceleration", "Acceleration decimals"),
            _db_reference_field("acceleration", "Acceleration"),
            _unit_field("global_unit_pressure", "Pressure", 1),
            _prefix_field("prefix_pressure", "Pressure prefix", "Pa"),
            _decimals_field("decimals_pressure", "Pressure decimals"),
            _db_reference_field("pressure", "Pressure"),
            _unit_field("global_unit_voltage", "Voltage", 2),
            _prefix_field("prefix_voltage", "Voltage prefix", "V"),
            _decimals_field("decimals_voltage", "Voltage decimals"),
            _db_reference_field("voltage", "Voltage"),
            _unit_field("global_unit_speed", "Speed", 3),
            _prefix_field("prefix_speed", "Speed prefix", "rpm"),
            _decimals_field("decimals_speed", "Speed decimals"),
            _prefix_field("prefix_frequency", "Frequency", "Hz"),
            _decimals_field("decimals_frequency", "Frequency decimals"),
            _prefix_field("prefix_time", "Time", "s"),
            _decimals_field("decimals_time", "Time decimals"),
            SettingsField(
                "x_axis_unit",
                "X axis unit",
                "choice",
                (("Native", X_AXIS_NATIVE), ("Hz", X_AXIS_HZ), ("RPM", X_AXIS_RPM)),
                "Unit of every frequency and speed X axis: Native keeps each graph in its own "
                "(spectra in Hz, order cuts in RPM); Hz or RPM shows all of them in one.",
                group="This project",
                note="Saved with the project.",
                project=True,
            ),
        ),
        _UNITS_ROWS,
    ),
    SettingsPage(
        "graphic/global",
        ("Graphic", "Global"),
        (
            SettingsField(
                "theme", "Theme", "choice",
                (("Dark", "dark"), ("Light", "light")),
                description="Appearance of the whole application.",
            ),
            SettingsField(
                "graph_theme", "Graph theme", "choice",
                (("Follow theme", "follow"), ("Dark", "dark"), ("Light", "light")),
                description="Appearance of the graph area, independent of the application theme.",
            ),
        ),
    ),
    SettingsPage(
        "graphic/graph_rendering",
        ("Graphic", "Graph Rendering"),
        (
            SettingsField("perf_downsample_enabled", "Enable downsampling", "flag"),
            SettingsField(
                "perf_auto_mode_active", "Downsampling mode", "choice",
                (("Automatic (matches monitor width)", True), ("Manual factor", False)),
                enabled_when=(("perf_downsample_enabled", True),),
            ),
            SettingsField(
                "perf_manual_factor", "Manual downsampling factor", "integer",
                enabled_when=(("perf_downsample_enabled", True), ("perf_auto_mode_active", False)),
            ),
            SettingsField("perf_render_screen_only", "Render screen only", "flag",
                          description="Render only the data inside the visible graph area."),
            SettingsField("highlight_other_opacity", "Other curves opacity", "integer", suffix=" %",
                          description="Visibility of the other curves while Highlight is active."),
        ),
    ),
    SettingsPage(
        "computation/result_cache",
        ("Computation", "Result Cache"),
        (
            # Only ever affects what is written next: h5py decompresses
            # transparently, so result sets already on disk stay readable.
            SettingsField(
                "result_cache_compression",
                "Result cache compression",
                "choice",
                (("None (fastest)", ""), ("lzf (fast)", "lzf"), ("gzip (smallest)", "gzip")),
                "Compression of result sets written from now on; existing ones stay readable.",
            ),
            SettingsField(
                "use_result_cache_lookup",
                "Use cached results",
                "flag",
                description="Reuse a result already in the cache instead of computing it again.",
            ),
        ),
    ),
    SettingsPage(
        "computation/dsp",
        ("Computation", "DSP"),
        (
            SettingsField(
                "tacho_hampel_filter",
                "Hampel filter",
                "flag",
                description="Replaces tacho spikes and dropouts before an RPM Tracked calculation "
                            "places its blocks: a sample further than the threshold from the median "
                            "of its 11 neighbours. Off = only missing samples are filled.",
                group="Tacho cleaning",
            ),
            SettingsField(
                "tacho_hampel_sigma",
                "Hampel threshold [σ]",
                "positive",
                description="How far from its neighbours' median a sample must lie to be replaced, "
                            "in standard deviations of the tacho's own noise. Small values (about 3) "
                            "replace plain noise too.",
                group="Tacho cleaning",
                enabled_when=(("tacho_hampel_filter", True),),
            ),
            SettingsField(
                "tacho_smoothing_ms",
                "Tacho smoothing window [ms]",
                "number",
                description="Moving average the tacho is smoothed with after the Hampel filter; "
                            "0 = no smoothing.",
                group="Tacho cleaning",
                note="Applies from the next RPM Tracked calculation.",
            ),
        ),
    ),
    SettingsPage(
        "maintenance",
        ("Maintenance",),
        (SettingsField("check_for_updates_on_startup", "Check for updates on startup", "flag"),),
    ),
    SettingsPage("about", ("About Spectra",), ()),
)


SETTINGS_FIELD_KEYS = frozenset(field.key for page in SETTINGS_PAGES for field in page.fields)
"""Every key the window shows. The Tools tab switches are settings too, but not among them."""

SETTINGS_PROJECT_KEYS = frozenset(
    field.key for page in SETTINGS_PAGES for field in page.fields if field.project)


def resolve_settings_page(page_id: str) -> SettingsPage:
    """The page with ``page_id``, or the first page when it no longer exists."""
    return next((page for page in SETTINGS_PAGES if page.page_id == page_id), SETTINGS_PAGES[0])


def build_settings_breadcrumb(page: SettingsPage) -> str:
    return " › ".join(page.path)


SETTINGS_IMMEDIATE_KEYS = frozenset(
    field.key for page in SETTINGS_PAGES for field in page.fields if field.kind == "toggle")
