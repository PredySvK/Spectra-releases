# =====================================================================
# FILE: gui/ribbon/ribbon_dsp_tab.py
# =====================================================================
"""
Shared QSettings<->AppContext plumbing for the ACC DSP ribbon tabs
(Spectrum, Spectrogram, Order Tracking, Overall Level).

The tabs differ only in which widgets they lay out and which DTO they build;
the plumbing around it -- read a value from QSettings, write it back on every
change, and refresh the DSP config held on AppContext -- lives here so that it
cannot drift per tab (audit 02 / refactor_candidates_3.md, S10).

A subclass sets `_settings_attr` (the AppContext attribute readers consult --
Workspace and the drop router read that, never the widget) and
`_ready_widget_name` (the widget built last that `get_dsp_config()` needs, used
to tell whether `init_ui()` has progressed far enough to call it), implements
`get_dsp_config()`, defines `init_ui()`, and may override `_after_push()` to
publish more than the config and `_sync_dependent_widgets()` to re-derive
widget state that follows other widgets (greyed items, minimums).

Every saved control is bound to its entry of the tab's ribbon DSP fields
(`resolve_ribbon_dsp_fields`, ADR §1.286) with `_bind_field()`: the field gives
its QSettings key and default, a closed-list control its register list
(ADR §1.186, QSettings keeps the label), and load, save and
`reset_to_defaults()` all come from that one list. A saved value the control
cannot show falls back to the default, is rewritten and logged.

A tracked tab builds its Tacho Tracking group with `_build_tracking_sweep()`
(#830): the group keeps its own settings per tracking mode, every accepted
change refreshes the DSP config like any other control, and reset returns it
too.
"""
from typing import Any, Dict

from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QWidget

from gui.ribbon.tracking_sweep_fields import TrackingSweepFields
from view_models.analysis_kinds import (
    FIELD_CHOICE, DspChoices, RibbonDspField, resolve_dsp_choices, resolve_ribbon_dsp_fields,
)


def _show(widget: QWidget, value: Any) -> None:
    """Put a field value (label, bool, float or str) into its control."""
    if isinstance(widget, QComboBox):
        widget.setCurrentText(value)
    elif isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QDoubleSpinBox):
        widget.setValue(float(value))
    elif isinstance(widget, QLineEdit):
        widget.setText(str(value))
    else:
        raise TypeError(f"no ribbon field binding for {type(widget).__name__}")


def _change_signal(widget: QWidget):
    """The signal carrying a control's new value in the form QSettings keeps."""
    if isinstance(widget, QComboBox):
        return widget.currentTextChanged
    if isinstance(widget, QCheckBox):
        return widget.toggled
    if isinstance(widget, QDoubleSpinBox):
        return widget.valueChanged
    return widget.textChanged


class RibbonDspTab(QWidget):
    _settings_attr = ""
    _ready_widget_name = ""
    _analysis_kind = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_context = parent.app_context if hasattr(parent, "app_context") else None
        self.settings = self.app_context.settings if self.app_context else None
        self.dsp_choices: DspChoices = resolve_dsp_choices(self._analysis_kind)
        self.ribbon_fields: Dict[str, RibbonDspField] = {
            field.name: field for field in resolve_ribbon_dsp_fields(self._analysis_kind)}
        self._bound: Dict[str, QWidget] = {}
        self._resetting = False
        self.init_ui()

    # ---- binding ------------------------------------------------------------

    def _bind_field(self, name: str, widget: QWidget, *, save_on_change: bool = True) -> QWidget:
        """
        Show ribbon field `name`'s saved value in `widget` and, unless the tab saves
        it itself (a value it validates first), save every change under its key.
        A combo with no items gets the field's register list.
        """
        field = self.ribbon_fields[name]
        if isinstance(widget, QComboBox) and widget.count() == 0:
            widget.addItems(list(field.choices.labels))
        _show(widget, self._resolve_saved_field(field))
        self._bound[name] = widget
        if save_on_change:
            _change_signal(widget).connect(lambda value, key=field.key: self._set_val(key, value))
        return widget

    def _build_field_combo(self, name: str) -> QComboBox:
        """A combo for closed-list ribbon field `name`, saved under its key."""
        return self._bind_field(name, QComboBox())

    def _build_choice_combo(self, name: str, key: str) -> QComboBox:
        """A combo offering DSP parameter `name`'s register list, set to the label saved under `key`
        -- for a control whose key is not a ribbon field of its own (Tacho Tracking)."""
        parameter = self.dsp_choices.parameter(name)
        field = RibbonDspField(name=name, key=key, kind=FIELD_CHOICE,
                               default=parameter.default_label, choices=parameter)
        combo = QComboBox()
        combo.addItems(list(parameter.labels))
        combo.setCurrentText(self._resolve_saved_field(field))
        return combo

    def _save_field(self, name: str, value) -> None:
        """Save `value` under ribbon field `name`'s key (a control bound without saving)."""
        self._set_val(self.ribbon_fields[name].key, value)

    def _resolve_saved_field(self, field: RibbonDspField):
        """
        What `field`'s control shows: the saved value, or the default when none is
        saved. The one ribbon rule for a saved value the control cannot show (a
        label the list no longer offers, an unreadable flag or number): it falls
        back to the default, the setting is rewritten, and a WARNING is logged.
        """
        if not self.settings:
            return field.default
        saved = self.settings.value(field.key, field.default)
        value = field.resolve_saved(saved)
        if value is not None:
            return value
        self.settings.setValue(field.key, field.default)
        reason = "is no longer offered" if field.kind == FIELD_CHOICE else "is not a valid value"
        if self.app_context is not None and hasattr(self.app_context, "log"):
            self.app_context.log(
                f"WARNING: saved ribbon setting {field.key} '{saved}' {reason}; "
                f"using '{field.default}'.")
        return field.default

    # ---- reset --------------------------------------------------------------

    def reset_to_defaults(self) -> None:
        """
        Every saved control of the tab, the Tacho Tracking group in every tracking
        mode included, back to its default. The controls change as if clicked (so
        whatever listens to them follows), but the DSP config and the display
        settings are published once, after the last one -- never a half-reset tab.
        """
        self._resetting = True
        try:
            for name, widget in self._bound.items():
                field = self.ribbon_fields[name]
                if self.settings:
                    self.settings.setValue(field.key, field.default)
                _show(widget, field.default)
            if hasattr(self, "tracking_sweep"):
                self.tracking_sweep.reset_to_defaults()
            self._sync_dependent_widgets()
        finally:
            self._resetting = False
        self._push_dsp_config()
        self._emit_display_settings_changed()

    def _sync_dependent_widgets(self) -> None:
        """Hook: re-derive widget state that follows other widgets (after init and reset)."""

    def _emit_display_settings_changed(self) -> None:
        if not self._resetting and hasattr(self, "sig_display_settings_changed"):
            self.sig_display_settings_changed.emit()

    # ---- plumbing -----------------------------------------------------------

    def _build_tracking_sweep(self, prefix: str) -> TrackingSweepFields:
        """The Tacho Tracking group, its settings saved under `<prefix>_...`."""
        self.tracking_sweep = TrackingSweepFields(
            prefix, self.dsp_choices, self.settings, self._build_choice_combo, self)
        self.tracking_sweep.sig_changed.connect(self._push_dsp_config)
        return self.tracking_sweep

    def _resolve_choice_value(self, name: str, combo: QComboBox):
        """The DSP value behind `combo`'s current label for DSP parameter `name`."""
        return self.dsp_choices.parameter(name).resolve_value(combo.currentText())

    def _set_val(self, key: str, val):
        if self.settings:
            self.settings.setValue(key, val)
        # Every control funnels through here, so this is the one place that keeps
        # AppContext current for the readers that never look at this widget.
        self._push_dsp_config()

    def _push_dsp_config(self):
        if self._resetting or not self.app_context or not hasattr(self, self._ready_widget_name):
            return
        setattr(self.app_context, self._settings_attr, self.get_dsp_config())
        self._after_push()

    def _after_push(self):
        """Hook for a tab that publishes more than its DSP config."""
