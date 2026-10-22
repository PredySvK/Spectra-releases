# =====================================================================
# FILE: gui/ribbon/ribbon_bar.py
# =====================================================================
from PySide6.QtWidgets import QTabWidget
from gui.ribbon.ribbon_widgets import RIBBON_TOOLTIP_QSS
from gui.ribbon.tab_project import TabProject
from gui.ribbon.tab_acc_spectrum import TabAccSpectrum
from view_models.analysis_kinds import (
    ANALYSIS_MODES, ANALYSIS_MODE_ACC_ORDER_TRACKING, ANALYSIS_MODE_ACC_OVERALL_LEVEL, ANALYSIS_MODE_ACC_SPECTROGRAM,
    ANALYSIS_MODE_ACC_SPECTRUM, ANALYSIS_MODE_PROJECT, ANALYSIS_MODE_TOOLS, ANALYSIS_MODE_WORKFLOW,
)
from gui.ribbon.tab_acc_spectrogram import TabAccSpectrogram
from gui.ribbon.tab_acc_order_tracking import TabAccOrderTracking
from gui.ribbon.tab_acc_overall_level import TabAccOverallLevel
from gui.ribbon.tab_workflow import TabWorkflow
from gui.ribbon.tab_tools import TabTools


class RibbonBar(QTabWidget):
    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.init_ui()

    def init_ui(self):
        # Room for one row of RibbonGroups: a big 84px button, its caption, and
        # the tab bar above. The old 115 predates icon-over-label buttons and
        # group captions and clipped both.
        # The tab row lives in the window's title strip (MainWindowFrame hides
        # this widget's own tab bar), so the height is the page alone.
        self.setFixedHeight(126)
        self.setTabPosition(QTabWidget.North)
        self.setStyleSheet(RIBBON_TOOLTIP_QSS)

        self.tab_project = TabProject(self)
        self.tab_acc_spectrum = TabAccSpectrum(self)
        self.tab_acc_spectrogram = TabAccSpectrogram(self)
        self.tab_acc_order_tracking = TabAccOrderTracking(self)
        self.tab_acc_overall_level = TabAccOverallLevel(self)
        self.tab_workflow = TabWorkflow(self)
        self.tab_tools = TabTools(self)

        tabs = {
            ANALYSIS_MODE_PROJECT: (self.tab_project, "📁 Project"),
            ANALYSIS_MODE_ACC_OVERALL_LEVEL: (self.tab_acc_overall_level, "📶 Overall Level"),
            ANALYSIS_MODE_ACC_ORDER_TRACKING: (self.tab_acc_order_tracking, "⚡ Order Tracking"),
            ANALYSIS_MODE_ACC_SPECTROGRAM: (self.tab_acc_spectrogram, "🎛️ Spectrogram 2D"),
            ANALYSIS_MODE_ACC_SPECTRUM: (self.tab_acc_spectrum, "📈 Spectrum 1D"),
            ANALYSIS_MODE_WORKFLOW: (self.tab_workflow, "🧩 Workflow"),
            ANALYSIS_MODE_TOOLS: (self.tab_tools, "🔧 Tools"),
        }
        # Tab order is the register's order, then the two non-analysis tabs;
        # the tab index -> mode lookup below reads this same list.
        self._tab_modes = [mode.name for mode in ANALYSIS_MODES] + [ANALYSIS_MODE_WORKFLOW, ANALYSIS_MODE_TOOLS]
        for mode in self._tab_modes:
            self.addTab(*tabs[mode])

        self.app_context.current_analysis_mode = ANALYSIS_MODE_PROJECT
        self.currentChanged.connect(self.handle_ribbon_tab_changed_routing)

    def handle_ribbon_tab_changed_routing(self, active_tab_index: int):
        tab_label = self.tabText(active_tab_index)
        in_range = 0 <= active_tab_index < len(self._tab_modes)
        self.app_context.current_analysis_mode = (
            self._tab_modes[active_tab_index] if in_range else ANALYSIS_MODE_PROJECT)
        self.app_context.log(f"WORKSPACE: Mode shifted to [{self.app_context.current_analysis_mode.upper()}] via '{tab_label}'.")

        # The Workflow tab swaps sub_area's centre from the analysis docks to the
        # WorkflowView; every other tab swaps it back.
        show_workflow = getattr(self.parent(), "show_workflow_view", None)
        if callable(show_workflow):
            show_workflow(self.app_context.current_analysis_mode == ANALYSIS_MODE_WORKFLOW)




