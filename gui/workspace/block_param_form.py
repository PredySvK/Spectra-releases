# =====================================================================
# FILE: gui/workspace/block_param_form.py
# =====================================================================
"""
A form that renders one block's parameters straight from its
`core/dsp_configs.py` dataclass (ARCHITECTURE_DECISIONS §1.6, Epic P phase 7C).

Lives in gui/ because it is a Qt widget. It is deliberately generic -- it walks
`dataclasses.fields(config_cls)` and picks a widget per field type -- rather than
a hand-tuned form per config class: there are three config classes today and
phase 7D adds five more blocks, so one generator that scales beats three copies
that drift from the ribbon.

Read-only mode is what phase 7C's viewer uses (a saved node's params are frozen,
§1.6 decision 1). The same widget, editable, is what the later "+ Add step" /
per-node settings step and the phase-8 canvas gear dialog will reuse -- hence
`values()` exists now even though nothing calls it yet.

All internal documentation strings and variable labels are standardly written
in English.
"""
import dataclasses
import typing
from typing import Any, Dict, Tuple

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLineEdit, QSpinBox, QWidget,
)

# Wide enough for any FFT size / step / hysteresis the DSP configs carry, without
# pretending to know a real range -- that belongs to the ribbon widgets, which
# stay the authoritative editor. This form is a mirror, not a validator.
_INT_LIMIT = 10_000_000
_FLOAT_LIMIT = 1.0e9


def _pretty(name: str) -> str:
    return name.replace("_", " ").title()


def _field_default(f: dataclasses.Field) -> Any:
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
        return f.default_factory()  # type: ignore[misc]
    return None


def _field_type(f: dataclasses.Field) -> Any:
    """The field's declared type. `core/dsp_configs.py` has no
    `from __future__ import annotations`, so this is a real type object, not a
    string -- but guard anyway so a future switch does not crash the form."""
    t = f.type
    if isinstance(t, str):
        return {"int": int, "float": float, "bool": bool, "str": str, "list": list}.get(t, str)
    return t


def _optional_inner(ftype: Any) -> Any:
    """`X` for an `Optional[X]` field, otherwise None."""
    if typing.get_origin(ftype) is typing.Union:
        args = typing.get_args(ftype)
        inner = [arg for arg in args if arg is not type(None)]
        if len(args) == 2 and len(inner) == 1:
            return inner[0]
    return None


# Fields with a closed set of values get the same dropdown the analysis tab's
# ribbon shows: (label, stored value) pairs. Same labels/order as the ribbons.
_FFT_SIZES = [(str(n), n) for n in (256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)]
_CHOICES: Dict[str, list] = {
    "fft_size": _FFT_SIZES,
    "window_type": [("Hanning", "hann"), ("Hamming", "hamming"), ("Blackman", "blackman"),
                    ("Flat-top", "flattop"), ("Rectangular", "boxcar")],
    "amplitude_mode": [("RMS", "rms"), ("Peak", "peak")],
    "spectrum_format": [("Linear", "linear"), ("Power", "power"), ("PSD", "psd")],
    "tracking_mode": [("RPM Tracked", "rpm"), ("Free Run (Time)", "time")],
    "direction": [("Up (Run-Up)", "up"), ("Down (Run-Down)", "down"), ("Any (Both)", "any")],
    "averaging_type": [("Linear", "linear"), ("Peak hold", "peak_hold"),
                       ("Exponential", "exponential")],
    "color_scale": [("Linear", "Linear"), ("dB (Log)", "dB (Log)")],
}


def _choices_for(config_cls: Any, name: str) -> list:
    choices = _CHOICES.get(name, [])
    # The spectrogram refuses "any" for RPM tracking (ADR §1.58 point 8); its ribbon omits it.
    if name == "direction" and config_cls.__name__ == "SpectrogramConfig":
        return [c for c in choices if c[1] != "any"]
    return choices


def _make_combo(choices: list, value: Any) -> QComboBox:
    w = QComboBox()
    for label, data in choices:
        w.addItem(label, data)
    idx = w.findData(value)
    if idx < 0:  # a value saved outside the list stays visible instead of being replaced
        w.addItem(str(value), value)
        idx = w.count() - 1
    w.setCurrentIndex(idx)
    return w


def _make_widget(f: dataclasses.Field, value: Any, choices: list = ()) -> QWidget:
    ftype = _field_type(f)

    if choices:
        return _make_combo(choices, value)
    if ftype is bool:
        w = QCheckBox()
        w.setChecked(bool(value))
        return w
    if ftype is int:
        w = QSpinBox()
        w.setRange(-_INT_LIMIT, _INT_LIMIT)
        try:
            w.setValue(int(value))
        except (TypeError, ValueError):
            pass
        return w
    if ftype is float:
        w = QDoubleSpinBox()
        w.setDecimals(4)
        w.setRange(-_FLOAT_LIMIT, _FLOAT_LIMIT)
        try:
            w.setValue(float(value))
        except (TypeError, ValueError):
            pass
        return w
    if ftype is list:
        w = QLineEdit(", ".join(str(item) for item in (value or [])))
        return w
    return QLineEdit("" if value is None else str(value))


def _read_widget(f: dataclasses.Field, widget: QWidget) -> Any:
    ftype = _field_type(f)
    if isinstance(widget, QComboBox):
        return widget.currentData()
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QSpinBox):
        return widget.value()
    if isinstance(widget, QDoubleSpinBox):
        return widget.value()
    text = widget.text().strip() if isinstance(widget, QLineEdit) else ""
    if ftype is list:
        items = [part.strip() for part in text.split(",") if part.strip()]
        out = []
        for item in items:
            try:
                out.append(float(item))
            except ValueError:
                out.append(item)
        return out
    inner = _optional_inner(ftype)
    if inner is not None:
        # Empty means None, not "": Overall Level's f_stop=None is Full
        # Bandwidth, and "" would reach the DSP as a band edge.
        if not text:
            return None
        try:
            return inner(text)
        except (TypeError, ValueError):
            return text
    return text


class BlockParamForm(QWidget):
    """
    `set_config(config_cls, params, read_only=...)` builds one row per dataclass
    field; `values()` reads them back into a params dict. Missing keys in
    `params` fall back to the dataclass default -- the same value the ribbon
    would show.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._form = QFormLayout(self)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._widgets: Dict[str, Tuple[dataclasses.Field, QWidget]] = {}
        self._config_cls: Any = None

    def clear(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._widgets = {}
        self._config_cls = None

    def set_config(self, config_cls: Any, params: Any, *, read_only: bool = False) -> None:
        self.clear()
        self._config_cls = config_cls
        params = dict(params or {})
        for f in dataclasses.fields(config_cls):
            value = params.get(f.name, _field_default(f))
            widget = _make_widget(f, value, _choices_for(config_cls, f.name))
            widget.setEnabled(not read_only)
            self._form.addRow(_pretty(f.name), widget)
            self._widgets[f.name] = (f, widget)

    def values(self) -> Dict[str, Any]:
        return {name: _read_widget(f, widget) for name, (f, widget) in self._widgets.items()}

    @property
    def config_cls(self) -> Any:
        return self._config_cls
