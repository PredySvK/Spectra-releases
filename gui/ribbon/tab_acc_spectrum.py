# =====================================================================
# FILE: gui/ribbon/tab_acc_spectrum.py
# =====================================================================
"""
Ribbon tab for 1D Spectrum configuration.

Left to right: the Refresh action, then captioned RibbonGroups -- FFT Analysis,
View, Averaging, Options -- then Compute Batch (beside Refresh), then Help.
Integrated with QSettings via AppContext for persistent user preferences;
generates a SpectrumConfig DTO to decouple the UI from the DSP backend.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout

from core.dsp_configs import SpectrumConfig
from gui.ribbon.ribbon_dsp_tab import RibbonDspTab
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_refresh_split_button, stack_buttons, vertical_separator
from gui.ribbon.save_section import ComputeResultSetButton


class TabAccSpectrum(RibbonDspTab):
    sig_display_settings_changed = Signal()
    # cb_band_rms is built last of the widgets get_dsp_config() reads.
    _settings_attr = "spectrum_settings"
    _ready_widget_name = "cb_band_rms"

    def _after_push(self):
        self.app_context.band_rms_cursors_enabled = self.cb_band_rms.isChecked()
        self.app_context.new_curve_config_from_trace = self.cb_new_curve_from_trace.isChecked()

    def _on_display_setting_changed(self, _val: str = ""):
        if hasattr(self, "combo_spectrum_format"):
            self._set_val("spec1d_format", self.combo_spectrum_format.currentText())
        if hasattr(self, "combo_amplitude_mode"):
            self._set_val("spec1d_amplitude", self.combo_amplitude_mode.currentText())
        if hasattr(self, "combo_scale"):
            self._set_val("spec1d_scale", self.combo_scale.currentText())
        self.sig_display_settings_changed.emit()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(8)

        self.btn_recalculate = make_refresh_split_button("Recompute this 1D spectrum")
        self.save_section = ComputeResultSetButton(
            "spec1d", self.app_context,
            tooltip=("Compute this spectrum for the selected channels across a folder "
                     "or a saved query, and save it as a result set."),
            parent=self,
        )
        layout.addWidget(stack_buttons(self.btn_recalculate, self.save_section))
        layout.addWidget(vertical_separator())

        # -- FFT Analysis --
        self.combo_fft_size = QComboBox()
        self.combo_fft_size.addItems(["256", "512", "1024", "2048", "4096", "8192", "16384", "32768", "65536"])
        self.combo_fft_size.setCurrentText(self._get_val("spec1d_fft_size", "4096"))
        self.combo_fft_size.currentTextChanged.connect(lambda v: self._set_val("spec1d_fft_size", v))

        self.combo_window_type = QComboBox()
        self.combo_window_type.addItems(["Hanning", "Hamming", "Blackman", "Flat-top", "Rectangular"])
        self.combo_window_type.setCurrentText(self._get_val("spec1d_window", "Hanning"))
        self.combo_window_type.currentTextChanged.connect(lambda v: self._set_val("spec1d_window", v))

        fft_group = RibbonGroup("FFT Analysis", tooltip="Block size and window of the spectrum")
        fft_group.add_fields([
            ("FFT Size", self.combo_fft_size), ("Window", self.combo_window_type),
        ])
        layout.addWidget(fft_group)
        layout.addWidget(vertical_separator())

        # -- View --
        self.combo_spectrum_format = QComboBox()
        self.combo_spectrum_format.addItems(["Linear", "Power", "PSD"])
        self.combo_spectrum_format.setCurrentText(self._get_val("spec1d_format", "Linear"))
        self.combo_spectrum_format.currentTextChanged.connect(self._on_display_setting_changed)
        self.combo_format = self.combo_spectrum_format

        self.combo_amplitude_mode = QComboBox()
        self.combo_amplitude_mode.addItems(["RMS", "Peak"])
        self.combo_amplitude_mode.setCurrentText(self._get_val("spec1d_amplitude", "RMS"))
        self.combo_amplitude_mode.currentTextChanged.connect(self._on_display_setting_changed)

        self.combo_scale = QComboBox()
        self.combo_scale.addItems(["Linear", "dB"])
        self.combo_scale.setCurrentText(self._get_val("spec1d_scale", "Linear"))
        self.combo_scale.currentTextChanged.connect(self._on_display_setting_changed)

        view_group = RibbonGroup("View", tooltip="Display format, amplitude mode and scaling")
        view_group.add_fields([
            ("Format", self.combo_spectrum_format),
            ("Amplitude", self.combo_amplitude_mode),
            ("Scale", self.combo_scale),
        ])
        layout.addWidget(view_group)
        layout.addWidget(vertical_separator())

        # -- Averaging --
        self.combo_averaging = QComboBox()
        self.combo_averaging.addItems(["Linear", "Peak Hold", "Exponential"])
        self.combo_averaging.setToolTip(
            "Linear: mean of every block. Peak Hold: the loudest value each bin ever "
            "reached, for a transient a mean would wash out. Exponential: recent "
            "blocks weighted more, by the alpha beside it."
        )
        self.combo_averaging.setCurrentText(self._get_val("spec1d_averaging", "Linear"))
        self.combo_averaging.currentTextChanged.connect(self._on_averaging_changed)

        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0.01, 1.0)
        self.spin_alpha.setSingleStep(0.05)
        self.spin_alpha.setDecimals(2)
        self.spin_alpha.setToolTip("Weight of each new block in exponential averaging.")
        self.spin_alpha.setValue(self._get_val("spec1d_exp_alpha", 0.1, float))
        self.spin_alpha.valueChanged.connect(lambda v: self._set_val("spec1d_exp_alpha", v))

        avg_group = RibbonGroup("Averaging", tooltip="How repeated FFT blocks are combined")
        avg_group.add_fields([("Mode", self.combo_averaging), ("Weight α", self.spin_alpha)])
        layout.addWidget(avg_group)
        layout.addWidget(vertical_separator())

        # -- Options --
        self.cb_remove_dc = QCheckBox("Remove DC Offset")
        saved_dc = str(self._get_val("spec1d_remove_dc", "true")).lower() == "true"
        self.cb_remove_dc.setChecked(saved_dc)
        self.cb_remove_dc.toggled.connect(lambda v: self._set_val("spec1d_remove_dc", v))

        self.cb_new_curve_from_trace = QCheckBox("New Curve: Match Graph")
        self.cb_new_curve_from_trace.setToolTip(
            "A dropped comparison channel is computed with this ribbon's current FFT "
            "settings by default. Check this to have it inherit the settings of the "
            "curve already on the graph instead, so the comparison is apples-to-apples."
        )
        saved_from_trace = str(self._get_val("spec1d_new_curve_from_trace", "false")).lower() == "true"
        self.cb_new_curve_from_trace.setChecked(saved_from_trace)
        self.cb_new_curve_from_trace.toggled.connect(
            lambda v: self._set_val("spec1d_new_curve_from_trace", v))

        self.cb_band_rms = QCheckBox("Band RMS Cursors")
        self.cb_band_rms.setObjectName("BandRmsCheckbox")  # Help figure target
        self.cb_band_rms.setToolTip(
            "Show a draggable band on the spectrum and report the RMS level inside it."
        )
        saved_band_rms = str(self._get_val("spec1d_band_rms_cursors", "false")).lower() == "true"
        self.cb_band_rms.setChecked(saved_band_rms)
        self.cb_band_rms.toggled.connect(lambda v: self._set_val("spec1d_band_rms_cursors", v))

        options_group = RibbonGroup("Options")
        options_group.add_column(self.cb_remove_dc, self.cb_new_curve_from_trace, self.cb_band_rms)
        layout.addWidget(options_group)


        build_tab_layout(self, layout, "1d_spectrum")

        self.spin_alpha.setEnabled(self.combo_averaging.currentText() == "Exponential")
        self._push_dsp_config()

    def _on_averaging_changed(self, text: str):
        # Alpha means nothing to the other two modes; left enabled it reads as a
        # setting that does something when it does not.
        self.spin_alpha.setEnabled(text == "Exponential")
        self._set_val("spec1d_averaging", text)

    def get_dsp_config(self) -> SpectrumConfig:
        """Translates UI selections into standard DTOs for the DSP layer."""
        w_map = {"Hanning": "hann", "Hamming": "hamming", "Blackman": "blackman", "Flat-top": "flattop",
                 "Rectangular": "boxcar"}
        a_map = {"Linear": "linear", "Peak Hold": "peak_hold", "Exponential": "exponential"}

        return SpectrumConfig(
            fft_size=int(self.combo_fft_size.currentText()),
            window_type=w_map.get(self.combo_window_type.currentText(), "hann"),
            amplitude_mode=self.combo_amplitude_mode.currentText().lower(),
            spectrum_format=self.combo_spectrum_format.currentText().lower(),
            remove_dc=self.cb_remove_dc.isChecked(),
            averaging_type=a_map.get(self.combo_averaging.currentText(), "linear"),
            exponential_alpha=self.spin_alpha.value(),
            decibel_scale=(self.combo_scale.currentText() == "dB"),
        )
