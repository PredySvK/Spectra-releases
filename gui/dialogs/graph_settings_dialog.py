# gui/dialogs/graph_settings_dialog.py
"""
Industrial Performance Configuration Dialog for PyQtGraph viewports.
Controls decimation factor indices and view boundaries eviction algorithms.
All internal documentation strings and variable labels are written in English.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox,
    QRadioButton, QSpinBox, QPushButton, QGroupBox
)
from PySide6.QtCore import Qt

from gui.dialogs.dialog_state import remember_dialog_geometry


class GraphSettingsDialog(QDialog):
    """
    Modality dialog box configuring hardware acceleration downsampling indices.
    """

    def __init__(self, current_config: dict, parent=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Default Graph Throughput Settings")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.config = current_config
        self.init_ui()

        # Remembered across restarts; cleared by Settings > Reset Layout / Reset All.
        remember_dialog_geometry(self, settings, "graph_settings", default_size=(440, 360))

    def init_ui(self):
        master_layout = QVBoxLayout(self)
        master_layout.setContentsMargins(12, 12, 12, 12)
        master_layout.setSpacing(12)

        # --- 1. DOWN-SAMPLING CONFIGURATIONS GROUP ---
        self.group_downsample = QGroupBox("Data Downsampling (Points Reduction)")
        group_layout = QVBoxLayout(self.group_downsample)
        group_layout.setSpacing(8)

        self.cb_enable_downsample = QCheckBox("Enable Downsampling")
        self.cb_enable_downsample.setChecked(self.config["downsample_enabled"])
        self.cb_enable_downsample.toggled.connect(self._slot_toggle_downsample_dependencies)
        group_layout.addWidget(self.cb_enable_downsample)

        self.rb_auto = QRadioButton("Automatic Optimization (Matches Monitor Width)")
        self.rb_auto.setChecked(self.config["auto_mode_active"])
        group_layout.addWidget(self.rb_auto)

        row_manual = QHBoxLayout()
        self.rb_manual = QRadioButton("Manual Decimation Factor:")
        self.rb_manual.setChecked(not self.config["auto_mode_active"])
        self.rb_manual.toggled.connect(self._slot_toggle_spinbox_state)
        row_manual.addWidget(self.rb_manual)

        self.sb_factor = QSpinBox()
        self.sb_factor.setRange(2, 10000)
        self.sb_factor.setValue(self.config["manual_factor"])
        row_manual.addWidget(self.sb_factor)
        row_manual.addStretch()
        group_layout.addLayout(row_manual)

        master_layout.addWidget(self.group_downsample)

        # --- 2. SCREEN VIEW BOUNDARY GROUP ---
        self.group_clipping = QGroupBox("Viewport Optimization")
        clipping_layout = QVBoxLayout(self.group_clipping)

        self.cb_render_screen_only = QCheckBox("Render Screen Only Data (Evict Hidden Points)")
        self.cb_render_screen_only.setChecked(self.config["render_screen_only"])
        clipping_layout.addWidget(self.cb_render_screen_only)

        master_layout.addWidget(self.group_clipping)

        # --- 3. BOTTOM INTERACTION CONTROL LAYOUT ROW ---
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save & Apply")
        self.btn_cancel = QPushButton("Cancel")
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        master_layout.addLayout(btn_layout)

        self.btn_save.clicked.connect(self.handle_save_action)
        self.btn_cancel.clicked.connect(self.reject)

        self._slot_toggle_downsample_dependencies(self.cb_enable_downsample.isChecked())

    def _slot_toggle_downsample_dependencies(self, checked: bool):
        self.rb_auto.setEnabled(checked)
        self.rb_manual.setEnabled(checked)
        self._slot_toggle_spinbox_state()

    def _slot_toggle_spinbox_state(self):
        is_manual_active = self.rb_manual.isChecked() and self.rb_manual.isEnabled()
        self.sb_factor.setEnabled(is_manual_active)

    def handle_save_action(self):
        self.config["downsample_enabled"] = self.cb_enable_downsample.isChecked()
        self.config["auto_mode_active"] = self.rb_auto.isChecked()
        self.config["manual_factor"] = self.sb_factor.value()
        self.config["render_screen_only"] = self.cb_render_screen_only.isChecked()
        self.accept()

    def get_finalized_configurations(self) -> dict:
        return self.config












