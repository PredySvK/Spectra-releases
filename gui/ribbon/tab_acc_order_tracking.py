# =====================================================================
# FILE: gui/ribbon/tab_acc_order_tracking.py
# =====================================================================
"""
Ribbon tab for acceleration order tracking.

Left to right: Refresh, then RibbonGroups -- Spectrum, Tacho Tracking, View, Live
Orders (what the active plot shows), Options -- then Batch, then Help. The
orders a *batch* extracts are asked in the Compute Result Set dialog, not here;
the batch swaps them into get_dsp_config() itself (#770).
Generates an OrderTrackingConfig DTO for the DSP backend.
"""
from typing import List

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QHBoxLayout, QLineEdit

from core.dsp_configs import OrderTrackingConfig
from gui.appearance import APP_TOKENS
from gui.ribbon.ribbon_dsp_tab import RibbonDspTab
from gui.ribbon.ribbon_widgets import RibbonGroup, build_tab_layout, make_refresh_split_button, stack_buttons, vertical_separator
from gui.ribbon.save_section import ComputeResultSetButton
from view_models.analysis_kinds import ANALYSIS_ORDERS
from view_models.evaluation import parse_orders_text

_DEFAULTS = OrderTrackingConfig()


class TabAccOrderTracking(RibbonDspTab):
    sig_display_settings_changed = Signal()
    _settings_attr = "order_tracking_settings"
    _ready_widget_name = "cb_remove_dc"
    _analysis_kind = ANALYSIS_ORDERS

    def _on_display_setting_changed(self, _val: str = ""):
        self._emit_display_settings_changed()

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
        self.combo_fft_size = self._build_field_combo("fft_size")
        self.combo_window_type = self._build_field_combo("window_type")

        spectrum_group = RibbonGroup("Spectrum", tooltip="Block size and window of the order FFT")
        spectrum_group.add_fields([
            ("FFT Size", self.combo_fft_size), ("Window", self.combo_window_type),
        ])
        layout.addWidget(spectrum_group)
        layout.addWidget(vertical_separator())

        # -- Tacho Tracking -- rpm only; its Tracking range is its own, not the
        # Spectrogram's, and the Overall Level + Residual curves follow it (#806).
        layout.addWidget(self._build_tracking_sweep("order").group)
        layout.addWidget(vertical_separator())

        # -- View --
        self.combo_amplitude_mode = self._build_field_combo("amplitude_mode")
        self.combo_amplitude_mode.currentTextChanged.connect(self._on_display_setting_changed)

        view_group = RibbonGroup("View", tooltip="Display amplitude mode")
        view_group.add_fields([("Amplitude", self.combo_amplitude_mode)])
        layout.addWidget(view_group)
        layout.addWidget(vertical_separator())

        # -- Live Orders (what the active plot shows) --
        self._last_valid_orders: List[float] = list(_DEFAULTS.orders_to_extract)
        self.edit_target_orders = QLineEdit()
        self.edit_target_orders.setFixedWidth(90)
        self._default_orders_tooltip = (
            "Orders shown in the active plot, e.g. 1. "
            "Enter several at once separated by commas or semicolons, e.g. 1, 2, 4.5"
        )
        # Saved only once it parses, so the tab saves it itself.
        self._bind_field("orders_to_extract", self.edit_target_orders, save_on_change=False)
        self._show_target_orders_validity()
        self.edit_target_orders.textChanged.connect(self._on_target_orders_changed)

        self.spin_order_width = QDoubleSpinBox()
        self.spin_order_width.setDecimals(2)
        self.spin_order_width.setRange(0.01, 2.0)
        self.spin_order_width.setSingleStep(0.05)
        self._bind_field("order_width", self.spin_order_width)

        orders_group = RibbonGroup("Live Orders", tooltip="Orders drawn in the active plot (not the batch)")
        orders_group.add_fields([("Target Orders", self.edit_target_orders),
                                 ("Order Width", self.spin_order_width)])
        layout.addWidget(orders_group)
        layout.addWidget(vertical_separator())

        # -- Options --
        # Built before cb_remove_dc (the ready widget), so _after_push finds it.
        # Not an OrderTrackingConfig field: that would change every stored order
        # cut's cache identity.
        self.cb_overall_level = QCheckBox("Overall Level + Residual")
        self.cb_overall_level.setToolTip(
            "Also draw the Overall Level (F min 10 Hz, Full Bandwidth) from the same computation")
        self._bind_field("overall_level", self.cb_overall_level)

        self.cb_remove_dc = QCheckBox("Remove DC Offset")
        self._bind_field("remove_dc", self.cb_remove_dc)

        options_group = RibbonGroup("Options")
        options_group.add_column(self.cb_remove_dc, self.cb_overall_level)
        layout.addWidget(options_group)


        build_tab_layout(self, layout, "order_tracking")

        self._push_dsp_config()

    def _after_push(self):
        self.app_context.order_tracking_overall_level = self.cb_overall_level.isChecked()

    def _sync_dependent_widgets(self):
        self._show_target_orders_validity()

    def _show_target_orders_validity(self) -> bool:
        """Mark the Target Orders field valid or not; a valid one becomes the last valid orders."""
        parsed = parse_orders_text(self.edit_target_orders.text())
        if parsed is None or not parsed:
            self.edit_target_orders.setStyleSheet(f"border: 1px solid {APP_TOKENS.input_error};")
            self.edit_target_orders.setToolTip(
                "Invalid orders: enter positive numbers with decimal dot (.), "
                "separated by commas or semicolons."
            )
            return False
        self.edit_target_orders.setStyleSheet("")
        self.edit_target_orders.setToolTip(self._default_orders_tooltip)
        self._last_valid_orders = parsed
        return True

    def _on_target_orders_changed(self, text: str) -> None:
        if self._show_target_orders_validity():
            self._save_field("orders_to_extract", text)

    def get_dsp_config(self) -> OrderTrackingConfig:
        """Translates UI selections into standard DTOs for the DSP layer."""
        parsed = parse_orders_text(self.edit_target_orders.text())
        orders = parsed if parsed else getattr(self, "_last_valid_orders", None)

        return OrderTrackingConfig(
            orders_to_extract=orders if orders else list(_DEFAULTS.orders_to_extract),
            order_width=float(self.spin_order_width.value()),
            fft_size=self._resolve_choice_value("fft_size", self.combo_fft_size),
            window_type=self._resolve_choice_value("window_type", self.combo_window_type),
            amplitude_mode=self._resolve_choice_value("amplitude_mode", self.combo_amplitude_mode),
            remove_dc=self.cb_remove_dc.isChecked(),
            **self.tracking_sweep.resolve_config_fields(),
        )
