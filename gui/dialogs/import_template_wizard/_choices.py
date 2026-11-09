"""
The choices the wizard's steps share: combo helpers, the filling of a result
table, and the labels more than one step shows.
"""

from typing import Sequence, Tuple

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QComboBox, QHeaderView, QTableWidget, QTableWidgetItem

from core.channel_types import (
    CHANNEL_TYPE_ACCELEROMETER, CHANNEL_TYPE_GENERAL_DYNAMIC, CHANNEL_TYPE_MICROPHONE, CHANNEL_TYPE_VOLTAGE,
)
from core.source_amplitude import (
    SOURCE_AMPLITUDE_PEAK, SOURCE_AMPLITUDE_PEAK_TO_PEAK, SOURCE_AMPLITUDE_RMS,
)

CHANNEL_TYPE_LABELS = (
    (CHANNEL_TYPE_ACCELEROMETER, "Accelerometer"),
    (CHANNEL_TYPE_MICROPHONE, "Microphone"),
    (CHANNEL_TYPE_VOLTAGE, "Voltage"),
    (CHANNEL_TYPE_GENERAL_DYNAMIC, "General dynamic"),
)
AMPLITUDE_LABELS = (
    (SOURCE_AMPLITUDE_PEAK, "Peak"),
    (SOURCE_AMPLITUDE_RMS, "RMS"),
    (SOURCE_AMPLITUDE_PEAK_TO_PEAK, "Peak-to-Peak"),
)

# How a text file is parsed; blank is detected from the file.
_DETECTED = "Detected"
ENCODING_LABELS = (
    ("", _DETECTED), ("utf-8", "UTF-8"), ("cp1252", "Windows-1252"), ("cp1250", "Windows-1250"),
    ("latin-1", "Latin-1"), ("utf-16", "UTF-16"),
)
DELIMITER_LABELS = (
    ("", _DETECTED), ("	", "Tab"), (";", "Semicolon"), (",", "Comma"), ("|", "Pipe"), (" ", "Space"),
)
DECIMAL_LABELS = (("", _DETECTED), (".", "Point"), (",", "Comma"))


def fill_combo(combo: QComboBox, choices) -> None:
    for value, label in choices:
        combo.addItem(label, value)


def select_data(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def fill_result_table(table: QTableWidget, labels: Sequence[str],
                      rows: Sequence[Tuple[Sequence[str], bool]], red: str) -> None:
    """
    Fills a table whose columns fit their contents with `rows` of (texts,
    shown red). The columns fit once at the end: refitting them after every
    replaced cell of a shown table took ~13 s for a few hundred channels.
    """
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.setUpdatesEnabled(False)
    try:
        table.setColumnCount(len(labels))
        table.setHorizontalHeaderLabels(list(labels))
        table.setRowCount(len(rows))
        brush = QBrush(QColor(red))
        for number, (values, is_red) in enumerate(rows):
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if is_red:
                    item.setForeground(brush)
                table.setItem(number, column, item)
    finally:
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setUpdatesEnabled(True)
