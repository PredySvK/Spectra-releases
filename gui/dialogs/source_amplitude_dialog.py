# =====================================================================
# FILE: gui/dialogs/source_amplitude_dialog.py
# =====================================================================
"""
Asking what the amplitude in imported result files means.

A MASTA workbook, a processed measurement or an ANSYS response arrives as a
ready-made amplitude, and nothing in the file says whether it is RMS or Peak.
Guessing wrong puts every curve of the file off by a factor of sqrt(2) with
nothing on screen to say so, so adding such files asks once per reader. The
question list and the defaults are decided by orchestration; this only shows
them and hands the choice back.

All internal documentation strings and variable labels are standardly written
in English.
"""

from typing import Dict, Optional, Sequence

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)

from core.source_amplitude import SOURCE_AMPLITUDE_PEAK, SOURCE_AMPLITUDE_RMS


def ask_source_amplitudes(parent, questions: Sequence) -> Optional[Dict[str, str]]:
    """Shows the question; returns reader -> "rms" | "peak", or None on Cancel."""
    dialog = SourceAmplitudeDialog(questions, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.answers()


class SourceAmplitudeDialog(QDialog):
    """One radio pair per reader; each starts on the reader's default."""

    def __init__(self, questions: Sequence, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Source amplitude")
        self.setMinimumWidth(420)
        self._choices: Dict[str, Dict[str, QRadioButton]] = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "<b>Is the amplitude in these files RMS or Peak?</b><br>"
            "The program converts it to RMS when reading:  RMS = Peak / √2."
        ))

        for question in questions:
            files = "file" if question.file_count == 1 else "files"
            group = QGroupBox(f"{question.label} — {question.file_count} {files}")
            group_layout = QVBoxLayout(group)
            buttons = {
                SOURCE_AMPLITUDE_RMS: QRadioButton("RMS"),
                SOURCE_AMPLITUDE_PEAK: QRadioButton("Peak"),
            }
            for button in buttons.values():
                group_layout.addWidget(button)
            buttons[question.default].setChecked(True)
            self._choices[question.reader] = buttons
            layout.addWidget(group)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout.addWidget(box)

    def answers(self) -> Dict[str, str]:
        return {
            reader: next(value for value, button in buttons.items() if button.isChecked())
            for reader, buttons in self._choices.items()
        }
