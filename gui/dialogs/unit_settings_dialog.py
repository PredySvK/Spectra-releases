# gui/dialogs/unit_settings_dialog.py
"""
Global Engineering Units Optimization Dashboard.
Persists configuration changes safely through AppContext encapsulation rules.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QLabel
from PySide6.QtCore import Qt
from core.units import _SW_CANONICAL_GROUPS

from gui.dialogs.dialog_state import remember_dialog_geometry


class UnitSettingsDialog(QDialog):
    """Modal interface window managing centralized engineering unit conversion preferences."""

    def __init__(self, app_context, parent=None, workspace=None, explorer_panel=None):
        super().__init__(parent)
        self.setWindowTitle("Global Engineering Units Configuration")
        self.setMinimumSize(450, 260)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.context = app_context
        self.workspace = workspace
        self.explorer_panel = explorer_panel
        self.init_ui()

        # Remembered across restarts; cleared by Settings > Reset Layout / Reset All.
        remember_dialog_geometry(
            self, getattr(self.context, "settings", None), "unit_settings", default_size=(480, 300)
        )

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Select target physical display units for the active workspace session graphs:"))

        self.combos = {}
        domain_labels = [
            ("Linear Acceleration Domain:", "global_unit_acceleration", 0),
            ("Acoustic / Fluid Pressure Domain:", "global_unit_pressure", 1),
            ("Electrical Voltage Domain:", "global_unit_voltage", 2),
            ("Rotational Speed / Frequency Domain:", "global_unit_speed", 3)
        ]

        for label_text, attr_name, matrix_idx in domain_labels:
            row_layout = QHBoxLayout()
            row_layout.addWidget(QLabel(label_text), stretch=1)

            combo = QComboBox()
            allowed_units = _SW_CANONICAL_GROUPS[matrix_idx]
            combo.addItems(allowed_units)

            current_active_val = getattr(self.context, attr_name, allowed_units)
            if current_active_val in allowed_units:
                combo.setCurrentText(current_active_val)

            row_layout.addWidget(combo, stretch=1)
            layout.addLayout(row_layout)
            self.combos[attr_name] = combo

        layout.addStretch()

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Apply & Save Units")
        self.btn_cancel = QPushButton("Cancel")

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.btn_save.clicked.connect(self.handle_save_action)
        self.btn_cancel.clicked.connect(self.reject)

    def handle_save_action(self):
        for attr_name, combo in self.combos.items():
            selected_unit = combo.currentText().strip()
            # Utilize AppContext public persistence method
            self.context.update_unit_setting(attr_name, selected_unit)

        self.context.log("SYSTEM: Centralized global engineering units preferred markers updated.")

        if self.workspace is not None:
            self.workspace.replot_time_docks_for_unit_change()

        if self.explorer_panel is not None and hasattr(self.explorer_panel, "rebuild_tree_view"):
            self.explorer_panel.rebuild_tree_view()

        self.accept()





