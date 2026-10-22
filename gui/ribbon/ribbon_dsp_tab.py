# =====================================================================
# FILE: gui/ribbon/ribbon_dsp_tab.py
# =====================================================================
"""
Shared QSettings<->AppContext plumbing for the ACC DSP ribbon tabs
(Spectrum, Spectrogram, Order Tracking).

The three tabs differ only in which widgets they lay out and which DTO they
build; the plumbing around it -- read a value from QSettings, write it back on
every change, and refresh the DSP config held on AppContext -- was three
byte-identical copies. It lives here so that plumbing cannot drift per tab
(audit 02 / refactor_candidates_3.md, S10).

A subclass sets `_settings_attr` (the AppContext attribute readers consult --
Workspace and the drop router read that, never the widget) and
`_ready_widget_name` (the widget built last that `get_dsp_config()` needs, used
to tell whether `init_ui()` has progressed far enough to call it), implements
`get_dsp_config()`, defines `init_ui()`, and may override `_after_push()` to
publish more than the config.

A subclass also sets `_analysis_kind`; its closed-list controls are built by
`_build_choice_combo()` from that kind's DSP choice register entry
(ADR §1.186), so no tab carries its own item list, default or label -> value
map. QSettings keeps storing the label.

A tracked tab builds its Tacho Tracking group with `_build_tracking_sweep()`
(#830): the group keeps its own settings per tracking mode and every accepted
change refreshes the DSP config like any other control.
"""
from PySide6.QtWidgets import QComboBox, QWidget

from gui.ribbon.tracking_sweep_fields import TrackingSweepFields
from view_models.analysis_kinds import DspChoices, ParameterChoices, resolve_dsp_choices


class RibbonDspTab(QWidget):
    _settings_attr = ""
    _ready_widget_name = ""
    _analysis_kind = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_context = parent.app_context if hasattr(parent, "app_context") else None
        self.settings = self.app_context.settings if self.app_context else None
        self.dsp_choices: DspChoices = resolve_dsp_choices(self._analysis_kind)
        self.init_ui()

    def _build_choice_combo(self, name: str, key: str) -> QComboBox:
        """A combo offering DSP parameter `name`'s register list, set to the label saved under `key`."""
        parameter = self.dsp_choices.parameter(name)
        combo = QComboBox()
        combo.addItems(list(parameter.labels))
        combo.setCurrentText(self._resolve_saved_label(parameter, key))
        return combo

    def _resolve_saved_label(self, parameter: ParameterChoices, key: str) -> str:
        """
        The label saved under `key`, or the default when none is saved. The one
        ribbon rule for a stale saved label (one the list no longer offers): it
        falls back to the default, the setting is rewritten, and a WARNING is logged.
        """
        default = parameter.default_label
        saved = self._get_val(key, default)
        if saved in parameter.labels:
            return saved
        self._set_val(key, default)
        if self.app_context is not None and hasattr(self.app_context, "log"):
            self.app_context.log(
                f"WARNING: saved ribbon setting {key} '{saved}' is no longer offered; "
                f"using '{default}'.")
        return default

    def _build_tracking_sweep(self, prefix: str) -> TrackingSweepFields:
        """The Tacho Tracking group, its settings saved under `<prefix>_...`."""
        self.tracking_sweep = TrackingSweepFields(
            prefix, self.dsp_choices, self.settings, self._build_choice_combo, self)
        self.tracking_sweep.sig_changed.connect(self._push_dsp_config)
        return self.tracking_sweep

    def _resolve_choice_value(self, name: str, combo: QComboBox):
        """The DSP value behind `combo`'s current label for DSP parameter `name`."""
        return self.dsp_choices.parameter(name).resolve_value(combo.currentText())

    def _get_val(self, key: str, default, type_cast=str):
        if self.settings:
            return type_cast(self.settings.value(key, default))
        return default

    def _set_val(self, key: str, val):
        if self.settings:
            self.settings.setValue(key, val)
        # Every control funnels through here, so this is the one place that keeps
        # AppContext current for the readers that never look at this widget.
        self._push_dsp_config()

    def _push_dsp_config(self):
        if not self.app_context or not hasattr(self, self._ready_widget_name):
            return
        setattr(self.app_context, self._settings_attr, self.get_dsp_config())
        self._after_push()

    def _after_push(self):
        """Hook for a tab that publishes more than its DSP config."""
