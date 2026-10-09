# =====================================================================
# FILE: gui/bottom_panels/bottom_panel.py
# =====================================================================
"""
The bottom dock: the System Log, the Job Manager and Evaluation as
side-by-side tabs, one panel.

These were three separate docks stacked and tabified in an arrangement the
user could not reliably get back to -- the Job Manager in particular kept
hiding behind the log. They are the same kind of thing (a running account of
what the application is doing) so they now share one panel, the same way the
Explorer dock carries File Browser / Data Pool / Block Pool.

Each tab is shown or hidden on its own from the Settings ribbon's Panels
group (the same add/remove-a-tab trick the Explorer's Block Pool uses -- the
widget stays alive, re-adding it is free). The window hides the whole dock
once the last tab is gone. Canonical left-to-right order is fixed here so a
tab that was toggled off and back on lands where it was.

Deliberately thin: it owns the QTabWidget and nothing else. The inner widgets
are built by the window (which wires the log callback and the job manager)
and handed in here.

All internal documentation strings and variable labels are standardly written
in English.
"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

LOG_TAB_LABEL = "System Log"
JOBS_TAB_LABEL = "Jobs"
EVALUATION_TAB_LABEL = "Evaluation"


class BottomPanel(QWidget):
    def __init__(self, log_widget, jobs_widget, evaluation_widget, parent=None):
        super().__init__(parent)
        self.log_widget = log_widget
        self.jobs_widget = jobs_widget
        self.evaluation_widget = evaluation_widget

        # (widget, label) in the order tabs must appear, whichever subset is on.
        self._catalog = (
            (log_widget, LOG_TAB_LABEL),
            (jobs_widget, JOBS_TAB_LABEL),
            (evaluation_widget, EVALUATION_TAB_LABEL),
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget(self)
        for widget, label in self._catalog:
            self.tabs.addTab(widget, label)
        self.tabs.setCurrentWidget(log_widget)

        layout.addWidget(self.tabs)

    # ---- per-tab visibility ------------------------------------------------

    def is_tab_visible(self, widget) -> bool:
        return self.tabs.indexOf(widget) != -1

    def set_tab_visible(self, widget, on: bool) -> None:
        idx = self.tabs.indexOf(widget)
        if on and idx == -1:
            self.tabs.insertTab(self._insertion_index(widget), widget,
                                self._label_for(widget))
            self.tabs.setCurrentWidget(widget)
        elif not on and idx != -1:
            self.tabs.removeTab(idx)

    def visible_tab_count(self) -> int:
        return self.tabs.count()

    def show_tab(self, widget) -> None:
        """Bring a tab on (if off) and make it current."""
        self.set_tab_visible(widget, True)
        self.tabs.setCurrentWidget(widget)

    # ---- helpers ---------------------------------------------------------

    def _label_for(self, widget) -> str:
        return next(label for w, label in self._catalog if w is widget)

    def _insertion_index(self, widget) -> int:
        """Where `widget` goes so the visible tabs keep catalog order."""
        order = [w for w, _ in self._catalog]
        target = order.index(widget)
        ahead = {w for w in order[:target]}
        return sum(1 for i in range(self.tabs.count())
                   if self.tabs.widget(i) in ahead)
