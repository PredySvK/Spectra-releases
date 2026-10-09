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
"""
from PySide6.QtWidgets import QWidget


class RibbonDspTab(QWidget):
    _settings_attr = ""
    _ready_widget_name = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.app_context = parent.app_context if hasattr(parent, "app_context") else None
        self.settings = self.app_context.settings if self.app_context else None
        self.init_ui()

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
