# =====================================================================
# FILE: gui/ribbon/tab_acc_spectrogram.py
# =====================================================================
"""
Ribbon tab for the 2D tracked waterfall.

Left to right: Refresh, then RibbonGroups -- Spectrum, View, Tacho Tracking (its
Sweep/Hysteresis grey out in Free Run mode), Options -- then Batch, then Help.
Generates a SpectrogramConfig DTO for the DSP backend.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel

from core.dsp_configs import SpectrogramConfig
from gui.ribbon.ribbon_dsp_tab import RibbonDspTab
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_refresh_button, stack_buttons, vertical_separator
from gui.ribbon.save_section import ComputeResultSetButton


class TabAccSpectrogram(RibbonDspTab):
    sig_display_settings_changed = Signal()
    # cb_remove_dc is the last widget get_dsp_config() reads to be built.
    _settings_attr = "spectrogram_settings"
    _ready_widget_name = "cb_remove_dc"

    def _on_display_setting_changed(self, _val: str = ""):
        if hasattr(self, "combo_spectrum_format"):
            self._set_val("spec2d_format", self.combo_spectrum_format.currentText())
        if hasattr(self, "combo_amplitude_mode"):
            self._set_val("spec2d_amplitude", self.combo_amplitude_mode.currentText())
        if hasattr(self, "combo_color_scale"):
            self._set_val("spec2d_color_scale", self.combo_color_scale.currentText())
        self.sig_display_settings_changed.emit()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(8)

        self.btn_recalculate = make_refresh_button("Recompute this waterfall")
        self.save_section = ComputeResultSetButton(
            "spec2d", self.app_context,
            tooltip=("Compute this waterfall for the selected channels across a folder "
                     "or a saved query, and save it as a result set."),
            parent=self,
        )
        layout.addWidget(stack_buttons(self.btn_recalculate, self.save_section))
        layout.addWidget(vertical_separator())

        # -- Spectrum --
        self.combo_fft_size = QComboBox()
        self.combo_fft_size.addItems(["256", "512", "1024", "2048", "4096", "8192", "16384", "32768", "65536"])
        self.combo_fft_size.setCurrentText(self._get_val("spec2d_fft_size", "4096"))
        self.combo_fft_size.currentTextChanged.connect(lambda v: self._set_val("spec2d_fft_size", v))

        self.combo_window_type = QComboBox()
        self.combo_window_type.addItems(["Hanning", "Hamming", "Blackman", "Flat-top", "Rectangular"])
        self.combo_window_type.setCurrentText(self._get_val("spec2d_window", "Hanning"))
        self.combo_window_type.currentTextChanged.connect(lambda v: self._set_val("spec2d_window", v))

        spectrum_group = RibbonGroup("Spectrum", tooltip="Block size and window of the waterfall")
        spectrum_group.add_fields([
            ("FFT Size", self.combo_fft_size), ("Window", self.combo_window_type),
        ])
        layout.addWidget(spectrum_group)
        layout.addWidget(vertical_separator())

        # -- View --
        self.combo_spectrum_format = QComboBox()
        self.combo_spectrum_format.addItems(["Linear", "Power", "PSD"])
        self.combo_spectrum_format.setCurrentText(self._get_val("spec2d_format", "Linear"))
        self.combo_spectrum_format.currentTextChanged.connect(self._on_display_setting_changed)
        self.combo_format = self.combo_spectrum_format

        self.combo_amplitude_mode = QComboBox()
        self.combo_amplitude_mode.addItems(["RMS", "Peak"])
        self.combo_amplitude_mode.setCurrentText(self._get_val("spec2d_amplitude", "RMS"))
        self.combo_amplitude_mode.currentTextChanged.connect(self._on_display_setting_changed)

        self.combo_color_scale = QComboBox()
        self.combo_color_scale.addItems(["Linear", "dB (Log)"])
        self.combo_color_scale.setCurrentText(self._get_val("spec2d_color_scale", "Linear"))
        self.combo_color_scale.currentTextChanged.connect(self._on_display_setting_changed)

        view_group = RibbonGroup("View", tooltip="Display format, amplitude mode and colour mapping")
        view_group.add_fields([
            ("Format", self.combo_spectrum_format),
            ("Amplitude", self.combo_amplitude_mode),
            ("Color Scale", self.combo_color_scale),
        ])
        layout.addWidget(view_group)
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
        # No "Any (Both)": compute_spectrogram refuses it for RPM tracking (ADR §1.58
        # point 8) and the sweep is disabled in time mode. A value saved before that
        # is not in the list, so the combo stays on Up and the setting is rewritten.
        self.combo_direction.addItems(["Up (Run-Up)", "Down (Run-Down)"])
        saved_direction = self._get_val("spec2d_direction", "Up (Run-Up)")
        self.combo_direction.setCurrentText(saved_direction)
        if self.combo_direction.currentText() != saved_direction:
            self._set_val("spec2d_direction", self.combo_direction.currentText())
            if self.app_context is not None and hasattr(self.app_context, "log"):
                self.app_context.log(
                    f"WARNING: Spectrogram sweep '{saved_direction}' is not supported; "
                    f"using '{self.combo_direction.currentText()}'.")
        self.combo_direction.currentTextChanged.connect(lambda v: self._set_val("spec2d_direction", v))

        self.lbl_hysteresis = QLabel("Hysteresis [RPM]")
        self.spin_hysteresis = QDoubleSpinBox()
        self.spin_hysteresis.setDecimals(1)
        self.spin_hysteresis.setRange(0.0, 5000.0)
        self.spin_hysteresis.setValue(self._get_val("spec2d_hysteresis", 10.0, float))
        self.spin_hysteresis.valueChanged.connect(lambda v: self._set_val("spec2d_hysteresis", v))

        self.cb_remove_dc = QCheckBox("Remove DC Offset")
        saved_dc = str(self._get_val("spec2d_remove_dc", "true")).lower() == "true"
        self.cb_remove_dc.setChecked(saved_dc)
        self.cb_remove_dc.toggled.connect(lambda v: self._set_val("spec2d_remove_dc", v))

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
        options_group = RibbonGroup("Options")
        options_group.add_column(self.cb_remove_dc)
        layout.addWidget(options_group)


        build_tab_layout(self, layout, "2d_spectrogram")

        # Restore tracking mode last -- this drives the enable/label updates.
        saved_mode = self._get_val("spec2d_tracking_mode", "RPM Tracked")
        self.combo_tracking_mode.setCurrentText(saved_mode)
        self._on_tracking_mode_changed(saved_mode)
        self.combo_tracking_mode.currentTextChanged.connect(self._on_tracking_mode_changed)

        self._push_dsp_config()

    def _on_tracking_mode_changed(self, mode: str):
        is_rpm = "RPM" in mode

        self.spin_tracking_step.blockSignals(True)
        if is_rpm:
            self.lbl_step.setText("Step [RPM]")
            self.spin_tracking_step.setDecimals(1)
            self.spin_tracking_step.setRange(0.1, 5000.0)
            val = self._get_val("spec2d_step_rpm", 50.0, float)
            if val < 0.1:
                val = 0.1
                self.spin_tracking_step.setValue(val)
                self._set_val("spec2d_step_rpm", val)
            else:
                self.spin_tracking_step.setValue(val)
        else:
            self.lbl_step.setText("Step [s]")
            self.spin_tracking_step.setDecimals(3)
            self.spin_tracking_step.setRange(0.001, 5000.0)
            val = self._get_val("spec2d_step_time", 0.05, float)
            if val < 0.001:
                val = 0.001
                self.spin_tracking_step.setValue(val)
                self._set_val("spec2d_step_time", val)
            else:
                self.spin_tracking_step.setValue(val)
        self.spin_tracking_step.blockSignals(False)

        self.lbl_direction.setEnabled(is_rpm)
        self.combo_direction.setEnabled(is_rpm)
        self.lbl_hysteresis.setEnabled(is_rpm)
        self.spin_hysteresis.setEnabled(is_rpm)

        self._set_val("spec2d_tracking_mode", mode)

    def _on_step_changed(self, val: float):
        mode = self.combo_tracking_mode.currentText()
        if "RPM" in mode:
            self._set_val("spec2d_step_rpm", val)
        else:
            self._set_val("spec2d_step_time", val)

    def get_dsp_config(self) -> SpectrogramConfig:
        """Translates UI selections into standard DTOs for the DSP layer."""
        w_map = {"Hanning": "hann", "Hamming": "hamming", "Blackman": "blackman", "Flat-top": "flattop",
                 "Rectangular": "boxcar"}
        dir_map = {"Up (Run-Up)": "up", "Down (Run-Down)": "down"}
        mode = "rpm" if "RPM" in self.combo_tracking_mode.currentText() else "time"

        return SpectrogramConfig(
            fft_size=int(self.combo_fft_size.currentText()),
            window_type=w_map.get(self.combo_window_type.currentText(), "hann"),
            amplitude_mode=self.combo_amplitude_mode.currentText().lower(),
            spectrum_format=self.combo_spectrum_format.currentText().lower(),
            tracking_mode=mode,
            step=float(self.spin_tracking_step.value()),
            direction=dir_map.get(self.combo_direction.currentText(), "up"),
            hysteresis=float(self.spin_hysteresis.value()),
            remove_dc=self.cb_remove_dc.isChecked(),
            color_scale=self.combo_color_scale.currentText(),
        )


def _labeled_column(rows):
    """A vertical column of (label, widget) pairs. `label` may be a str or an
    existing QLabel the tab keeps a reference to (for enable/disable)."""
    from PySide6.QtWidgets import QVBoxLayout

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
