# =====================================================================
# FILE: gui/ribbon/tab_acc_spectrogram.py
# =====================================================================
"""
Ribbon tab for the 2D tracked waterfall.

Left to right: Refresh, then RibbonGroups -- Spectrum, Tacho Tracking (the
tab's TrackingSweepFields), View, Options -- then Batch, then Help.
Generates a SpectrogramConfig DTO for the DSP backend.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout

from core.dsp_configs import SpectrogramConfig
from gui.ribbon.ribbon_dsp_tab import RibbonDspTab
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_refresh_button, stack_buttons, vertical_separator
from gui.ribbon.save_section import ComputeResultSetButton
from view_models.analysis_kinds import ANALYSIS_SPECTROGRAM


class TabAccSpectrogram(RibbonDspTab):
    sig_display_settings_changed = Signal()
    # cb_remove_dc is the last widget get_dsp_config() reads to be built.
    _settings_attr = "spectrogram_settings"
    _ready_widget_name = "cb_remove_dc"
    _analysis_kind = ANALYSIS_SPECTROGRAM

    def _on_display_setting_changed(self, _val: str = ""):
        self._emit_display_settings_changed()

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
        self.combo_fft_size = self._build_field_combo("fft_size")
        self.combo_window_type = self._build_field_combo("window_type")

        spectrum_group = RibbonGroup("Spectrum", tooltip="Block size and window of the waterfall")
        spectrum_group.add_fields([
            ("FFT Size", self.combo_fft_size), ("Window", self.combo_window_type),
        ])
        layout.addWidget(spectrum_group)
        layout.addWidget(vertical_separator())

        # -- Tacho Tracking --
        layout.addWidget(self._build_tracking_sweep("spec2d").group)
        layout.addWidget(vertical_separator())

        # -- View --
        self.combo_spectrum_format = self._build_field_combo("spectrum_format")
        self.combo_spectrum_format.currentTextChanged.connect(self._on_display_setting_changed)
        self.combo_format = self.combo_spectrum_format

        self.combo_amplitude_mode = self._build_field_combo("amplitude_mode")
        self.combo_amplitude_mode.currentTextChanged.connect(self._on_display_setting_changed)

        self.combo_color_scale = self._build_field_combo("color_scale")
        self.combo_color_scale.currentTextChanged.connect(self._on_display_setting_changed)

        view_group = RibbonGroup("View", tooltip="Display format, amplitude mode and colour mapping")
        view_group.add_fields([
            ("Amplitude", self.combo_amplitude_mode),
            ("Format", self.combo_spectrum_format),
            ("Color Scale", self.combo_color_scale),
        ])
        layout.addWidget(view_group)
        layout.addWidget(vertical_separator())

        # -- Options --
        self.cb_remove_dc = QCheckBox("Remove DC Offset")
        self._bind_field("remove_dc", self.cb_remove_dc)

        options_group = RibbonGroup("Options")
        options_group.add_column(self.cb_remove_dc)
        layout.addWidget(options_group)


        build_tab_layout(self, layout, "2d_spectrogram")

        self._push_dsp_config()

    def get_dsp_config(self) -> SpectrogramConfig:
        """Translates UI selections into standard DTOs for the DSP layer."""
        return SpectrogramConfig(
            fft_size=self._resolve_choice_value("fft_size", self.combo_fft_size),
            window_type=self._resolve_choice_value("window_type", self.combo_window_type),
            amplitude_mode=self._resolve_choice_value("amplitude_mode", self.combo_amplitude_mode),
            spectrum_format=self._resolve_choice_value("spectrum_format", self.combo_spectrum_format),
            remove_dc=self.cb_remove_dc.isChecked(),
            color_scale=self._resolve_choice_value("color_scale", self.combo_color_scale),
            **self.tracking_sweep.resolve_config_fields(),
        )

