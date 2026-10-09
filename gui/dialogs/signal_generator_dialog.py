# =====================================================================
# FILE: gui/dialogs/signal_generator_dialog.py
# =====================================================================
"""
Dumb UI View for defining synthetic multi-channel NVH signals.
Strictly handles layout, widgets, and user inputs. Emits signals to the Controller.
Mathematical imports and complex preview logic have been stripped out.
All internal documentation strings and variable labels are written in English.

The component editor mirrors the generation engine's contract
(io_modules/signal_generation/signal_generation_engine.compose_vibration_signal):
every optional per-component key the engine understands -- amp_end (warm-up
drift), mod_order / mod_depth (bearing-fault sidebands) -- has a field here, and
the four stochastic component types (White / Pink / Brown Noise, Resonance) are
in the type list. A field is only shown for the component types it applies to so
the row does not become a wall of greyed-out spinboxes.
"""

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QDoubleSpinBox, QSpinBox, QComboBox, QTableWidget, QCheckBox,
    QTableWidgetItem, QPushButton, QHeaderView, QTabWidget, QWidget, QLineEdit,
    QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator

from gui.dialogs.dialog_state import remember_dialog_geometry
from gui.dialogs.library_preset_dialog import LibraryPresetDialog

# Component types that carry a swept/fixed tone (value = order or Hz) and so
# accept amplitude drift and sideband modulation. Everything else is broadband.
_TONE_TYPES = ("Order", "Sine signal", "Chirp")
# Types that expose the SDOF resonance pair (centre frequency + Q).
_RESONANCE_TYPES = ("Order", "Resonance", "Chirp")
_ALL_COMPONENT_TYPES = ("Order", "Sine signal", "White Noise",
                        "Pink Noise", "Brown Noise", "Resonance", "Chirp")

_TABLE_COLUMNS = ("Type", "Value", "Amp", "Amp End",
                  "Mod Ord", "Mod Dep", "Res Hz", "Amplif")


def _fmt(value: float) -> str:
    """Compact number for a table cell: 1.0 -> '1', 0.230 -> '0.23'."""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text if text else "0"


class CleanDoubleSpinBox(QDoubleSpinBox):
    def textFromValue(self, val: float) -> str:
        text = super().textFromValue(val)
        if self.locale().decimalPoint() in text:
            text = text.rstrip('0').rstrip(self.locale().decimalPoint())
        return text if text else "0"


class ChannelTab(QWidget):
    """
    One channel's editor: label + unit, the component input row with its
    per-type show/hide, and the component table. Owns its widgets as real
    attributes (edit_name / combo_unit / table were monkey-patched onto a bare
    QWidget before). Emits `changed` on any edit so the dialog refreshes the
    live preview, and `name_changed` so the dialog can retitle the tab.
    """

    changed = Signal()
    name_changed = Signal(str)

    def __init__(self, default_name: str, unit: str = "g", parent=None):
        super().__init__(parent)
        # Guards the burst of itemChanged signals while a row is being written,
        # so a single add / preset load emits `changed` once, not per cell.
        self._is_updating = False
        self._amp_end_follows_amp = True
        self._is_syncing_amp_end = False

        layout = QVBoxLayout(self)

        # 1. Channel naming and units
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Channel Label:"))
        self.edit_name = QLineEdit(default_name)
        self.edit_name.textChanged.connect(self.name_changed)
        header_layout.addWidget(self.edit_name)

        header_layout.addWidget(QLabel("Unit:"))
        self.combo_unit = QComboBox()
        self.combo_unit.addItems(["g", "m/s2", "mm/s", "mm", "Pa", "V", "N", "lbf"])
        if unit and self.combo_unit.findText(unit) >= 0:
            self.combo_unit.setCurrentText(unit)
        self.combo_unit.currentTextChanged.connect(self._emit_changed)
        header_layout.addWidget(self.combo_unit)
        layout.addLayout(header_layout)

        # 2. Parameters input box -- fields appear only for the types they apply
        # to, and the eight fields are split over two rows so the box never
        # forces the dialog wider than the screen.
        def _num(decimals, lo, hi, value, step=None):
            box = CleanDoubleSpinBox()
            box.setDecimals(decimals)
            box.setRange(lo, hi)
            box.setValue(value)
            if step is not None:
                box.setSingleStep(step)
            box.setMaximumWidth(90)
            return box

        self._combo_type = QComboBox()
        self._combo_type.setObjectName("ComponentTypeCombo")
        self._combo_type.addItems(list(_ALL_COMPONENT_TYPES))

        lbl_val_name = QLabel("Order [-]:")
        self._spin_val = _num(3, 0.0, 100000.0, 1)
        lbl_amp = QLabel("Amp:")
        self._spin_amp = _num(3, 0.0, 1_000_000.0, 1)
        lbl_amp_end = QLabel("Amp End:")
        self._spin_amp_end = _num(3, 0.0, 1_000_000.0, 1)
        self._spin_amp.valueChanged.connect(self._sync_amp_end)
        self._spin_amp_end.valueChanged.connect(self._set_amp_end_explicit)
        self._spin_amp_end.lineEdit().textEdited.connect(self._set_amp_end_explicit)
        lbl_mod_order = QLabel("Mod Order:")
        self._spin_mod_order = _num(3, 0.0, 100000.0, 0)
        lbl_mod_depth = QLabel("Mod Depth:")
        self._spin_mod_depth = _num(3, 0.0, 1.0, 0, step=0.05)
        lbl_res_f = QLabel("Res Freq [Hz]:")
        self._spin_res_f = _num(1, 0.0, 100000.0, 0)
        lbl_res_a = QLabel("Amplification:")
        self._spin_res_a = _num(1, 0.0, 100.0, 1)

        param_row1 = QHBoxLayout()
        for w in (self._combo_type, lbl_val_name, self._spin_val, lbl_amp,
                  self._spin_amp, lbl_amp_end, self._spin_amp_end):
            param_row1.addWidget(w)
        param_row1.addStretch()
        layout.addLayout(param_row1)

        param_row2 = QHBoxLayout()
        for w in (lbl_mod_order, self._spin_mod_order, lbl_mod_depth,
                  self._spin_mod_depth, lbl_res_f, self._spin_res_f,
                  lbl_res_a, self._spin_res_a):
            param_row2.addWidget(w)
        param_row2.addStretch()
        layout.addLayout(param_row2)

        # (widget, label, applicable types) -- drives per-type show/hide.
        field_specs = [
            (self._spin_val, lbl_val_name, _TONE_TYPES),
            (self._spin_amp, lbl_amp, _ALL_COMPONENT_TYPES),
            (self._spin_amp_end, lbl_amp_end, _TONE_TYPES),
            (self._spin_mod_order, lbl_mod_order, _TONE_TYPES),
            (self._spin_mod_depth, lbl_mod_depth, _TONE_TYPES),
            (self._spin_res_f, lbl_res_f, _RESONANCE_TYPES),
            (self._spin_res_a, lbl_res_a, ("Order", "Resonance")),
        ]

        def _on_type_changed(curr_text):
            lbl_val_name.setText("Freq [Hz]:" if curr_text in ("Sine signal", "Chirp") else "Order [-]:")
            lbl_res_f.setText("End Freq [Hz]:" if curr_text == "Chirp" else "Res Freq [Hz]:")
            lbl_res_a.setText("Q factor:" if curr_text == "Resonance" else "Amplification:")
            for widget, label, types in field_specs:
                visible = curr_text in types
                widget.setVisible(visible)
                label.setVisible(visible)

        self._combo_type.currentTextChanged.connect(_on_type_changed)
        _on_type_changed(self._combo_type.currentText())

        # 3. Component action buttons
        btn_layout = QHBoxLayout()
        btn_remove = QPushButton("❌ Remove Component")
        btn_add = QPushButton("➕ Add Component")
        btn_add.setObjectName("AddComponentButton")
        btn_layout.addWidget(btn_remove)
        btn_layout.addWidget(btn_add)
        layout.addLayout(btn_layout)

        # 4. Table
        self.table = QTableWidget(0, len(_TABLE_COLUMNS))
        self.table.setObjectName("ComponentTable")
        self.table.setHorizontalHeaderLabels(list(_TABLE_COLUMNS))
        header = self.table.horizontalHeader()
        # Small floor so eight columns always share the width evenly instead of
        # the header text setting a large per-column minimum and spilling the
        # last columns off the right edge.
        header.setMinimumSectionSize(50)
        header.setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemChanged.connect(self._emit_changed)
        layout.addWidget(self.table)

        btn_remove.clicked.connect(self._remove_selected_rows)
        btn_add.clicked.connect(self._add_from_inputs)

    # ---- editing -----------------------------------------------------

    def _sync_amp_end(self, amplitude: float):
        """Keep the default end amplitude equal to Amp until edited directly."""
        if not self._amp_end_follows_amp:
            return
        self._is_syncing_amp_end = True
        self._spin_amp_end.setValue(amplitude)
        self._is_syncing_amp_end = False

    def _set_amp_end_explicit(self, *_):
        """Preserve a user-selected Amp End when Amp changes later."""
        if not self._is_syncing_amp_end:
            self._amp_end_follows_amp = False

    def _emit_changed(self, *_):
        if not self._is_updating:
            self.changed.emit()

    def _add_from_inputs(self):
        ctype = self._combo_type.currentText()
        comp = {"type": ctype, "amplitude": self._spin_amp.value()}
        if ctype in _TONE_TYPES:
            comp["value"] = self._spin_val.value()
            if self._spin_amp_end.value() != self._spin_amp.value():
                comp["amp_end"] = self._spin_amp_end.value()
            if self._spin_mod_order.value() > 0 and self._spin_mod_depth.value() > 0:
                comp["mod_order"] = self._spin_mod_order.value()
                comp["mod_depth"] = self._spin_mod_depth.value()
        if ctype in _RESONANCE_TYPES:
            comp["res_freq"] = self._spin_res_f.value()
            if ctype != "Chirp":  # engine ignores Amplification for Chirp
                comp["res_amp"] = self._spin_res_a.value()
        self.add_component(comp)

    def _remove_selected_rows(self):
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self.changed.emit()

    def add_component(self, comp: dict):
        """
        Writes one component dict into a new table row. The single place a row
        is created, so the add button and a loaded preset produce identical
        cells. Cells that do not apply to the type are left blank rather than
        zeroed -- a blank Res Freq means "no resonance", 0.0 would too but reads
        as a real setting the user forgot to fill in.
        """
        ctype = comp["type"]
        is_tone = ctype in _TONE_TYPES
        is_res = ctype in _RESONANCE_TYPES

        def opt(key):
            return _fmt(comp[key]) if key in comp else ""

        cells = [
            ctype,
            _fmt(comp.get("value", 0.0)) if is_tone else "",
            _fmt(comp.get("amplitude", 0.0)),
            opt("amp_end") if is_tone else "",
            opt("mod_order") if is_tone else "",
            opt("mod_depth") if is_tone else "",
            _fmt(comp.get("res_freq", 0.0)) if is_res else "",
            _fmt(comp.get("res_amp", 0.0)) if is_res else "",
        ]

        was_updating = self._is_updating
        self._is_updating = True
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, text in enumerate(cells):
            self.table.setItem(r, col, QTableWidgetItem(text))
        self._is_updating = was_updating
        if not self._is_updating:
            self.changed.emit()

    def set_components(self, components: list):
        self.table.setRowCount(0)
        for comp in components:
            self.add_component(comp)

    # ---- reading back ----------------------------------------------

    @staticmethod
    def _safe_float(string_val: str) -> float:
        """Parse a table number with either decimal dot or decimal comma."""
        try:
            text = string_val.strip()
            if text.count(",") == 1 and "." not in text:
                text = text.replace(",", ".")
            return float(text)
        except (ValueError, AttributeError, TypeError):
            return 0.0

    def _row_component(self, r: int) -> dict:
        """One table row -> a component dict in the engine's contract."""
        def cell(col):
            item = self.table.item(r, col)
            return item.text().strip() if item is not None else ""

        comp = {
            "type": cell(0),
            "value": self._safe_float(cell(1)),
            "amplitude": self._safe_float(cell(2)),
            "res_freq": self._safe_float(cell(6)),
            "res_amp": self._safe_float(cell(7)),
        }
        # Optional keys: emitted only when the cell carries a meaningful value,
        # so a preset round-trips and the engine sees exactly what it would from
        # signal_library (amp_end == amplitude and mod_* == 0 are engine no-ops).
        amp_end = cell(3)
        if amp_end and self._safe_float(amp_end) != comp["amplitude"]:
            comp["amp_end"] = self._safe_float(amp_end)
        mod_order, mod_depth = cell(4), cell(5)
        if self._safe_float(mod_order) > 0 and self._safe_float(mod_depth) > 0:
            comp["mod_order"] = self._safe_float(mod_order)
            comp["mod_depth"] = self._safe_float(mod_depth)
        return comp

    def components(self) -> list:
        return [self._row_component(r) for r in range(self.table.rowCount())]


class SignalGeneratorDialog(QDialog):
    sig_parameters_changed = Signal()

    def __init__(self, parent=None, settings=None):
        super().__init__(parent)
        self._is_updating = False
        self.setWindowTitle("Signal Generator")

        self.init_ui()
        self.add_channel_tab("Channel_1")

        # Open at a size that fits a 1080p screen and shows the whole eight-column
        # table without a horizontal scrollbar; can be shrunk further (the table
        # stays stretched, just narrower).
        self.setMinimumSize(1100, 680)
        # Remembered across restarts; cleared by Settings > Reset Layout / Reset All.
        remember_dialog_geometry(self, settings, "signal_generator", default_size=(1400, 860))

    def _param_changed(self, *_):
        """Single funnel for every 'a widget changed' wire, muted during a bulk load."""
        if not self._is_updating:
            self.sig_parameters_changed.emit()

    def init_ui(self):
        master_layout = QVBoxLayout(self)
        split_layout = QHBoxLayout()
        master_layout.addLayout(split_layout, stretch=1)

        split_layout.addLayout(self._build_controls_column(), stretch=5)
        split_layout.addLayout(self._build_preview_column(), stretch=4)
        master_layout.addLayout(self._build_action_row())

    # ---- init_ui sections (pure widget construction, no behaviour) --------

    def _build_controls_column(self) -> QVBoxLayout:
        """Left column: global + tacho settings, then the per-channel tabs."""
        left_layout = QVBoxLayout()
        left_layout.addWidget(self._build_global_settings_group())
        left_layout.addWidget(self._build_tacho_settings_group())

        # Channels Tab Widget & Management layout
        self.tabs_channels = QTabWidget()
        self.tabs_channels.setObjectName("ChannelTabs")
        left_layout.addWidget(self.tabs_channels)

        chan_manage_layout = QHBoxLayout()
        self.btn_remove_tab = QPushButton("❌ Remove Current Channel")
        self.btn_remove_tab.clicked.connect(self.remove_current_channel_tab)
        chan_manage_layout.addWidget(self.btn_remove_tab)

        self.btn_add_tab = QPushButton("➕ Add New Channel")
        self.btn_add_tab.clicked.connect(lambda: self.add_channel_tab(f"Channel_{self.tabs_channels.count() + 1}"))
        chan_manage_layout.addWidget(self.btn_add_tab)
        left_layout.addLayout(chan_manage_layout)

        # Visual Separator under Channel Management
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("margin-top: 10px; margin-bottom: 5px;")
        left_layout.addWidget(line)
        return left_layout

    def _build_global_settings_group(self) -> QGroupBox:
        group_global = QGroupBox("Global Settings")
        group_global.setObjectName("GlobalSettingsGroup")
        layout_global = QHBoxLayout(group_global)

        layout_global.addWidget(QLabel("Duration [s]:"))
        self.spin_duration = CleanDoubleSpinBox()
        self.spin_duration.setDecimals(2)
        self.spin_duration.setRange(0.1, 1000.0)
        self.spin_duration.setValue(30)
        self.spin_duration.valueChanged.connect(self._param_changed)
        layout_global.addWidget(self.spin_duration)

        layout_global.addWidget(QLabel("Sampling [Hz]:"))
        self.spin_fs = QSpinBox()
        self.spin_fs.setRange(100, 102400)
        self.spin_fs.setValue(10000)
        self.spin_fs.valueChanged.connect(self._param_changed)
        layout_global.addWidget(self.spin_fs)

        # Blank = draw a fresh seed at export time and log it. A fixed value
        # makes the record (and its noise components) reproducible byte for byte.
        layout_global.addWidget(QLabel("Seed:"))
        self.edit_seed = QLineEdit()
        self.edit_seed.setPlaceholderText("random")
        self.edit_seed.setValidator(QIntValidator(0, 2_147_483_647, self))
        self.edit_seed.setMaximumWidth(120)
        self.edit_seed.textChanged.connect(self._param_changed)
        layout_global.addWidget(self.edit_seed)

        layout_global.addStretch()

        self.btn_load_preset = QPushButton("📂 Load Preset…")
        self.btn_load_preset.clicked.connect(self._open_preset_picker)
        layout_global.addWidget(self.btn_load_preset)

        return group_global

    def _build_tacho_settings_group(self) -> QGroupBox:
        group_rpm = QGroupBox("Tacho Settings")
        group_rpm.setObjectName("TachoSettingsGroup")
        layout_rpm = QVBoxLayout(group_rpm)

        row1_rpm = QHBoxLayout()
        row1_rpm.addWidget(QLabel("Start:"))
        self.spin_rpm_start = QSpinBox()
        self.spin_rpm_start.setRange(0, 100000)
        self.spin_rpm_start.setValue(0)
        self.spin_rpm_start.valueChanged.connect(self._param_changed)
        row1_rpm.addWidget(self.spin_rpm_start)

        row1_rpm.addWidget(QLabel("Stop:"))
        self.spin_rpm_stop = QSpinBox()
        self.spin_rpm_stop.setRange(0, 100000)
        self.spin_rpm_stop.setValue(35000)
        self.spin_rpm_stop.valueChanged.connect(self._param_changed)
        row1_rpm.addWidget(self.spin_rpm_stop)

        row1_rpm.addWidget(QLabel("Direction:"))
        self.combo_direction = QComboBox()
        self.combo_direction.setObjectName("TachoDirectionCombo")
        self.combo_direction.addItems(["Ramp Up", "Ramp Down", "Ramp Up & Down"])
        self.combo_direction.currentTextChanged.connect(self._param_changed)
        row1_rpm.addWidget(self.combo_direction)
        row1_rpm.addStretch()
        layout_rpm.addLayout(row1_rpm)

        row2_rpm = QHBoxLayout()
        self.chk_plateaus = QCheckBox("Enable Plateaus")
        self.chk_plateaus.setObjectName("PlateausCheckbox")
        self.chk_plateaus.stateChanged.connect(self._param_changed)
        row2_rpm.addWidget(self.chk_plateaus)

        row2_rpm.addWidget(QLabel("Steps:"))
        self.spin_plateaus = QSpinBox()
        self.spin_plateaus.setRange(1, 50)
        self.spin_plateaus.setValue(3)
        self.spin_plateaus.setEnabled(False)
        self.spin_plateaus.valueChanged.connect(self._param_changed)
        row2_rpm.addWidget(self.spin_plateaus)

        row2_rpm.addWidget(QLabel("Plateau Ratio (0-1):"))
        self.spin_plateau_ratio = CleanDoubleSpinBox()
        self.spin_plateau_ratio.setDecimals(2)
        self.spin_plateau_ratio.setRange(0.01, 0.99)
        self.spin_plateau_ratio.setValue(0.5)
        self.spin_plateau_ratio.setSingleStep(0.1)
        self.spin_plateau_ratio.setEnabled(False)
        self.spin_plateau_ratio.valueChanged.connect(self._param_changed)
        row2_rpm.addWidget(self.spin_plateau_ratio)
        row2_rpm.addStretch()
        layout_rpm.addLayout(row2_rpm)

        def _toggle_plateaus(state):
            is_checked = state == Qt.CheckState.Checked.value
            self.spin_plateaus.setEnabled(is_checked)
            self.spin_plateau_ratio.setEnabled(is_checked)

        self.chk_plateaus.stateChanged.connect(_toggle_plateaus)

        # Tacho-channel acquisition noise. Degrades ONLY the tacho column written
        # to disk -- the vibration is always synthesized from the clean profile
        # (see apply_tacho_noise). Lets a test plant "shaft was smooth, tacho
        # was not" and check the order tracker survives it.
        self.chk_tacho_noise = QCheckBox("Tacho Noise")
        self.chk_tacho_noise.setObjectName("TachoNoiseCheckbox")
        self.chk_tacho_noise.stateChanged.connect(self._param_changed)

        self.spin_tn_std = CleanDoubleSpinBox()
        self.spin_tn_std.setDecimals(1)
        self.spin_tn_std.setRange(0.0, 5000.0)
        self.spin_tn_std.setMaximumWidth(90)
        self.spin_tn_std.valueChanged.connect(self._param_changed)

        self.combo_tn_region = QComboBox()
        self.combo_tn_region.addItems(["all", "start", "end"])
        self.combo_tn_region.currentTextChanged.connect(self._param_changed)

        self.spin_tn_region_frac = CleanDoubleSpinBox()
        self.spin_tn_region_frac.setDecimals(2)
        self.spin_tn_region_frac.setRange(0.01, 1.0)
        self.spin_tn_region_frac.setValue(1.0)
        self.spin_tn_region_frac.setSingleStep(0.05)
        self.spin_tn_region_frac.setMaximumWidth(90)
        self.spin_tn_region_frac.valueChanged.connect(self._param_changed)

        self.spin_tn_dropout_rate = CleanDoubleSpinBox()
        self.spin_tn_dropout_rate.setDecimals(6)
        self.spin_tn_dropout_rate.setRange(0.0, 1.0)
        self.spin_tn_dropout_rate.setSingleStep(0.0001)
        self.spin_tn_dropout_rate.setMaximumWidth(110)
        self.spin_tn_dropout_rate.valueChanged.connect(self._param_changed)

        self.spin_tn_dropout_gain = CleanDoubleSpinBox()
        self.spin_tn_dropout_gain.setDecimals(2)
        self.spin_tn_dropout_gain.setRange(0.0, 1.0)
        self.spin_tn_dropout_gain.setValue(0.5)
        self.spin_tn_dropout_gain.setSingleStep(0.05)
        self.spin_tn_dropout_gain.setMaximumWidth(90)
        self.spin_tn_dropout_gain.valueChanged.connect(self._param_changed)

        row3_rpm = QHBoxLayout()
        for w in (self.chk_tacho_noise, QLabel("Jitter [rpm]:"), self.spin_tn_std,
                  QLabel("Region:"), self.combo_tn_region,
                  QLabel("Region frac:"), self.spin_tn_region_frac):
            row3_rpm.addWidget(w)
        row3_rpm.addStretch()
        layout_rpm.addLayout(row3_rpm)

        row4_rpm = QHBoxLayout()
        for w in (QLabel("Dropout rate:"), self.spin_tn_dropout_rate,
                  QLabel("Dropout gain:"), self.spin_tn_dropout_gain):
            row4_rpm.addWidget(w)
        row4_rpm.addStretch()
        layout_rpm.addLayout(row4_rpm)

        self._tacho_noise_widgets = (
            self.spin_tn_std, self.combo_tn_region, self.spin_tn_region_frac,
            self.spin_tn_dropout_rate, self.spin_tn_dropout_gain,
        )

        def _toggle_tacho_noise(state):
            on = state == Qt.CheckState.Checked.value
            for w in self._tacho_noise_widgets:
                w.setEnabled(on)

        self.chk_tacho_noise.stateChanged.connect(_toggle_tacho_noise)
        _toggle_tacho_noise(0)

        return group_rpm

    def _build_preview_column(self) -> QVBoxLayout:
        """Right column: tacho + vibration preview plots and view settings."""
        right_layout = QVBoxLayout()

        # Floor on the preview width so the plots never collapse to a sliver
        # when the controls column is asking for room.
        self.rpm_plot = pg.PlotWidget(title="Tacho Profile")
        self.rpm_plot.setObjectName("TachoProfilePlot")
        self.rpm_plot.setMinimumWidth(340)
        self.rpm_plot.showGrid(x=True, y=True)
        self.rpm_plot.setLabel('bottom', 'Time', 's')
        self.rpm_plot.setLabel('left', 'Speed', 'RPM')
        right_layout.addWidget(self.rpm_plot)

        self.vib_plot = pg.PlotWidget(title="Active Channel Vibration Preview")
        self.vib_plot.setObjectName("VibrationPreviewPlot")
        self.vib_plot.setMinimumWidth(340)
        self.vib_plot.showGrid(x=True, y=True)
        self.vib_plot.setLabel('bottom', 'Time', 's')
        self.vib_plot.setLabel('left', 'Amplitude', 'g')
        right_layout.addWidget(self.vib_plot)

        group_preview = QGroupBox("View Settings")
        group_preview.setObjectName("ViewSettingsGroup")
        layout_preview = QHBoxLayout(group_preview)

        layout_preview.addWidget(QLabel("X-Axis:"))
        self.combo_x_axis = QComboBox()
        self.combo_x_axis.addItems(["Time", "RPM"])
        self.combo_x_axis.currentTextChanged.connect(self._param_changed)
        layout_preview.addWidget(self.combo_x_axis)

        layout_preview.addWidget(QLabel("Start [s]:"))
        self.spin_prev_start = CleanDoubleSpinBox()
        self.spin_prev_start.setDecimals(3)
        # Same upper bound as spin_duration: the default 0..99.99 silently clips
        # "View All" on a longer record to its first 99.99 s (audit 02, S11/11.6).
        self.spin_prev_start.setRange(0.0, 1000.0)
        self.spin_prev_start.setValue(0)
        self.spin_prev_start.valueChanged.connect(self._param_changed)
        layout_preview.addWidget(self.spin_prev_start)

        layout_preview.addWidget(QLabel("End [s]:"))
        self.spin_prev_end = CleanDoubleSpinBox()
        self.spin_prev_end.setDecimals(3)
        self.spin_prev_end.setRange(0.0, 1000.0)
        self.spin_prev_end.setValue(30)
        self.spin_prev_end.valueChanged.connect(self._param_changed)
        layout_preview.addWidget(self.spin_prev_end)

        self.btn_view_all = QPushButton("View All")
        layout_preview.addWidget(self.btn_view_all)

        self.btn_view_4p = QPushButton("View 4 period")
        layout_preview.addWidget(self.btn_view_4p)

        right_layout.addWidget(group_preview)
        return right_layout

    def _build_action_row(self) -> QHBoxLayout:
        action_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        action_layout.addWidget(self.btn_cancel)

        action_layout.addStretch()

        action_layout.addWidget(QLabel("Export Format:"))
        self.combo_format = QComboBox()
        self.combo_format.addItems(["ASC (Siemens Testlab)"])
        action_layout.addWidget(self.combo_format)

        self.btn_generate = QPushButton("Export Signal")
        self.btn_generate.setObjectName("ExportSignalButton")
        self.btn_generate.setStyleSheet(
            "background-color: #2b579a; color: white; font-weight: bold; height: 35px; padding: 0 25px;")
        self.btn_generate.clicked.connect(self.accept)
        action_layout.addWidget(self.btn_generate)
        return action_layout

    # ---- per-channel tabs ------------------------------------------

    def add_channel_tab(self, default_name: str, unit: str = "g", components: list = None):
        tab = ChannelTab(default_name, unit)
        tab.changed.connect(self._param_changed)
        tab.name_changed.connect(
            lambda txt, t=tab: self.tabs_channels.setTabText(self.tabs_channels.indexOf(t), txt))
        self.tabs_channels.addTab(tab, default_name)

        if components is None:
            components = [{"type": "Order", "value": 1.0, "amplitude": 1.0}]
        tab.set_components(components)

    def remove_current_channel_tab(self):
        current_idx = self.tabs_channels.currentIndex()
        if self.tabs_channels.count() > 1:
            self.tabs_channels.removeTab(current_idx)
            self.sig_parameters_changed.emit()

    # ---- reading back ----------------------------------------------

    def get_active_channel_components(self) -> list:
        tab = self.tabs_channels.currentWidget()
        return tab.components() if tab is not None else []

    def _tacho_noise_params(self) -> dict:
        """The tacho_noise block for the pipeline, or {} when disabled."""
        if not self.chk_tacho_noise.isChecked():
            return {}
        cfg = {
            "std_rpm": float(self.spin_tn_std.value()),
            "region": str(self.combo_tn_region.currentText()),
            "region_frac": float(self.spin_tn_region_frac.value()),
        }
        if self.spin_tn_dropout_rate.value() > 0:
            cfg["dropout_rate"] = float(self.spin_tn_dropout_rate.value())
            cfg["dropout_gain"] = float(self.spin_tn_dropout_gain.value())
        return cfg

    def get_generation_parameters(self) -> dict:
        channels_data = []
        for i in range(self.tabs_channels.count()):
            tab = self.tabs_channels.widget(i)
            channels_data.append({
                "name": tab.edit_name.text(),
                "unit": tab.combo_unit.currentText(),
                "components": tab.components(),
            })

        params = {
            "fs": float(self.spin_fs.value()),
            "duration": float(self.spin_duration.value()),
            "rpm_start": float(self.spin_rpm_start.value()),
            "rpm_stop": float(self.spin_rpm_stop.value()),
            "direction": str(self.combo_direction.currentText()),
            "plateaus_on": self.chk_plateaus.isChecked(),
            "plateaus": int(self.spin_plateaus.value()),
            "plateau_ratio": float(self.spin_plateau_ratio.value()),
            "format": self.combo_format.currentText(),
            "x_axis_mode": self.combo_x_axis.currentText(),
            "prev_start": float(self.spin_prev_start.value()),
            "prev_end": float(self.spin_prev_end.value()),
            "channels": channels_data,
        }

        seed_txt = self.edit_seed.text().strip()
        if seed_txt:
            try:
                seed = int(seed_txt)
            except ValueError:
                # QIntValidator accepts a bare '+' as an intermediate edit
                # state. Live preview can run before the user finishes typing.
                seed = None
            if seed is not None:
                params["seed"] = seed

        tacho_noise = self._tacho_noise_params()
        if tacho_noise:
            params["tacho_noise"] = tacho_noise

        return params

    # ---- loading a preset -----------------------------------------

    def _open_preset_picker(self):
        picker = LibraryPresetDialog(self)
        if picker.exec() and picker.selected_params() is not None:
            self.load_parameters(picker.selected_params())

    def load_parameters(self, params: dict):
        """
        Replaces every field with `params` (signal_library / pipeline shape).
        Muted while it runs so the live preview redraws once at the end, not on
        every widget it touches.
        """
        self._is_updating = True
        try:
            self.spin_fs.setValue(int(round(params.get("fs", self.spin_fs.value()))))
            duration = float(params.get("duration", self.spin_duration.value()))
            self.spin_duration.setValue(duration)
            # Snap the preview window to the whole new record -- a leftover 30 s
            # end on a 60 s preset would show half the sweep.
            self.spin_prev_start.setValue(0.0)
            self.spin_prev_end.setValue(duration)
            self.spin_rpm_start.setValue(int(round(params.get("rpm_start", 0))))
            self.spin_rpm_stop.setValue(int(round(params.get("rpm_stop", 0))))

            direction = params.get("direction", "Ramp Up")
            if self.combo_direction.findText(direction) >= 0:
                self.combo_direction.setCurrentText(direction)

            self.chk_plateaus.setChecked(bool(params.get("plateaus_on", False)))
            self.spin_plateaus.setValue(max(1, int(params.get("plateaus", 3) or 3)))
            self.spin_plateau_ratio.setValue(min(0.99, max(0.01, float(params.get("plateau_ratio", 0.5) or 0.5))))

            seed = params.get("seed")
            self.edit_seed.setText("" if seed is None else str(int(seed)))

            tacho = params.get("tacho_noise") or {}
            self.chk_tacho_noise.setChecked(bool(tacho))
            self.spin_tn_std.setValue(float(tacho.get("std_rpm", 0.0)))
            region = tacho.get("region", "all")
            if self.combo_tn_region.findText(region) >= 0:
                self.combo_tn_region.setCurrentText(region)
            self.spin_tn_region_frac.setValue(min(1.0, max(0.01, float(tacho.get("region_frac", 1.0)))))
            self.spin_tn_dropout_rate.setValue(float(tacho.get("dropout_rate", 0.0)))
            self.spin_tn_dropout_gain.setValue(float(tacho.get("dropout_gain", 0.5)))

            while self.tabs_channels.count():
                self.tabs_channels.removeTab(0)
            for channel in params.get("channels", []):
                self.add_channel_tab(
                    channel.get("name", f"Channel_{self.tabs_channels.count() + 1}"),
                    channel.get("unit", "g"),
                    list(channel.get("components", [])),
                )
            if self.tabs_channels.count() == 0:
                self.add_channel_tab("Channel_1")
        finally:
            self._is_updating = False

        self.sig_parameters_changed.emit()
