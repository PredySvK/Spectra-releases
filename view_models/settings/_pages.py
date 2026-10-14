"""The Settings page tree as data: adding a page is adding a SettingsPage here."""

from dataclasses import dataclass

from core.axis_projections import X_AXIS_HZ, X_AXIS_NATIVE, X_AXIS_RPM
from core.units import CANONICAL_UNIT_GROUPS


@dataclass(frozen=True)
class SettingsField:
    """One draft field. ``key`` is the value's AppContext attribute / QSettings key."""

    key: str
    label: str
    kind: str  # "choice", "flag", "integer" or immediate "toggle"
    choices: tuple[tuple[str, object], ...] = ()
    description: str = ""
    group: str = ""  # heading above the field on the page; "" = none
    note: str = ""  # shown under the field, not only as a tooltip
    minimum: int = 0
    maximum: int = 100
    suffix: str = ""
    enabled_when: tuple[tuple[str, object], ...] = ()
    project: bool = False  # lives in the open project, not in the application settings


@dataclass(frozen=True)
class SettingsPage:
    """One page; ``path`` is its place in the tree, section names first."""

    page_id: str
    path: tuple[str, ...]
    fields: tuple[SettingsField, ...]


def _unit_field(key: str, label: str, domain: int) -> SettingsField:
    units = CANONICAL_UNIT_GROUPS[domain]
    return SettingsField(key, label, "choice", tuple((unit, unit) for unit in units), group="Application")


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
            _unit_field("global_unit_pressure", "Pressure", 1),
            _unit_field("global_unit_voltage", "Voltage", 2),
            _unit_field("global_unit_speed", "Speed", 3),
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
    ),
    SettingsPage(
        "graphic/global",
        ("Graphic", "Global"),
        (
            SettingsField(
                "theme", "Theme", "choice",
                (("Dark", "dark"), ("Light", "light")),
                description="Appearance of the whole application.",
                note="Applies after restart.",
            ),
            SettingsField(
                "graph_theme", "Graph theme", "choice",
                (("Follow theme", "follow"), ("Dark", "dark"), ("Light", "light")),
                description="Appearance of the graph area, independent of the application theme.",
                note="Applies after restart.",
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
                minimum=2, maximum=10000,
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
        "maintenance",
        ("Maintenance",),
        (SettingsField("check_for_updates_on_startup", "Check for updates on startup", "flag"),),
    ),
    SettingsPage("about", ("About Spectra",), ()),
)


SETTINGS_PROJECT_KEYS = frozenset(
    field.key for page in SETTINGS_PAGES for field in page.fields if field.project)


def resolve_settings_page(page_id: str) -> SettingsPage:
    """The page with ``page_id``, or the first page when it no longer exists."""
    return next((page for page in SETTINGS_PAGES if page.page_id == page_id), SETTINGS_PAGES[0])


def build_settings_breadcrumb(page: SettingsPage) -> str:
    return " › ".join(page.path)


SETTINGS_IMMEDIATE_KEYS = frozenset(
    field.key for page in SETTINGS_PAGES for field in page.fields if field.kind == "toggle")
