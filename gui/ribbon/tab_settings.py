# gui/ribbon/tab_settings.py
"""
Application settings ribbon tab.

Groups: Defaults (graph + units), Panels (dock toggles, two columns), View (X axis
unit), Cache, Startup, Update, Benchmark, Reset, Help.
"""

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core.axis_projections import X_AXIS_HZ, X_AXIS_NATIVE, X_AXIS_RPM
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_ribbon_button, vertical_separator

# The global X axis unit: the label the user picks, and the value it stores.
X_AXIS_UNIT_CHOICES = [
    ("Native", X_AXIS_NATIVE),
    ("Hz", X_AXIS_HZ),
    ("RPM", X_AXIS_RPM),
]

# Result-cache compression: the label the user picks, and the h5py filter name
# it maps to ("" = none). Off by default -- see AppContext.result_cache_compression.
CACHE_COMPRESSION_CHOICES = [
    ("None (fastest)", ""),
    ("lzf (fast)", "lzf"),
    ("gzip (smallest)", "gzip"),
]


class TabSettings(QWidget):
    """Application settings and layout configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(8)

        # -- Defaults --
        self.btn_graph_settings = make_ribbon_button(
            "Graph\nDefaults", "line-chart", kind="primary", big=True,
            tooltip="Default appearance and throughput profile for new graphs")
        self.btn_global_units = make_ribbon_button(
            "Unit\nSettings", "ruler", kind="commit", big=True,
            tooltip="Global engineering unit conversions")
        defaults = RibbonGroup("Defaults")
        defaults.add(self.btn_graph_settings)
        defaults.add(self.btn_global_units)
        layout.addWidget(defaults)
        layout.addWidget(vertical_separator())

        # -- Panels --
        self.btn_toggle_explorer = make_ribbon_button(
            "Explorer", "panel-left", tooltip="Show or hide the Explorer dock")
        self.btn_toggle_filters = make_ribbon_button(
            "Filters", "filter", tooltip="Show or hide the Filters dock")
        self.btn_toggle_log = make_ribbon_button(
            "System Log", "file-text", tooltip="Show or hide the System Log tab")
        self.btn_toggle_jobs = make_ribbon_button(
            "Jobs", "activity", tooltip="Show or hide the Jobs tab")
        self.btn_toggle_evaluation = make_ribbon_button(
            "Evaluation", "list", tooltip="Show or hide the Evaluation tab")
        panels = RibbonGroup("Panels")
        panels.add_column(self.btn_toggle_explorer, self.btn_toggle_filters, self.btn_toggle_log, spacing=4)
        panels.add_column(self.btn_toggle_jobs, self.btn_toggle_evaluation, spacing=4)
        layout.addWidget(panels)
        layout.addWidget(vertical_separator())

        # -- View --
        # The open project's X axis unit (issue #459), stored with the project
        # rather than in QSettings -- see gui/handlers/window_settings.py.
        self.combo_x_axis_unit = QComboBox()
        for text, value in X_AXIS_UNIT_CHOICES:
            self.combo_x_axis_unit.addItem(text, value)
        self.combo_x_axis_unit.setToolTip(
            "Unit of every frequency and speed X axis: Native keeps each graph in its own "
            "(spectra in Hz, order cuts in RPM); Hz or RPM shows all of them in one")
        view_column = QVBoxLayout()
        view_column.setSpacing(2)
        view_column.addWidget(QLabel("X axis unit"))
        view_column.addWidget(self.combo_x_axis_unit)
        view_column.addStretch()
        view = RibbonGroup("View", tooltip="How graphs are shown")
        view.add(view_column)
        layout.addWidget(view)
        layout.addWidget(vertical_separator())

        # -- Cache --
        # Only ever affects what is written next: h5py decompresses
        # transparently, so result sets already on disk stay readable (ADR §1.21).
        self.combo_cache_compression = QComboBox()
        for text, value in CACHE_COMPRESSION_CHOICES:
            self.combo_cache_compression.addItem(text, value)
        self.cb_use_result_cache_lookup = QCheckBox("Use cached results")
        cache_column = QVBoxLayout()
        cache_column.setSpacing(2)
        cache_column.addWidget(QLabel("Result cache compression"))
        cache_column.addWidget(self.combo_cache_compression)
        cache_column.addWidget(self.cb_use_result_cache_lookup)
        cache_column.addStretch()
        cache = RibbonGroup("Cache", tooltip="Result cache behavior and compression")
        cache.add(cache_column)
        layout.addWidget(cache)
        layout.addWidget(vertical_separator())

        # -- Startup --
        # Wired to shared_settings in MainWindowFrame.init_ui; read back by
        # ProjectDocumentHandler.run_startup on the next launch.
        self.cb_open_last_project = QCheckBox("Open last project on startup")
        startup = RibbonGroup("Startup")
        startup.add_column(self.cb_open_last_project)
        layout.addWidget(startup)
        layout.addWidget(vertical_separator())

        # -- Update --
        self.btn_check_updates = make_ribbon_button(
            "Check for Updates", "download", tooltip="Check for a newer Spectra release")
        update = RibbonGroup("Update")
        update.add(self.btn_check_updates)
        layout.addWidget(update)
        layout.addWidget(vertical_separator())

        # -- Benchmark --
        self.btn_run_benchmark = make_ribbon_button(
            "Run Benchmark…", "activity", tooltip="Time the analyses on this machine and show the report")
        benchmark = RibbonGroup("Benchmark")
        benchmark.add(self.btn_run_benchmark)
        layout.addWidget(benchmark)
        layout.addWidget(vertical_separator())

        # -- Reset --
        # Two, not one: "Reset Layout" is the everyday dock-tidy and stays cheap
        # to click; "Reset All Settings" forgets units, DSP defaults and recent
        # projects too. See gui/handlers/window_settings.py.
        self.btn_reset_layout = make_ribbon_button(
            "Reset Layout", "layout", kind="danger", tooltip="Restore the default dock layout")
        self.btn_reset_all_settings = make_ribbon_button(
            "Reset All Settings", "trash", kind="danger",
            tooltip="Forget layout, units, DSP defaults and recent projects")
        reset = RibbonGroup("Reset")
        reset.add_column(self.btn_reset_layout, self.btn_reset_all_settings, spacing=4)
        layout.addWidget(reset)

        build_tab_layout(self, layout, "settings")

    def set_x_axis_unit(self, value: str) -> None:
        """Show ``value`` without emitting a change -- a project swap is not a user pick."""
        index = self.combo_x_axis_unit.findData(value)
        self.combo_x_axis_unit.blockSignals(True)
        self.combo_x_axis_unit.setCurrentIndex(max(0, index))
        self.combo_x_axis_unit.blockSignals(False)

    def x_axis_unit(self) -> str:
        return self.combo_x_axis_unit.currentData() or X_AXIS_NATIVE

    def set_cache_compression(self, value: str) -> None:
        index = self.combo_cache_compression.findData(value or "")
        self.combo_cache_compression.setCurrentIndex(max(0, index))

    def cache_compression(self) -> str:
        return self.combo_cache_compression.currentData() or ""

    def set_use_result_cache_lookup(self, enabled: bool) -> None:
        self.cb_use_result_cache_lookup.setChecked(bool(enabled))

    def use_result_cache_lookup(self) -> bool:
        return self.cb_use_result_cache_lookup.isChecked()
