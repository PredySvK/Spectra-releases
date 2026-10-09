# =====================================================================
# FILE: gui/ribbon/tab_acc_order_tracking.py
# =====================================================================
"""
Ribbon tab for acceleration order tracking.

Left to right: Refresh, then RibbonGroups -- Spectrum, View, Live Orders (what the
active plot shows), Tacho Tracking, Options -- then Batch, then Help. The
orders a *batch* extracts are asked in the Compute Result Set dialog, not here;
this tab keeps get_save_dsp_config() reading that value back from QSettings.
Generates an OrderTrackingConfig DTO for the DSP backend.
"""
from typing import List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLineEdit

from core.dsp_configs import OrderTrackingConfig
from gui.ribbon.ribbon_dsp_tab import RibbonDspTab
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_refresh_split_button, stack_buttons, vertical_separator
from gui.ribbon.save_section import ComputeResultSetButton
from view_models.evaluation import parse_orders_text


class TabAccOrderTracking(RibbonDspTab):
    sig_display_settings_changed = Signal()
    _settings_attr = "order_tracking_settings"
    _ready_widget_name = "cb_remove_dc"

    def _on_display_setting_changed(self, _val: str = ""):
        if hasattr(self, "combo_amplitude_mode"):
            self._set_val("order_amplitude", self.combo_amplitude_mode.currentText())
        self.sig_display_settings_changed.emit()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 4, 5, 2)
        layout.setSpacing(8)

        self.btn_recalculate = make_refresh_split_button("Recompute order tracking for the active channel")
        self.save_section = ComputeResultSetButton(
            "order", self.app_context, extra_orders=True,
            tooltip=("Compute the chosen orders for the selected channels across a folder "
                     "or a saved query, and save them as a result set."),
            parent=self,
        )
        layout.addWidget(stack_buttons(self.btn_recalculate, self.save_section))
        layout.addWidget(vertical_separator())

        # -- Spectrum --
        self.combo_fft_size = QComboBox()
        self.combo_fft_size.addItems(["256", "512", "1024", "2048", "4096", "8192", "16384", "32768", "65536"])
        self.combo_fft_size.setCurrentText(self._get_val("order_fft_size", "4096"))
        self.combo_fft_size.currentTextChanged.connect(lambda v: self._set_val("order_fft_size", v))

        self.combo_window_type = QComboBox()
        self.combo_window_type.addItems(["Hanning", "Hamming", "Blackman", "Flat-top", "Rectangular"])
        self.combo_window_type.setCurrentText(self._get_val("order_window", "Hanning"))
        self.combo_window_type.currentTextChanged.connect(lambda v: self._set_val("order_window", v))

        spectrum_group = RibbonGroup("Spectrum", tooltip="Block size and window of the order FFT")
        spectrum_group.add_fields([
            ("FFT Size", self.combo_fft_size), ("Window", self.combo_window_type),
        ])
        layout.addWidget(spectrum_group)
        layout.addWidget(vertical_separator())

        # -- View --
        self.combo_amplitude_mode = QComboBox()
        self.combo_amplitude_mode.addItems(["RMS", "Peak"])
        self.combo_amplitude_mode.setCurrentText(self._get_val("order_amplitude", "RMS"))
        self.combo_amplitude_mode.currentTextChanged.connect(self._on_display_setting_changed)

        view_group = RibbonGroup("View", tooltip="Display amplitude mode")
        view_group.add_fields([("Amplitude", self.combo_amplitude_mode)])
        layout.addWidget(view_group)
        layout.addWidget(vertical_separator())

        # -- Live Orders (what the active plot shows) --
        raw_target = self._get_val("order_targets", "1")
        initial_parsed = parse_orders_text(str(raw_target))
        self._last_valid_orders: List[float] = initial_parsed if initial_parsed else [1.0]

        self.edit_target_orders = QLineEdit(str(raw_target))
        self.edit_target_orders.setFixedWidth(90)
        self._default_orders_tooltip = (
            "Orders shown in the active plot, e.g. 1. "
            "Enter several at once separated by commas or semicolons, e.g. 1, 2, 4.5"
        )
        self.edit_target_orders.setToolTip(self._default_orders_tooltip)
        if initial_parsed is None or not initial_parsed:
            self.edit_target_orders.setStyleSheet("border: 1px solid #d9534f;")
        self.edit_target_orders.textChanged.connect(self._on_target_orders_changed)

        self.spin_order_width = QDoubleSpinBox()
        self.spin_order_width.setDecimals(2)
        self.spin_order_width.setRange(0.01, 2.0)
        self.spin_order_width.setSingleStep(0.05)
        self.spin_order_width.setValue(self._get_val("order_width", 0.2, float))
        self.spin_order_width.valueChanged.connect(lambda v: self._set_val("order_width", v))

        orders_group = RibbonGroup("Live Orders", tooltip="Orders drawn in the active plot (not the batch)")
        orders_group.add_fields([("Target Orders", self.edit_target_orders),
                                 ("Order Width", self.spin_order_width)])
        layout.addWidget(orders_group)
        layout.addWidget(vertical_separator())

        # -- Tacho Tracking --
        self.spin_tracking_step = QDoubleSpinBox()
        self.spin_tracking_step.setDecimals(1)
        self.spin_tracking_step.setRange(1.0, 5000.0)
        self.spin_tracking_step.setValue(self._get_val("order_tracking_step", 50.0, float))
        self.spin_tracking_step.valueChanged.connect(lambda v: self._set_val("order_tracking_step", v))

        self.combo_direction = QComboBox()
        self.combo_direction.addItems(["Up (Run-Up)", "Down (Run-Down)", "Any (Both)"])
        self.combo_direction.setCurrentText(self._get_val("order_direction", "Up (Run-Up)"))
        self.combo_direction.currentTextChanged.connect(lambda v: self._set_val("order_direction", v))

        self.spin_hysteresis = QDoubleSpinBox()
        self.spin_hysteresis.setDecimals(1)
        self.spin_hysteresis.setRange(0.0, 5000.0)
        self.spin_hysteresis.setValue(self._get_val("order_hysteresis", 10.0, float))
        self.spin_hysteresis.valueChanged.connect(lambda v: self._set_val("order_hysteresis", v))

        tracking_group = RibbonGroup("Tacho Tracking", tooltip="RPM step and sweep direction the tacho is followed at")
        tracking_group.add_fields([
            ("Step [RPM]", self.spin_tracking_step), ("Sweep", self.combo_direction),
            ("Hysteresis [RPM]", self.spin_hysteresis),
        ])
        layout.addWidget(tracking_group)
        layout.addWidget(vertical_separator())

        # -- Options --
        # Built before cb_remove_dc (the ready widget), so _after_push finds it.
        # Not an OrderTrackingConfig field: that would change every stored order
        # cut's cache identity (ADR §1.141 point 9).
        self.cb_overall_level = QCheckBox("Overall Level + Residual")
        self.cb_overall_level.setToolTip(
            "Also draw the Overall Level (F min 10 Hz, Full Bandwidth) from the same computation")
        self.cb_overall_level.setChecked(
            str(self._get_val("order_overall_level", "false")).lower() == "true")
        self.cb_overall_level.toggled.connect(lambda v: self._set_val("order_overall_level", v))

        self.cb_remove_dc = QCheckBox("Remove DC Offset")
        saved_dc = str(self._get_val("order_remove_dc", "true")).lower() == "true"
        self.cb_remove_dc.setChecked(saved_dc)
        self.cb_remove_dc.toggled.connect(lambda v: self._set_val("order_remove_dc", v))

        options_group = RibbonGroup("Options")
        options_group.add_column(self.cb_remove_dc, self.cb_overall_level)
        layout.addWidget(options_group)


        build_tab_layout(self, layout, "order_tracking")

        self._push_dsp_config()

    def _after_push(self):
        self.app_context.order_tracking_overall_level = self.cb_overall_level.isChecked()

    def _on_target_orders_changed(self, text: str) -> None:
        parsed = parse_orders_text(text)
        if parsed is None or not parsed:
            self.edit_target_orders.setStyleSheet("border: 1px solid #d9534f;")
            self.edit_target_orders.setToolTip(
                "Invalid orders: enter positive numbers with decimal dot (.), "
                "separated by commas or semicolons."
            )
            return
        self.edit_target_orders.setStyleSheet("")
        self.edit_target_orders.setToolTip(self._default_orders_tooltip)
        self._last_valid_orders = parsed
        self._set_val("order_targets", text)

    def get_save_dsp_config(self) -> OrderTrackingConfig:
        """Same FFT/tracking parameters as get_dsp_config(), but with the orders
        to save (kept in QSettings by the Compute Result Set dialog) instead of
        the orders shown in the live plot."""
        config = self.get_dsp_config()

        raw_orders = self._get_val("order_save_targets", "1, 2")
        parsed = parse_orders_text(str(raw_orders))
        config.orders_to_extract = parsed if parsed else [1.0]
        return config

    def get_dsp_config(self) -> OrderTrackingConfig:
        """Translates UI selections into standard DTOs for the DSP layer."""
        w_map = {"Hanning": "hann", "Hamming": "hamming", "Blackman": "blackman", "Flat-top": "flattop",
                 "Rectangular": "boxcar"}
        dir_map = {"Up (Run-Up)": "up", "Down (Run-Down)": "down", "Any (Both)": "any"}

        parsed = parse_orders_text(self.edit_target_orders.text())
        orders = parsed if parsed else getattr(self, "_last_valid_orders", [1.0])

        return OrderTrackingConfig(
            orders_to_extract=orders if orders else [1.0],
            order_width=float(self.spin_order_width.value()),
            fft_size=int(self.combo_fft_size.currentText()),
            window_type=w_map.get(self.combo_window_type.currentText(), "hann"),
            spectrum_format="linear",
            amplitude_mode=self.combo_amplitude_mode.currentText().lower(),
            step=float(self.spin_tracking_step.value()),
            direction=dir_map.get(self.combo_direction.currentText(), "up"),
            hysteresis=float(self.spin_hysteresis.value()),
            remove_dc=self.cb_remove_dc.isChecked()
        )
