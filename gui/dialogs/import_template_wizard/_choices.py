"""
The choices the wizard's steps share: combo helpers and the labels more than one step shows.
"""

from PySide6.QtWidgets import QComboBox

from core.import_template import PICK_FILE_NAME, PICK_FOLDER, PICK_HEADER, PICK_SHEET
from core.source_amplitude import (
    SOURCE_AMPLITUDE_PEAK, SOURCE_AMPLITUDE_PEAK_TO_PEAK, SOURCE_AMPLITUDE_RMS,
)

PICK_SOURCE_LABELS = (
    (PICK_HEADER, "Column header"),
    (PICK_SHEET, "Sheet name"),
    (PICK_FILE_NAME, "File name"),
    (PICK_FOLDER, "Folder"),
)
AMPLITUDE_LABELS = (
    (SOURCE_AMPLITUDE_PEAK, "Peak"),
    (SOURCE_AMPLITUDE_RMS, "RMS"),
    (SOURCE_AMPLITUDE_PEAK_TO_PEAK, "Peak-to-Peak"),
)


def fill_combo(combo: QComboBox, choices) -> None:
    for value, label in choices:
        combo.addItem(label, value)


def select_data(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)
