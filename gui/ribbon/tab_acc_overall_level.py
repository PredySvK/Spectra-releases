# =====================================================================
# FILE: gui/ribbon/tab_acc_overall_level.py
# =====================================================================
"""
Ribbon tab for the live Overall Level dock (band energy against speed or time, ADR §1.62).

Left to right: Refresh, then RibbonGroups -- Spectrum, Tacho Tracking (the
tab's TrackingSweepFields), View, Band, Options, Batch. View/Amplitude (issue #128) mirrors Order
Tracking's group: an instant redraw, no recompute.
Generates an OverallLevelConfig DTO for the DSP backend.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel

from core.dsp_configs import OverallLevelConfig
from gui.ribbon.ribbon_dsp_tab import RibbonDspTab
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_refresh_split_button, stack_buttons, vertical_separator
from gui.ribbon.save_section import ComputeResultSetButton
from view_models.analysis_kinds import ANALYSIS_OVERALL_LEVEL

_BAND_SPIN_WIDTH = 64  # whole Hz, no arrows: fits "200000" with room


class TabAccOverallLevel(RibbonDspTab):
    sig_display_settings_changed = Signal()
    _settings_attr = "overall_level_settings"
    _ready_widget_name = "cb_remove_dc"
    _analysis_kind = ANALYSIS_OVERALL_LEVEL

    def _on_display_setting_changed(self, _val: str = ""):
        self._emit_display_settings_changed()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(8)

        self.btn_recalculate = make_refresh_split_button("Recompute Overall Level for the active channel")
        self.save_section = ComputeResultSetButton(
            "oal", self.app_context,
            tooltip=("Compute this Overall Level for the selected channels across a folder "
                     "or a saved query, and save it as a result set."),
            parent=self,
        )
        layout.addWidget(stack_buttons(self.btn_recalculate, self.save_section))
        layout.addWidget(vertical_separator())

        # -- Spectrum --
        self.combo_fft_size = self._build_field_combo("fft_size")
        self.combo_window_type = self._build_field_combo("window_type")

        spectrum_group = RibbonGroup("Spectrum", tooltip="Block size and window of the underlying FFT")
        spectrum_group.add_fields([
            ("FFT Size", self.combo_fft_size), ("Window", self.combo_window_type),
        ])
        layout.addWidget(spectrum_group)
        layout.addWidget(vertical_separator())

        # -- Tacho Tracking --
        layout.addWidget(self._build_tracking_sweep("oal").group)
        layout.addWidget(vertical_separator())

        # -- View --
        self.combo_amplitude_mode = self._build_field_combo("amplitude_mode")
        self.combo_amplitude_mode.currentTextChanged.connect(self._on_display_setting_changed)

        view_group = RibbonGroup("View", tooltip="Display amplitude mode")
        view_group.add_fields([("Amplitude", self.combo_amplitude_mode)])
        layout.addWidget(view_group)
        layout.addWidget(vertical_separator())

        # -- Band -- built before wiring cross-widget signals (F max's
        # minimum depends on F min, its enabled state on Full Bandwidth), so
        # restoring saved settings does not fire a handler against a sibling
        # widget that does not exist yet.
        self.spin_f_min = QDoubleSpinBox()
        self.spin_f_min.setDecimals(0)
        self.spin_f_min.setRange(0.0, 100000.0)
        # F min is saved by its handler, after F max's minimum follows it.
        self._bind_field("f_start", self.spin_f_min, save_on_change=False)

        self.spin_f_max = QDoubleSpinBox()
        self.spin_f_max.setDecimals(0)
        self.spin_f_max.setRange(1.0, 200000.0)
        self._bind_field("f_stop", self.spin_f_max)

        self.cb_full_bandwidth = QCheckBox("Full Bandwidth")
        self._bind_field("full_bandwidth", self.cb_full_bandwidth)
        self._sync_dependent_widgets()

        self.spin_f_min.valueChanged.connect(self._on_f_min_changed)
        self.cb_full_bandwidth.toggled.connect(self._sync_dependent_widgets)

        band_group = RibbonGroup("Band", tooltip="Frequency band the Overall Level energy is integrated over")
        # Full Bandwidth on top: it is the switch that greys F max out.
        # F min and F max sit side by side under it, together as wide as the checkbox.
        band_grid = QGridLayout()
        band_grid.setSpacing(1)
        band_grid.setHorizontalSpacing(6)
        band_grid.addWidget(self.cb_full_bandwidth, 0, 0, 1, 2)
        for column, (text, spin) in enumerate((("F min [Hz]", self.spin_f_min),
                                               ("F max [Hz]", self.spin_f_max))):
            label = QLabel(text)
            label.setStyleSheet("color: palette(window-text); font-size: 11px;")
            spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            spin.setFixedWidth(_BAND_SPIN_WIDTH)
            band_grid.addWidget(label, 1, column)
            band_grid.addWidget(spin, 2, column)
        band_grid.setRowStretch(3, 1)
        band_group.add(band_grid)
        layout.addWidget(band_group)
        layout.addWidget(vertical_separator())

        # -- Options --
        self.cb_remove_dc = QCheckBox("Remove DC Offset")
        self._bind_field("remove_dc", self.cb_remove_dc)

        options_group = RibbonGroup("Options")
        options_group.add_column(self.cb_remove_dc)
        layout.addWidget(options_group)


        build_tab_layout(self, layout, "overall_level")

        self._push_dsp_config()

    def _sync_dependent_widgets(self, _checked: bool = False):
        self.spin_f_max.setMinimum(self.spin_f_min.value() + 1.0)
        self.spin_f_max.setEnabled(not self.cb_full_bandwidth.isChecked())

    def _on_f_min_changed(self, value: float):
        self.spin_f_max.setMinimum(value + 1.0)
        self._save_field("f_start", value)

    def reset_to_defaults(self) -> None:
        # Lowered first: F max's minimum still follows the old F min, and would
        # clamp the default F max (1000 Hz) when the old F min was above it.
        self.spin_f_max.setMinimum(1.0)
        super().reset_to_defaults()

    def get_dsp_config(self) -> OverallLevelConfig:
        """Translates UI selections into the DTO for the DSP layer."""
        f_stop = None if self.cb_full_bandwidth.isChecked() else float(self.spin_f_max.value())

        return OverallLevelConfig(
            f_start=float(self.spin_f_min.value()),
            f_stop=f_stop,
            fft_size=self._resolve_choice_value("fft_size", self.combo_fft_size),
            window_type=self._resolve_choice_value("window_type", self.combo_window_type),
            amplitude_mode=self._resolve_choice_value("amplitude_mode", self.combo_amplitude_mode),
            remove_dc=self.cb_remove_dc.isChecked(),
            **self.tracking_sweep.resolve_config_fields(),
        )
