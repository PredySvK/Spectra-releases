# =====================================================================
# FILE: gui/dialogs/library_preset_dialog.py
# =====================================================================
"""
Standalone picker that loads one measurement's parameter dict out of a
predefined dataset (io_modules.signal_generation.signal_library, ADR section
1.20). Split out of signal_generator_dialog.py: it is its own topic -- browsing
the library -- and shares no state with the generator's channel editor beyond
the params dict it hands back.
"""

import copy

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QListWidget,
    QDialogButtonBox,
)


class LibraryPresetDialog(QDialog):
    """
    Picks one measurement out of a predefined dataset (signal_library, ADR
    section 1.20). It only returns that measurement's parameter dict -- the
    caller loads it into the generator dialog, where the user is free to edit
    it further. Whole-dataset realisation stays in tools/make_test_dataset.py.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Load Predefined Signal")
        self.setMinimumWidth(520)
        self._selected_params = None

        from io_modules.signal_generation import signal_library
        self._library = signal_library

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Dataset:"))
        self.combo_dataset = QComboBox()
        self.combo_dataset.addItems(signal_library.list_datasets())
        self.combo_dataset.currentTextChanged.connect(self._reload_measurements)
        row.addWidget(self.combo_dataset, stretch=1)
        layout.addLayout(row)

        self.lbl_description = QLabel()
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setStyleSheet("color: #666;")
        layout.addWidget(self.lbl_description)

        self.list_measurements = QListWidget()
        self.list_measurements.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.list_measurements, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._measurements = []
        if self.combo_dataset.count():
            self._reload_measurements(self.combo_dataset.currentText())

    def _reload_measurements(self, key: str):
        self.list_measurements.clear()
        if not key:
            return
        spec = self._library.build_dataset(key)
        self.lbl_description.setText(spec.description)
        self._measurements = list(spec.measurements)
        for m in self._measurements:
            self.list_measurements.addItem(
                f"R{m.run_idx}  ·  {m.setup.key} {m.setup.label}  ·  {m.cycles} cycles"
            )
        if self._measurements:
            self.list_measurements.setCurrentRow(0)

    def accept(self):
        idx = self.list_measurements.currentRow()
        if 0 <= idx < len(self._measurements):
            # Deep copy: the library dataclasses are frozen but their nested
            # params dict is not, and the generator dialog mutates what it loads.
            self._selected_params = copy.deepcopy(self._measurements[idx].params)
        super().accept()

    def selected_params(self):
        return self._selected_params
