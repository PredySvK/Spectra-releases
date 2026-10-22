# =====================================================================
# FILE: gui/ribbon/tracking_sweep_fields.py
# =====================================================================
"""
The ribbon's Tacho Tracking group: the Tracking sweep of a tracked analysis
(tracking mode, step, direction and Tracking range), for the Spectrogram,
Order Tracking and Overall Level tabs (#830).

A tab hands over its QSettings prefix and its DSP choices and gets back the
group to lay out and the values its DSP config needs. Everything between is
kept here once: the step and the Tracking range are remembered per tracking
mode (`<prefix>_step_rpm` / `_step_time`, `<prefix>_rpm_min` / `_rpm_max`,
`<prefix>_time_start` / `_time_end`), the labels follow the mode, and the
direction greys out in Free Run, which has none. An analysis whose DSP choices
offer no time step (Order Tracking) gets the group without the mode choice.

The Tracking range is one pair of fields showing the range of the shown mode.
Empty means auto (None). A pair whose minimum is at or above its maximum is
refused as it is entered: the field just edited goes back to its last accepted
value and a tooltip says why, so a computation that cannot succeed is never
started. Only the shown mode's range reaches the config; the inactive one is
core's to set to auto (`resolve_tracking_sweep`).
"""
from typing import Any, Callable, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QLabel, QLineEdit,
                               QToolTip, QVBoxLayout)

from gui.ribbon.ribbon_widgets import RibbonGroup, labeled_column

# Digits with an optional decimal part, or nothing at all (auto). A
# QDoubleValidator treats an empty field as unfinished and never reports it as
# entered, so clearing a field back to auto would not take.
_NUMBER_OR_EMPTY = QRegularExpression(r"^(\d{1,7}(\.\d{0,3})?)?$")

# tracking mode -> its wording and the config fields / QSettings suffixes of its range
_MODES = {
    "rpm": {
        "step_label": "Step [RPM]",
        "range_fields": ("rpm_min", "rpm_max"),
        "range_labels": ("Min [RPM]", "Max [RPM]"),
        "range_tooltips": ("Lowest rpm that counts; empty = auto",
                           "Highest rpm that counts; empty = auto"),
        "refusal": "Min must be below Max. Leave a field empty for auto.",
    },
    "time": {
        "step_label": "Step [s]",
        "range_fields": ("time_start", "time_end"),
        "range_labels": ("Start [s]", "End [s]"),
        "range_tooltips": ("Time on the time axis the analysis starts at; empty = start of the record",
                           "Time on the time axis the analysis ends at; empty = end of the record"),
        "refusal": "Start must be before End. Leave a field empty for auto.",
    },
}

_TOOLTIP_WITH_FREE_RUN = (
    "RPM Tracked resamples onto engine speed; Free Run keeps the time axis. "
    "Step, ramp and range are remembered per mode.")
_TOOLTIP_RPM_ONLY = "RPM step, ramp and rpm range the tacho is followed over"


def _format(value: Optional[float]) -> str:
    return "" if value is None else f"{float(value):g}"


def _parse(text: str) -> Optional[float]:
    text = text.strip()
    return float(text) if text else None


def _resolve_saved_bound(text) -> Optional[float]:
    """A bound as QSettings kept it: empty (auto) or unreadable is None."""
    try:
        return float(text) if str(text).strip() else None
    except ValueError:
        return None


class TrackingSweepFields(QObject):
    """The Tacho Tracking group of one tab; `sig_changed` fires after any accepted change is saved."""

    sig_changed = Signal()

    def __init__(self, prefix: str, dsp_choices, settings,
                 build_choice_combo: Callable[[str, str], QComboBox], parent=None):
        super().__init__(parent)
        self._prefix = prefix
        self._dsp_choices = dsp_choices
        self._settings = settings
        self._modes = tuple(mode for mode, _ in dsp_choices.step_rules)
        self._accepted = ("", "")

        self.combo_tracking_mode: Optional[QComboBox] = None
        if len(self._modes) > 1:
            self.combo_tracking_mode = build_choice_combo("tracking_mode", self._key("tracking_mode"))

        self.lbl_step = QLabel()
        self.spin_step = QDoubleSpinBox()
        self.lbl_direction = QLabel("Ramp")
        self.combo_direction = build_choice_combo("direction", self._key("direction"))
        self.lbl_min = QLabel()
        self.lbl_max = QLabel()
        self.edit_min = self._build_edit()
        self.edit_max = self._build_edit()

        self.group = self._build_group()
        self._show_mode()

        if self.combo_tracking_mode is not None:
            self.combo_tracking_mode.currentTextChanged.connect(self._on_mode_changed)
        self.spin_step.valueChanged.connect(self._on_step_changed)
        self.combo_direction.currentTextChanged.connect(self._on_direction_changed)

    def resolve_config_fields(self) -> Dict[str, Any]:
        """The DSP config fields this group sets: step, direction and the shown mode's
        Tracking range, plus the tracking mode where the analysis has Free Run."""
        mode = self.resolve_tracking_mode()
        fields: Dict[str, Any] = {
            "step": float(self.spin_step.value()),
            "direction": self._dsp_choices.parameter("direction").resolve_value(
                self.combo_direction.currentText()),
        }
        if self.combo_tracking_mode is not None:
            fields["tracking_mode"] = mode
        fields.update(zip(_MODES[mode]["range_fields"], self.resolve_range()))
        return fields

    def resolve_tracking_mode(self) -> str:
        if self.combo_tracking_mode is None:
            return self._modes[0]
        return self._dsp_choices.parameter("tracking_mode").resolve_value(
            self.combo_tracking_mode.currentText())

    def resolve_range(self) -> Tuple[Optional[float], Optional[float]]:
        """The accepted (min, max) of the shown mode; None is auto."""
        return _parse(self._accepted[0]), _parse(self._accepted[1])

    def _key(self, suffix: str) -> str:
        return f"{self._prefix}_{suffix}"

    def _get(self, key: str, default):
        return self._settings.value(key, default) if self._settings else default

    def _set(self, key: str, value) -> None:
        if self._settings:
            self._settings.setValue(key, value)

    def _build_edit(self) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText("auto")
        edit.setValidator(QRegularExpressionValidator(_NUMBER_OR_EMPTY, edit))
        edit.setMaximumWidth(80)
        edit.editingFinished.connect(lambda: self._on_range_edited(edit))
        return edit

    def _build_group(self) -> RibbonGroup:
        # One grid in every tab:  Tracking Mode | Step (over Min + Max)
        #                          Ramp          | Min  | Max
        # An analysis without Free Run shows the Tracking Mode greyed out on
        # RPM Tracked, so the group looks the same in every tab.
        top = Qt.AlignmentFlag.AlignTop
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(0)

        def cell(label, widget) -> QVBoxLayout:
            return labeled_column([(label, widget)])

        if self.combo_tracking_mode is None:
            group = RibbonGroup("Tacho Tracking", tooltip=_TOOLTIP_RPM_ONLY)
            mode_widget = QComboBox()
            mode_widget.addItems(["RPM Tracked", "Free Run (Time)"])  # same width as the live combo
            mode_widget.setEnabled(False)
        else:
            group = RibbonGroup("Tacho Tracking", tooltip=_TOOLTIP_WITH_FREE_RUN)
            mode_widget = self.combo_tracking_mode
        grid.addLayout(cell("Tracking Mode", mode_widget), 0, 0, top)
        grid.addLayout(cell(self.lbl_step, self.spin_step), 0, 1, 1, 2, top)
        grid.addLayout(cell(self.lbl_direction, self.combo_direction), 1, 0, top)
        grid.addLayout(cell(self.lbl_min, self.edit_min), 1, 1, top)
        grid.addLayout(cell(self.lbl_max, self.edit_max), 1, 2, top)
        group.body.addLayout(grid)
        return group

    def _show_mode(self) -> None:
        """Word the group for the current mode and show the step and range saved for it."""
        mode = self.resolve_tracking_mode()
        wording = _MODES[mode]
        rule = self._dsp_choices.step_rule(mode)
        step_key = self._key(f"step_{mode}")

        self.spin_step.blockSignals(True)
        self.lbl_step.setText(wording["step_label"])
        self.spin_step.setDecimals(rule.decimals)
        self.spin_step.setRange(rule.minimum, rule.maximum)
        try:
            saved = float(self._get(step_key, rule.default))
        except (TypeError, ValueError):
            saved = rule.default
        step = rule.clamp(saved)
        self.spin_step.setValue(step)
        if step != saved:
            self._set(step_key, step)
        self.spin_step.blockSignals(False)

        self.lbl_direction.setEnabled(mode == "rpm")
        self.combo_direction.setEnabled(mode == "rpm")

        self._range_keys = tuple(self._key(field) for field in wording["range_fields"])
        self._refusal = wording["refusal"]
        self.lbl_min.setText(wording["range_labels"][0])
        self.lbl_max.setText(wording["range_labels"][1])
        self.edit_min.setToolTip(wording["range_tooltips"][0])
        self.edit_max.setToolTip(wording["range_tooltips"][1])
        low, high = (_resolve_saved_bound(self._get(key, "")) for key in self._range_keys)
        if low is not None and high is not None and low >= high:
            low = high = None
        self._show_range(_format(low), _format(high))

    def _show_range(self, low: str, high: str) -> None:
        self._accepted = (low, high)
        self.edit_min.setText(low)
        self.edit_max.setText(high)

    def _on_mode_changed(self, label: str) -> None:
        self._set(self._key("tracking_mode"), label)
        self._show_mode()
        self.sig_changed.emit()

    def _on_step_changed(self, value: float) -> None:
        self._set(self._key(f"step_{self.resolve_tracking_mode()}"), value)
        self.sig_changed.emit()

    def _on_direction_changed(self, label: str) -> None:
        self._set(self._key("direction"), label)
        self.sig_changed.emit()

    def _on_range_edited(self, edit: QLineEdit) -> None:
        typed = (self.edit_min.text().strip(), self.edit_max.text().strip())
        if typed == self._accepted:
            return
        low, high = _parse(typed[0]), _parse(typed[1])
        if low is not None and high is not None and low >= high:
            self._show_range(*self._accepted)
            QToolTip.showText(edit.mapToGlobal(edit.rect().bottomLeft()), self._refusal, edit)
            return
        self._show_range(_format(low), _format(high))
        # Both bounds are saved before one emit: a config holding the new
        # minimum with the old maximum is never published in between.
        for key, value in zip(self._range_keys, (low, high)):
            self._set(key, "" if value is None else value)
        self.sig_changed.emit()
