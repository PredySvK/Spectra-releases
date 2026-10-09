# =====================================================================
# FILE: gui/ribbon/tab_acc_overall_level.py
# =====================================================================
"""
Ribbon tab for the live Overall Level dock (band energy against speed or time, ADR §1.62).

Left to right: Refresh, then RibbonGroups -- Spectrum, View, Band, Tacho
Tracking, Options, Batch. View/Amplitude (issue #128) mirrors Order
Tracking's group: an instant redraw, no recompute (ADR §1.60, §1.62 point 5).
Generates an OverallLevelConfig DTO for the DSP backend.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QVBoxLayout,
)

from core.dsp_configs import OverallLevelConfig
from gui.ribbon.ribbon_dsp_tab import RibbonDspTab
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_refresh_split_button, stack_buttons, vertical_separator
from gui.ribbon.save_section import ComputeResultSetButton


def _labeled_column(rows):
    """A vertical column of (label, widget) pairs. `label` may be a str or an
    existing QLabel the tab keeps a reference to (for enable/disable)."""
    column = QVBoxLayout()
    column.setSpacing(4)
    for label, widget in rows:
        if isinstance(label, str):
            label_widget = QLabel(label)
            label_widget.setStyleSheet("color: #b8b8b8; font-size: 11px;")
        else:
            label_widget = label
            label_widget.setStyleSheet("color: #b8b8b8; font-size: 11px;")
        column.addWidget(label_widget)
        column.addWidget(widget)
        column.addSpacing(4)
    return column


class TabAccOverallLevel(RibbonDspTab):
    sig_display_settings_changed = Signal()
    _settings_attr = "overall_level_settings"
    _ready_widget_name = "cb_remove_dc"

    def _on_display_setting_changed(self, _val: str = ""):
        if hasattr(self, "combo_amplitude_mode"):
            self._set_val("oal_amplitude", self.combo_amplitude_mode.currentText())
        self.sig_display_settings_changed.emit()

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
        self.combo_fft_size = QComboBox()
        self.combo_fft_size.addItems(["256", "512", "1024", "2048", "4096", "8192", "16384", "32768", "65536"])
        self.combo_fft_size.setCurrentText(self._get_val("oal_fft_size", "4096"))
        self.combo_fft_size.currentTextChanged.connect(lambda v: self._set_val("oal_fft_size", v))

        self.combo_window_type = QComboBox()
        self.combo_window_type.addItems(["Hanning", "Hamming", "Blackman", "Flat-top", "Rectangular"])
        self.combo_window_type.setCurrentText(self._get_val("oal_window", "Hanning"))
        self.combo_window_type.currentTextChanged.connect(lambda v: self._set_val("oal_window", v))

        spectrum_group = RibbonGroup("Spectrum", tooltip="Block size and window of the underlying FFT")
        spectrum_group.add_fields([
            ("FFT Size", self.combo_fft_size), ("Window", self.combo_window_type),
        ])
        layout.addWidget(spectrum_group)
        layout.addWidget(vertical_separator())

        # -- View --
        self.combo_amplitude_mode = QComboBox()
        self.combo_amplitude_mode.addItems(["RMS", "Peak"])
        self.combo_amplitude_mode.setCurrentText(self._get_val("oal_amplitude", "RMS"))
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
        self.spin_f_min.setDecimals(1)
        self.spin_f_min.setRange(0.0, 100000.0)
        self.spin_f_min.setValue(self._get_val("oal_f_min", 10.0, float))

        self.spin_f_max = QDoubleSpinBox()
        self.spin_f_max.setDecimals(1)
        self.spin_f_max.setRange(0.1, 200000.0)
        self.spin_f_max.setValue(self._get_val("oal_f_max", 1000.0, float))
        self.spin_f_max.setMinimum(self.spin_f_min.value() + 0.1)

        self.cb_full_bandwidth = QCheckBox("Full Bandwidth")
        saved_full_bandwidth = str(self._get_val("oal_full_bandwidth", "true")).lower() == "true"
        self.cb_full_bandwidth.setChecked(saved_full_bandwidth)
        self.spin_f_max.setEnabled(not saved_full_bandwidth)

        self.spin_f_min.valueChanged.connect(self._on_f_min_changed)
        self.cb_full_bandwidth.toggled.connect(self._on_full_bandwidth_toggled)
        self.spin_f_max.valueChanged.connect(lambda v: self._set_val("oal_f_max", v))

        band_group = RibbonGroup("Band", tooltip="Frequency band the Overall Level energy is integrated over")
        band_group.add_fields([("F min [Hz]", self.spin_f_min), ("F max [Hz]", self.spin_f_max)])
        band_group.add_column(self.cb_full_bandwidth)
        layout.addWidget(band_group)
        layout.addWidget(vertical_separator())

        # -- Tacho Tracking --
        self.combo_tracking_mode = QComboBox()
        self.combo_tracking_mode.addItems(["Free Run (Time)", "RPM Tracked"])

        self.lbl_step = QLabel("Step:")
        self.spin_tracking_step = QDoubleSpinBox()
        self.spin_tracking_step.setDecimals(1)
        self.spin_tracking_step.setRange(0.1, 5000.0)
        self.spin_tracking_step.valueChanged.connect(self._on_step_changed)

        self.lbl_direction = QLabel("Sweep")
        self.combo_direction = QComboBox()
        self.combo_direction.addItems(["Up (Run-Up)", "Down (Run-Down)", "Any (Both)"])
        self.combo_direction.setCurrentText(self._get_val("oal_direction", "Up (Run-Up)"))
        self.combo_direction.currentTextChanged.connect(lambda v: self._set_val("oal_direction", v))

        self.lbl_hysteresis = QLabel("Hysteresis [RPM]")
        self.spin_hysteresis = QDoubleSpinBox()
        self.spin_hysteresis.setDecimals(1)
        self.spin_hysteresis.setRange(0.0, 5000.0)
        self.spin_hysteresis.setValue(self._get_val("oal_hysteresis", 10.0, float))
        self.spin_hysteresis.valueChanged.connect(lambda v: self._set_val("oal_hysteresis", v))

        tracking_group = RibbonGroup(
            "Tacho Tracking",
            tooltip="RPM Tracked resamples onto engine speed; Free Run keeps the time axis",
        )
        tracking_group.body.setSpacing(8)
        col_a = _labeled_column([("Tracking Mode", self.combo_tracking_mode),
                                 (self.lbl_step, self.spin_tracking_step)])
        col_b = _labeled_column([(self.lbl_direction, self.combo_direction),
                                 (self.lbl_hysteresis, self.spin_hysteresis)])
        tracking_group.body.addLayout(col_a)
        tracking_group.body.addLayout(col_b)
        layout.addWidget(tracking_group)
        layout.addWidget(vertical_separator())

        # -- Options --
        self.cb_remove_dc = QCheckBox("Remove DC Offset")
        saved_dc = str(self._get_val("oal_remove_dc", "true")).lower() == "true"
        self.cb_remove_dc.setChecked(saved_dc)
        self.cb_remove_dc.toggled.connect(lambda v: self._set_val("oal_remove_dc", v))

        options_group = RibbonGroup("Options")
        options_group.add_column(self.cb_remove_dc)
        layout.addWidget(options_group)


        # Restore tracking mode last -- this drives the enable/label updates.
        saved_mode = self._get_val("oal_tracking_mode", "RPM Tracked")
        self.combo_tracking_mode.setCurrentText(saved_mode)
        self._on_tracking_mode_changed(saved_mode)
        self.combo_tracking_mode.currentTextChanged.connect(self._on_tracking_mode_changed)

        build_tab_layout(self, layout, "overall_level")

        self._push_dsp_config()

    def _on_f_min_changed(self, value: float):
        self.spin_f_max.setMinimum(value + 0.1)
        self._set_val("oal_f_min", value)

    def _on_full_bandwidth_toggled(self, checked: bool):
        self.spin_f_max.setEnabled(not checked)
        self._set_val("oal_full_bandwidth", checked)

    def _on_tracking_mode_changed(self, mode: str):
        is_rpm = "RPM" in mode

        self.spin_tracking_step.blockSignals(True)
        if is_rpm:
            self.lbl_step.setText("Step [RPM]")
            self.spin_tracking_step.setDecimals(1)
            self.spin_tracking_step.setRange(0.1, 5000.0)
            default_rpm = self._get_val("oal_tracking_step", 50.0, float)
            val = self._get_val("oal_step_rpm", default_rpm, float)
            if val < 0.1:
                val = 0.1
                self.spin_tracking_step.setValue(val)
                self._set_val("oal_step_rpm", val)
                self._set_val("oal_tracking_step", val)
            else:
                self.spin_tracking_step.setValue(val)
        else:
            self.lbl_step.setText("Step [s]")
            self.spin_tracking_step.setDecimals(3)
            self.spin_tracking_step.setRange(0.001, 5000.0)
            val = self._get_val("oal_step_time", 0.05, float)
            if val < 0.001:
                val = 0.001
                self.spin_tracking_step.setValue(val)
                self._set_val("oal_step_time", val)
            else:
                self.spin_tracking_step.setValue(val)
        self.spin_tracking_step.blockSignals(False)

        self.lbl_direction.setEnabled(is_rpm)
        self.combo_direction.setEnabled(is_rpm)
        self.lbl_hysteresis.setEnabled(is_rpm)
        self.spin_hysteresis.setEnabled(is_rpm)

        self._set_val("oal_tracking_mode", mode)

    def _on_step_changed(self, val: float):
        mode = self.combo_tracking_mode.currentText()
        if "RPM" in mode:
            self._set_val("oal_step_rpm", val)
            self._set_val("oal_tracking_step", val)
        else:
            self._set_val("oal_step_time", val)

    def get_dsp_config(self) -> OverallLevelConfig:
        """Translates UI selections into the DTO for the DSP layer."""
        w_map = {"Hanning": "hann", "Hamming": "hamming", "Blackman": "blackman", "Flat-top": "flattop",
                 "Rectangular": "boxcar"}
        dir_map = {"Up (Run-Up)": "up", "Down (Run-Down)": "down", "Any (Both)": "any"}
        mode = "rpm" if "RPM" in self.combo_tracking_mode.currentText() else "time"

        f_stop = None if self.cb_full_bandwidth.isChecked() else float(self.spin_f_max.value())

        return OverallLevelConfig(
            f_start=float(self.spin_f_min.value()),
            f_stop=f_stop,
            fft_size=int(self.combo_fft_size.currentText()),
            window_type=w_map.get(self.combo_window_type.currentText(), "hann"),
            amplitude_mode=self.combo_amplitude_mode.currentText().lower(),
            tracking_mode=mode,
            step=float(self.spin_tracking_step.value()),
            direction=dir_map.get(self.combo_direction.currentText(), "up"),
            hysteresis=float(self.spin_hysteresis.value()),
            remove_dc=self.cb_remove_dc.isChecked(),
        )
