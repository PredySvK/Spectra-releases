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
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout

from core.dsp_configs import SpectrumConfig, allows_format
from gui.ribbon.ribbon_dsp_tab import RibbonDspTab
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_refresh_split_button, stack_buttons, vertical_separator
from gui.ribbon.save_section import ComputeResultSetButton
from view_models.analysis_kinds import ANALYSIS_SPECTRUM

_LINEAR_ONLY_TIP = ("Linear average averages amplitudes, so it shows only the Linear format: its square "
                    "is not the mean power, and a PSD of it is no density (about 1 dB low on noise).")


class TabAccSpectrum(RibbonDspTab):
    sig_display_settings_changed = Signal()
    # cb_band_rms is built last of the widgets get_dsp_config() reads.
    _settings_attr = "spectrum_settings"
    _ready_widget_name = "cb_band_rms"
    _analysis_kind = ANALYSIS_SPECTRUM

    def _after_push(self):
        self.app_context.band_rms_cursors_enabled = self.cb_band_rms.isChecked()
        self.app_context.new_curve_config_from_trace = self.cb_new_curve_from_trace.isChecked()

    def _on_display_setting_changed(self, _val: str = ""):
        self._sync_format_with_averaging()
        self._emit_display_settings_changed()

    def _sync_dependent_widgets(self):
        self._sync_exp_parameter_enabled()
        self._sync_format_with_averaging()

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
        self.combo_fft_size = self._build_field_combo("fft_size")
        self.combo_window_type = self._build_field_combo("window_type")

        fft_group = RibbonGroup("FFT Analysis", tooltip="Block size and window of the spectrum")
        fft_group.add_fields([
            ("FFT Size", self.combo_fft_size), ("Window", self.combo_window_type),
        ])
        layout.addWidget(fft_group)
        layout.addWidget(vertical_separator())

        # -- View --
        self.combo_spectrum_format = self._build_field_combo("spectrum_format")
        self.combo_spectrum_format.currentTextChanged.connect(self._on_display_setting_changed)
        self.combo_format = self.combo_spectrum_format

        self.combo_amplitude_mode = self._build_field_combo("amplitude_mode")
        self.combo_amplitude_mode.currentTextChanged.connect(self._on_display_setting_changed)

        self.combo_scale = self._build_field_combo("decibel_scale")
        self.combo_scale.currentTextChanged.connect(self._on_display_setting_changed)

        view_group = RibbonGroup("View", tooltip="Display format, amplitude mode and scaling")
        view_group.add_fields([
            ("Amplitude", self.combo_amplitude_mode),
            ("Format", self.combo_spectrum_format),
            ("Scale", self.combo_scale),
        ])
        layout.addWidget(view_group)
        layout.addWidget(vertical_separator())

        # -- Averaging --
        self.combo_averaging = self._build_field_combo("averaging_type")
        self.combo_averaging.setToolTip(
            "Named as in Simcenter Testlab.\n"
            "Energy average: mean power (|X|²) of every block.\n"
            "Linear average: mean amplitude (|X|) of every block; lower than Energy "
            "average on a run-up or noise. Linear format only.\n"
            "Energy exponential average: recent blocks weighted more; the Exponential "
            "parameter beside it is how much of the old average each new block keeps.\n"
            "Minimum value / Maximum value: the lowest / loudest power each bin reached; "
            "the maximum catches a transient a mean would wash out."
        )
        self.combo_averaging.currentTextChanged.connect(self._on_averaging_changed)

        # Shown in percent, as Testlab; the config keeps the fraction (#956).
        # 100 % would freeze the average at the first block, so it is not offered.
        self.spin_exp_parameter = QDoubleSpinBox()
        self.spin_exp_parameter.setRange(0.0, 99.0)
        self.spin_exp_parameter.setSingleStep(1.0)
        self.spin_exp_parameter.setDecimals(0)
        self.spin_exp_parameter.setSuffix(" %")
        self.spin_exp_parameter.setToolTip(
            "Testlab's Exponential parameter: how much of the old average each new block keeps "
            "in Energy exponential average. Higher smooths more; 0 % is the last block alone.")
        self._bind_field("exponential_parameter", self.spin_exp_parameter)

        avg_group = RibbonGroup("Averaging", tooltip="How repeated FFT blocks are combined")
        avg_group.add_fields([("Mode", self.combo_averaging), ("Exp. parameter", self.spin_exp_parameter)])
        layout.addWidget(avg_group)
        layout.addWidget(vertical_separator())

        # -- Options --
        self.cb_remove_dc = QCheckBox("Remove DC Offset")
        self._bind_field("remove_dc", self.cb_remove_dc)

        self.cb_new_curve_from_trace = QCheckBox("New Curve: Match Graph")
        self.cb_new_curve_from_trace.setToolTip(
            "A dropped comparison channel is computed with this ribbon's current FFT "
            "settings by default. Check this to have it inherit the settings of the "
            "curve already on the graph instead, so the comparison is apples-to-apples."
        )
        self._bind_field("new_curve_from_trace", self.cb_new_curve_from_trace)

        self.cb_band_rms = QCheckBox("Band RMS Cursors")
        self.cb_band_rms.setObjectName("BandRmsCheckbox")  # Help figure target
        self.cb_band_rms.setToolTip(
            "Show a draggable band on every spectrum and report the RMS level inside it."
        )
        self._bind_field("band_rms_cursors", self.cb_band_rms)

        options_group = RibbonGroup("Options")
        options_group.add_column(self.cb_remove_dc, self.cb_new_curve_from_trace, self.cb_band_rms)
        layout.addWidget(options_group)


        build_tab_layout(self, layout, "1d_spectrum")

        self._sync_dependent_widgets()
        self._push_dsp_config()

    def _on_averaging_changed(self, _text: str):
        self._sync_dependent_widgets()

    def _sync_format_with_averaging(self):
        # Linear average shows only the Linear format (§1.283): each combo greys
        # out the items that would not pair with the other's choice. Settings
        # saved with a pair that does not (by hand) keep the Format and fall
        # back to Energy average.
        if not hasattr(self, "combo_averaging"):
            return
        averaging = self._resolve_choice_value("averaging_type", self.combo_averaging)
        spectrum_format = self._resolve_choice_value("spectrum_format", self.combo_spectrum_format)
        if not allows_format(averaging, spectrum_format):
            self.combo_averaging.setCurrentText(self.dsp_choices.parameter("averaging_type").default_label)
            return  # the averaging change syncs again
        for value in self.dsp_choices.parameter("spectrum_format").values:
            self._set_item_enabled(self.combo_spectrum_format, "spectrum_format", value,
                                   allows_format(averaging, value))
        for value in self.dsp_choices.parameter("averaging_type").values:
            self._set_item_enabled(self.combo_averaging, "averaging_type", value,
                                   allows_format(value, spectrum_format))

    def _set_item_enabled(self, combo: QComboBox, name: str, value, enabled: bool):
        index = combo.findText(self.dsp_choices.parameter(name).resolve_label(value))
        combo.model().item(index).setEnabled(enabled)
        combo.setItemData(index, None if enabled else _LINEAR_ONLY_TIP, Qt.ItemDataRole.ToolTipRole)

    def _sync_exp_parameter_enabled(self):
        # The parameter means nothing to the other modes; left enabled it reads
        # as a setting that does something when it does not.
        self.spin_exp_parameter.setEnabled(
            self._resolve_choice_value("averaging_type", self.combo_averaging) == "energy_exponential")

    def get_dsp_config(self) -> SpectrumConfig:
        """Translates UI selections into standard DTOs for the DSP layer."""
        return SpectrumConfig(
            fft_size=self._resolve_choice_value("fft_size", self.combo_fft_size),
            window_type=self._resolve_choice_value("window_type", self.combo_window_type),
            amplitude_mode=self._resolve_choice_value("amplitude_mode", self.combo_amplitude_mode),
            spectrum_format=self._resolve_choice_value("spectrum_format", self.combo_spectrum_format),
            remove_dc=self.cb_remove_dc.isChecked(),
            averaging_type=self._resolve_choice_value("averaging_type", self.combo_averaging),
            exponential_parameter=self.spin_exp_parameter.value() / 100.0,
            decibel_scale=self._resolve_choice_value("decibel_scale", self.combo_scale),
        )
