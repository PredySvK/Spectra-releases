# =====================================================================
# FILE: gui/dialogs/channel_selection_dialog.py
# =====================================================================
"""
Checkbox picker for "Calculate & Save Data": which physical channels (by
base name and direction) to include, built from what is actually present in
the currently loaded folder.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Dict, List, Optional, Set

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.models import ChannelIdentity
from gui.dialogs.dialog_state import remember_dialog_geometry


class ChannelSelectionDialog(QDialog):
    def __init__(self, identities: Dict[str, List[Optional[str]]],
                previously_selected: Set[ChannelIdentity], parent=None, settings=None):
        super().__init__(parent)
        self.setWindowTitle("Select Channels")
        self.setMinimumWidth(320)
        self._checkboxes: Dict[ChannelIdentity, QCheckBox] = {}
        self._build_ui(identities, previously_selected)
        remember_dialog_geometry(self, settings, "channel_selection", default_size=(360, 480))

    def _build_ui(self, identities: Dict[str, List[Optional[str]]],
                  previously_selected: Set[ChannelIdentity]) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        btn_all = QPushButton("Select All")
        btn_none = QPushButton("Select None")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        toolbar.addWidget(btn_all)
        toolbar.addWidget(btn_none)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)

        if not identities:
            container_layout.addWidget(QLabel("No matching channels found in the loaded folder."))

        for base in sorted(identities.keys()):
            for direction in identities[base]:
                identity = (base, direction)
                label = f"{base}  {direction}" if direction else base
                checkbox = QCheckBox(label)
                checkbox.setChecked(identity in previously_selected)
                self._checkboxes[identity] = checkbox
                container_layout.addWidget(checkbox)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, checked: bool) -> None:
        for checkbox in self._checkboxes.values():
            checkbox.setChecked(checked)

    def selected_identities(self) -> Set[ChannelIdentity]:
        return {identity for identity, checkbox in self._checkboxes.items() if checkbox.isChecked()}


