# =====================================================================
# FILE: gui/main_window.py
# =====================================================================
"""
Master visual orchestration frame shell configuring core dock layouts.
Directly integrates the automated central command discovery registry subsystem.
Implements Dependency Injection (DI) to pass AppContext to decoupled components.
"""

import functools

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QMainWindow, QTabWidget, QDockWidget, QStackedWidget,
)

from gui.handlers.data_pool import DataPoolHandler
from gui.handlers.filter_routing import FilterRoutingHandler
from gui.handlers.project_document import ProjectDocumentHandler
from gui.handlers.result_content import ResultContentHandler
from gui.ribbon.ribbon_bar import RibbonBar
from gui.ribbon.ribbon_widgets import RibbonGroup
from gui.welcome.welcome_page import WelcomePage
from gui.workspace.workspace import Workspace, find_dock_by_id
from gui.workspace.workspace_layout import (
    WorkspaceLayout, DEFAULT_BOTTOM_HEIGHT, DEFAULT_EXPLORER_WIDTH,
)
from gui.file_explorer.file_explorer import UnvChannelExplorer
from io_modules.changelog import read_changelog
from gui.filter_panel.filter_panel import FilterPanel
from gui.bottom_panels.log_widget import LogWidget
from gui.bottom_panels.bottom_panel import BottomPanel
from gui.bottom_panels.evaluation_panel import EvaluationPanel
from app_context import AppContext
from view_models.analysis_kinds import (
    ANALYSIS_MODE_ACC_ORDER_TRACKING,
    ANALYSIS_MODE_ACC_OVERALL_LEVEL,
    ANALYSIS_MODE_ACC_SPECTROGRAM,
    ANALYSIS_MODE_ACC_SPECTRUM,
    resolve_analysis_mode,
)


_TITLEBAR_HEIGHT = 28


class MainWindowFrame(QWidget):
    def __init__(self, parent=None, startup_project_path: str | None = None,
                 install_update=None):
        super().__init__(parent)

        self.app_context = AppContext()
        self.app_context.initialize_session_directory()

        # Created before init_ui and before any controller: the status strip and
        # the Jobs dock render from it, and every controller that runs work in
        # the background receives it by constructor (ADR 1.13).
        from gui.jobs.qt_job_runner import QtJobRunner
        self.job_manager = QtJobRunner(self.app_context, parent=self)

        # Wire scan-cache adoption to QtJobRunner so the GUI thread does not copy
        # files synchronously during save_as (audit 02 finding 6.3 / #82).
        from io_modules.project_store import adopt_untitled_scan_caches
        self.app_context.project_session.set_cache_adopter(
            lambda path, roots: self.job_manager.submit(
                "Adopt scan caches",
                fn=adopt_untitled_scan_caches,
                args=(path, roots),
                lane="interactive",
                quiet=True,
            )
        )


        # Created before init_ui for the same reason: BatchRunHandler is wired
        # up inside init_ui() and takes this controller by constructor (#235,
        # #239).
        from gui.workspace.workflow_run_bridge import WorkflowRunBridge
        self.workflow_run_bridge = WorkflowRunBridge(self.app_context, self.job_manager)

        # Same reason again: ProjectDocumentHandler resets the live-compute
        # queue on every project swap and is built inside init_ui() (#236).
        from gui.workspace.live_order_results import LiveOrderResults
        self.live_order_results = LiveOrderResults(
            self.app_context, self.job_manager,
        )

        # Before init_ui, which wires the Settings tab button to it; the shell
        # hands in how to install a downloaded Update (None outside the shell).
        from gui.update import UpdateHandler
        self.update_handler = UpdateHandler(self.job_manager, self, install_update)

        self.init_ui()
        # The layout is restored later, the first time the workspace becomes
        # visible (see _set_project_ui_enabled). restoreState() only gets dock
        # *sizes* right against a laid-out, visible window; sub_area is hidden
        # behind the Welcome page here and has no real size yet, so restoring
        # now snaps every manually resized dock back to its size hint.
        self._layout_restored = False

        # Built inside init_ui (ahead of workspace, which takes it by
        # constructor); only the result signals are wired here, once both ends
        # exist.
        self.spectral_requests.spectrum_ready.connect(self.workspace.plot_frequency_block)
        self.spectral_requests.waterfall_ready.connect(self.workspace.plot_spectrogram_block)

        # --- NEW: Connect Order Tracking signal ---
        self.spectral_requests.order_cuts_ready.connect(self.workspace.plot_order_cuts)
        self.spectral_requests.overall_level_ready.connect(self.workspace.plot_overall_level_block)

        self.spectral_requests.computation_failed.connect(
            self.workspace.report_computation_failure
        )

        # The Project ribbon tab's own refresh tail, wired to the runner: a
        # finished batch run can have changed the project's result-set list.
        self.project_document.bind_run_finished(self.workflow_run_bridge)

        # Coalesced rather than applied per finished channel: every re-apply
        # re-reads every checked result set off disk, so dropping N channels at
        # once used to cost N full reads (and N redraws) to arrive at the one
        # that counts. Same settle-timer shape PoolWatcher uses for file bursts.
        self._live_channel_settle = QTimer(self)
        self._live_channel_settle.setSingleShot(True)
        self._live_channel_settle.setInterval(150)
        self._live_channel_settle.timeout.connect(self.live_drop_handler.refresh_pending)
        self.live_order_results.channel_ready.connect(self._live_channel_settle.start)

        if startup_project_path is not None:
            # The shell shows the window before the event loop opens the project,
            # so an open error has a visible parent and never interrupts construction.
            QTimer.singleShot(0, self, lambda: self.project_document.run_startup(startup_project_path))
        else:
            self.project_document.run_startup()

    def init_ui(self):
        master_layout = QVBoxLayout(self)
        master_layout.setContentsMargins(0, 0, 0, 0)
        master_layout.setSpacing(0)

        self.ribbon = RibbonBar(app_context=self.app_context, parent=self)
        self.ribbon.setObjectName("RibbonBar")
        self._build_window_chrome(master_layout)
        master_layout.addWidget(self.ribbon)

        sub_area = QMainWindow()
        sub_area.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        sub_area.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        # The dock separators are the resize handles between the plot tabs and
        # the docks around them; unstyled they are invisible. The hover colour
        # waits for the mouse to rest, so crossing a separator does not flash it.
        from gui.shell import DockSeparatorHighlight
        self.dock_separator_highlight = DockSeparatorHighlight(sub_area)

        # The one owner of what the Data Pool holds (#240). Built before
        # explorer_panel below, which hands it down to the three tabs that call
        # it; it gets that same panel back by setter once it exists.
        self.data_pool = DataPoolHandler(self.app_context, self.job_manager, self)

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setObjectName("WorkspaceTabs")
        self.workspace_tabs.setTabPosition(QTabWidget.South)
        self.workspace_tabs.setMovable(True)
        self.workspace_tabs.setTabsClosable(True)

        # Both are built here rather than after init_ui, so workspace below
        # can take them by constructor instead of reaching back into the window
        # for them (#242). Neither needs the manager to be built -- the
        # controller's result signals are connected to it afterwards, in
        # __init__, and the drop handler only needs the tab widget above.
        from gui.workspace.spectral_requests import SpectralRequests
        self.spectral_requests = SpectralRequests(self.app_context, self.job_manager)

        from gui.handlers.live_channel_drop import LiveChannelDropHandler
        self.live_drop_handler = LiveChannelDropHandler(
            self.app_context, self.live_order_results, self.workspace_tabs,
        )

        # Built here, ahead of explorer_panel/workspace, so ResultPoolPanel
        # (nested in explorer_panel) and Workspace can both receive it
        # by constructor instead of reaching into main_window later
        # (ARCHITECTURE_DECISIONS §1.75, #233). find_dock_by_id is bound to
        # workspace_tabs directly -- the tab widget already exists and is
        # never replaced, unlike Workspace, which is built after this.
        self.result_content_handler = ResultContentHandler(
            self.app_context, functools.partial(find_dock_by_id, self.workspace_tabs),
            self.job_manager, self,
        )

        from gui.workspace.graph_dock import GraphDock
        self.placeholder_graph = GraphDock(app_context=self.app_context)

        plot_item = self.placeholder_graph.plot_widget.plotItem
        from core.app_metadata import APP_NAME
        plot_item.setTitle(f"{APP_NAME} - Engineering Canvas")
        plot_item.hideAxis('left')
        plot_item.hideAxis('bottom')
        self.placeholder_graph.plot_widget.showGrid(x=False, y=False)

        # Built ahead of its own dock (below) so DataPoolPanel can take it by
        # constructor: the pool tree reads the panel's state on every rebuild
        # to narrow itself (#241).
        self.filter_panel = FilterPanel()
        self.filter_panel.setObjectName("FilterPanel")

        self.explorer_panel = UnvChannelExplorer(
            app_context=self.app_context,
            data_pool=self.data_pool,
            filter_panel=self.filter_panel,
            focused_dock=self.workspace_tabs.currentWidget,
            result_content_handler=self.result_content_handler,
            # Late-bound on purpose: FilterRoutingHandler needs this very
            # panel, so it cannot exist yet -- the lambda reads it off the
            # window at call time, once both are up (#234).
            refresh_and_apply_for_focused_dock=(
                lambda: self.filter_routing.refresh_and_apply_for_focused_dock()),
            job_runner=self.job_manager,
        )
        self.data_pool.set_explorer_panel(self.explorer_panel)
        explorer_dock = QDockWidget("Explorer", sub_area)
        explorer_dock.setWidget(self.explorer_panel)
        explorer_dock.setObjectName("ExplorerDock")
        explorer_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        sub_area.addDockWidget(Qt.LeftDockWidgetArea, explorer_dock)

        filter_dock = QDockWidget("Filters", sub_area)
        filter_dock.setWidget(self.filter_panel)
        filter_dock.setObjectName("FilterDock")
        filter_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        sub_area.addDockWidget(Qt.LeftDockWidgetArea, filter_dock)
        # File Explorer on top, Filters below it: the explorer is the primary
        # navigation surface and the filters act on what it shows. A saved
        # layout overrides this in WorkspaceLayout.restore_state.
        sub_area.splitDockWidget(explorer_dock, filter_dock, Qt.Vertical)
        sub_area.resizeDocks([explorer_dock, filter_dock], [65, 35], Qt.Vertical)

        # The job status strip is its own dock at the foot of the left column,
        # not part of Filters: closing Filters must not take it along. No title
        # bar and no features -- it cannot be closed, moved or floated, so it is
        # always there. WorkspaceLayout pins its height.
        from gui.jobs.job_status_bar import JobStatusBar
        self.job_status_bar = JobStatusBar(self.job_manager)
        job_status_dock = QDockWidget("Job Status", sub_area)
        job_status_dock.setWidget(self.job_status_bar)
        job_status_dock.setObjectName("JobStatusDock")
        job_status_dock.setTitleBarWidget(QWidget(job_status_dock))
        job_status_dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
        sub_area.addDockWidget(Qt.LeftDockWidgetArea, job_status_dock)
        sub_area.splitDockWidget(filter_dock, job_status_dock, Qt.Vertical)
        # First approximation only; WorkspaceLayout.apply_saved_explorer_width
        # sets the real width (saved or default) once sub_area is visible and
        # laid out.
        sub_area.resizeDocks([explorer_dock], [DEFAULT_EXPLORER_WIDTH], Qt.Horizontal)

        # The one owner of the Filter panel's facets and of the mask they put on
        # every open dock (ARCHITECTURE_DECISIONS §1.76, #234). Built here, after
        # the panel it drives and the two widgets it reads, and before
        # Workspace below, which takes it by constructor.
        self.filter_routing = FilterRoutingHandler(
            self.app_context, self.filter_panel, self.workspace_tabs,
            self.explorer_panel, self,
        )

        self.log_panel = LogWidget()
        # Wire AppContext's central logging hook safely
        self.app_context.logger_callback = self.log_panel.log_message

        from gui.jobs.jobs_dock import JobsDockWidget
        self.jobs_panel = JobsDockWidget(self.job_manager)

        # Built before BottomPanel (below) since the Evaluation card needs it
        # for its dock tasks -- the same live-dock pattern (DockTasks, ADR
        # §1.84) every other analysis-tab read goes through (ADR §1.64
        # point 5, patterns.md).
        self.workspace = Workspace(
            app_context=self.app_context, tab_widget=self.workspace_tabs,
            placeholder_graph=self.placeholder_graph,
            filter_panel=self.filter_panel,
            job_manager=self.job_manager,
            spectral_requests=self.spectral_requests,
            live_drop_handler=self.live_drop_handler,
            result_content_handler=self.result_content_handler,
            filter_routing=self.filter_routing,
        )
        self.explorer_panel.bind_workspace(self.workspace)
        from gui.handlers.selection_drop import SelectionDropHandler
        self.workspace.bind_selection_drops(
            SelectionDropHandler(self.app_context, self.job_manager, self.workspace))
        self.explorer_panel.selections_panel.selection_activated.connect(self.workspace.draw_selection)
        self.evaluation_panel = EvaluationPanel(self.app_context, self.workspace)
        # The one dependency that cannot go the other way round: the card is
        # made from the manager, so the manager gets it back by setter.
        self.workspace.bind_evaluation_panel(self.evaluation_panel)

        # System Log, Job Manager and Evaluation as one panel of tabs -- the
        # same shape as the Explorer dock. The job status strip in the left column still carries
        # the one job the user is waiting on. Each tab toggles on its own from
        # the Settings ribbon; the dock's own title strip is dropped (it only
        # repeated "Output" and cost a row) so the tab bar is the whole chrome.
        bottom_panel = BottomPanel(self.log_panel, self.jobs_panel, self.evaluation_panel)
        bottom_dock = QDockWidget("Output", sub_area)
        bottom_dock.setWidget(bottom_panel)
        bottom_dock.setObjectName("BottomDock")
        bottom_dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        bottom_dock.setTitleBarWidget(QWidget(bottom_dock))
        sub_area.addDockWidget(Qt.BottomDockWidgetArea, bottom_dock)
        sub_area.resizeDocks([bottom_dock], [DEFAULT_BOTTOM_HEIGHT], Qt.Vertical)

        self.workspace_layout = WorkspaceLayout(
            self.app_context, sub_area, explorer_dock, filter_dock, job_status_dock,
            bottom_dock, bottom_panel, self.log_panel, self.jobs_panel, self.evaluation_panel,
        )
        # Late for the same reason evaluation_panel is: the layout is assembled
        # from panels that are themselves made from the manager.
        self.workspace.bind_workspace_layout(self.workspace_layout)
        self.workspace.bind_cursor_switch(self.ribbon.tab_tools.btn_cursor)
        self.workspace.bind_pin_switch(self.ribbon.tab_tools.btn_cursor_pin)
        self.workspace.bind_highlight_switch(self.ribbon.tab_tools.btn_highlight)
        self.ribbon.tab_tools.btn_cursor_settings.clicked.connect(self.workspace.open_cursor_settings)

        self.workspace_tabs.tabCloseRequested.connect(lambda idx: self.workspace.close_specific_tab(idx))
        self.workspace.show_home_tab()

        # sub_area's centre swaps between the analysis docks and the block-diagram
        # workflow panel; the ribbon's Workflow tab drives the swap (ADR §1.6
        # phase 7C). The surrounding docks (File Explorer, Jobs, Log) stay put.
        from gui.workspace.workflow_view import WorkflowView
        self.workflow_view = WorkflowView(self.app_context)
        self.explorer_panel.selections_panel.selections_changed.connect(
            self.workflow_view.refresh_input_selections)
        self.workflow_view.create_selection_requested.connect(self._create_selection_for_workflow)
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.workspace_tabs)   # index 0: analysis
        self.center_stack.addWidget(self.workflow_view)    # index 1: workflows
        sub_area.setCentralWidget(self.center_stack)

        # The Block Pool: a palette of processing blocks, a sub-tab of the
        # Explorer dock and only shown while the ribbon's Workflow tab is active
        # (ADR §1.6 phase 7C). Double-click or drag adds a block to the open
        # workflow. The panel is built by UnvChannelExplorer; the window only
        # wires its activation signal and toggles the tab.
        self.block_pool_panel = self.explorer_panel.block_pool_panel
        self.block_pool_panel.block_activated.connect(self.workflow_view.add_block)

        from gui.handlers.window_settings import WindowSettingsHandler
        from gui.handlers.dataset_authoring import DatasetAuthoringHandler

        self.window_settings = WindowSettingsHandler(
            self.app_context,
            self.workspace_layout,
            self.workspace,
            self.log_panel,
            self,
            explorer_panel=self.explorer_panel,
        )

        self.dataset_authoring = DatasetAuthoringHandler(
            self.app_context,
            self.job_manager,
            self,
            log_panel=self.log_panel,
            data_pool=self.data_pool,
        )

        self.ribbon.tab_settings.btn_graph_settings.clicked.connect(self.window_settings.open_graph_settings)
        self.ribbon.tab_project.btn_generate_signal.clicked.connect(self.dataset_authoring.generate_signal)
        self.ribbon.tab_project.btn_realize_dataset.clicked.connect(self.dataset_authoring.realize_dataset)

        # --- PROJECT DOCUMENT COMMANDS ---
        # The one owner of "which project is open" (ADR §1.78, #236). Built
        # here, after every panel it refreshes; the four things whose owners are
        # only built at the end of init_ui() go in as callables (see the module
        # docstring).
        project_tab = self.ribbon.tab_project
        self.project_document = ProjectDocumentHandler(
            self.app_context, project_tab, self.workspace, self.explorer_panel,
            self.filter_panel, self.filter_routing, self.live_order_results,
            self.workflow_view, self.log_panel, self.data_pool, self,
            show_welcome=self.show_welcome,
            show_workspace=self.show_workspace,
            set_titlebar_text=self.set_titlebar_text,
            show_x_axis_unit=self.ribbon.tab_settings.set_x_axis_unit,
            job_runner=self.job_manager,
        )

        project_tab.btn_select_dir.clicked.connect(self.project_document.select_data_directory)
        project_tab.btn_edit_meta.clicked.connect(self.project_document.open_metadata_editor)
        project_tab.btn_new_project.clicked.connect(self.project_document.new_project)
        project_tab.btn_open_project.clicked.connect(
            lambda: self.project_document.open_project())
        project_tab.btn_save_project.clicked.connect(self.project_document.save_project)
        project_tab.btn_save_project_as.clicked.connect(self.project_document.save_project_as)
        project_tab.combo_recent.activated.connect(
            lambda _: self.project_document.open_recent_project())

        # --- WORKFLOW TAB (ADR §1.6 phase 7C) ---
        from gui.handlers.workflow_authoring import WorkflowAuthoringHandler
        from gui.handlers.batch_run import BatchRunHandler

        self.workflow_authoring = WorkflowAuthoringHandler(
            self.app_context, self.workflow_view, self
        )
        # The one owner of "start a batch run", whether it came from the
        # Workflow tab's Run button or from one of the four ribbon fast paths
        # below (ARCHITECTURE_DECISIONS §1.77, #235). Built here, after the
        # ribbon and the workflow view it reads; the runner it hands work to is
        # built before init_ui() for exactly this.
        self.batch_run = BatchRunHandler(
            self.app_context, self.ribbon, self.workflow_run_bridge,
            self.workflow_view, self, job_runner=self.job_manager,
        )
        workflow_tab = self.ribbon.tab_workflow
        workflow_tab.btn_new.clicked.connect(self.workflow_authoring.new_workflow)
        workflow_tab.btn_run.clicked.connect(self.batch_run.run_selected_workflow)
        workflow_tab.btn_import.clicked.connect(self.workflow_authoring.import_workflow)
        workflow_tab.btn_export.clicked.connect(self.workflow_authoring.export_workflow)
        workflow_tab.btn_delete.clicked.connect(self.workflow_authoring.delete_workflow)

        # --- ROUTING OF RECALCULATE / EXTRACT BUTTONS ---
        self.ribbon.tab_acc_spectrum.btn_recalculate.clicked.connect(self.workspace.refresh_active_spectrum)
        self.ribbon.tab_acc_spectrum.cb_band_rms.toggled.connect(
            self.workspace.toggle_band_rms_cursors)
        # BUGS.md C1 used to require wrapping this in a lambda:
        # refresh_active_spectrogram took an optional `newly_opened_dock` and
        # a direct connect fed QAbstractButton.clicked's `checked` bool into
        # it, so every click was silently treated as a tab-open of a non-dock.
        # S4 (ideas/session_persistence/PLAN.md) moved the "fresh open" branch
        # into dispatch_compute's `is_fresh_open` -- refresh_active_spectrogram
        # takes no extra parameter to feed anymore, so a direct connect is safe.
        self.ribbon.tab_acc_spectrogram.btn_recalculate.clicked.connect(
            self.workspace.refresh_active_spectrogram)
        self.ribbon.tab_acc_order_tracking.btn_recalculate.clicked.connect(
            self.workspace.refresh_active_order_tracking)
        self.ribbon.tab_acc_overall_level.btn_recalculate.clicked.connect(
            self.workspace.refresh_active_overall_level)
        # "Refresh Last N" (S8, ideas/session_persistence/PLAN.md) -- the
        # dropdown RefreshSplitButton adds beside the plain Refresh above.
        self.ribbon.tab_acc_spectrum.btn_recalculate.refresh_last_n_requested.connect(
            self.workspace.refresh_last_n_curves)
        self.ribbon.tab_acc_order_tracking.btn_recalculate.refresh_last_n_requested.connect(
            self.workspace.refresh_last_n_curves)
        # Overall Level has no overlay concept this ticket (#125) -- wired anyway
        # so its dropdown's "Go" logs the same "needs an active spectrum or
        # order tracking tab" warning refresh_last_n_curves already gives any
        # other kind of tab, instead of doing nothing silently.
        self.ribbon.tab_acc_overall_level.btn_recalculate.refresh_last_n_requested.connect(
            self.workspace.refresh_last_n_curves)

        for ribbon_tab, analysis_kind in (
            (self.ribbon.tab_acc_spectrum, resolve_analysis_mode(ANALYSIS_MODE_ACC_SPECTRUM).analysis_kind),
            (self.ribbon.tab_acc_spectrogram, resolve_analysis_mode(ANALYSIS_MODE_ACC_SPECTROGRAM).analysis_kind),
            (self.ribbon.tab_acc_order_tracking, resolve_analysis_mode(ANALYSIS_MODE_ACC_ORDER_TRACKING).analysis_kind),
            (self.ribbon.tab_acc_overall_level, resolve_analysis_mode(ANALYSIS_MODE_ACC_OVERALL_LEVEL).analysis_kind),
        ):
            ribbon_tab.sig_display_settings_changed.connect(functools.partial(
                self.workspace.rebuild_active_dock_display_settings, analysis_kind))

        # One "Compute Result Set..." button per analysis tab; the dialog it
        # opens routes folder-vs-query -- see batch_run.py.
        self.ribbon.tab_acc_order_tracking.save_section.button.clicked.connect(
            self.batch_run.open_compute_result_set_order_tracking)
        self.ribbon.tab_acc_spectrum.save_section.button.clicked.connect(
            self.batch_run.open_compute_result_set_spectrum)
        self.ribbon.tab_acc_spectrogram.save_section.button.clicked.connect(
            self.batch_run.open_compute_result_set_spectrogram)
        self.ribbon.tab_acc_overall_level.save_section.button.clicked.connect(
            self.batch_run.open_compute_result_set_overall_level)

        # --- FILTER PANEL ---
        filter_routing = self.filter_routing
        self.filter_panel.btn_configure_filters.clicked.connect(
            filter_routing.open_filter_field_selection)
        # Auto-apply: any facet checkbox re-plots -- see filter_routing
        # module docstring for why there is no explicit Apply button.
        # selection_changed only redraws immediately whichever dock is
        # focused (S3, R6'); dock_focus_changed (below) catches up an edit
        # made while a different dock had focus.
        self.filter_panel.selection_changed.connect(filter_routing.selection_changed)
        self.filter_panel.active_profile_focus_changed.connect(
            filter_routing.active_profile_focus_changed)
        self.filter_panel.profile_duplicated.connect(filter_routing.profile_duplicated)
        self.filter_panel.profiles_changed.connect(filter_routing.profiles_changed)
        self.filter_panel.active_profile_chosen.connect(filter_routing.active_profile_chosen)
        # Which dock's Local filter tabs show, and catches the focused dock up
        # to a filter edit made while it did not have focus (S3, R2'/R6').
        self.workspace_tabs.currentChanged.connect(
            lambda idx: filter_routing.dock_focus_changed(self.workspace_tabs.widget(idx)))
        # The Evaluation card (ADR §1.64 point 5) recomputes on the same
        # dock-focus event the Filter panel routes on.
        self.workspace_tabs.currentChanged.connect(
            lambda idx: self.evaluation_panel.on_dock_focus_changed(self.workspace_tabs.widget(idx)))

        # The pool redraws on any facet change, but only rebuilds its facets
        # when the checkbox itself moves: switching it on brings the pool's own
        # measurements in as a source of filter values, which changes what the
        # panel has to offer.
        self.filter_panel.selection_changed.connect(filter_routing.refresh_data_pool_filter)
        self.filter_panel.data_pool_filter_toggled.connect(filter_routing.toggle_data_pool_filter)
        # The panel-wide "Show all" switch: blanks every mask and the pool
        # narrowing at once, checked values kept (ADR §1.32).
        self.filter_panel.show_all_toggled.connect(filter_routing.toggle_show_all)

        settings_tab = self.ribbon.tab_settings
        settings_tab.btn_check_updates.clicked.connect(self.update_handler.run_manual_check)
        layout = self.workspace_layout
        settings_tab.btn_toggle_explorer.clicked.connect(
            lambda: layout.toggle_dock(layout.explorer_dock))
        settings_tab.btn_toggle_filters.clicked.connect(
            lambda: layout.toggle_dock(layout.filter_dock))
        settings_tab.btn_toggle_log.clicked.connect(
            lambda: layout.toggle_bottom_tab(self.log_panel))
        settings_tab.btn_toggle_jobs.clicked.connect(
            lambda: layout.toggle_bottom_tab(self.jobs_panel))
        self.job_status_bar.open_jobs_requested.connect(
            lambda: layout.show_bottom_tab(self.jobs_panel))
        settings_tab.btn_toggle_evaluation.clicked.connect(
            lambda: layout.toggle_bottom_tab(self.evaluation_panel))
        settings_tab.btn_global_units.clicked.connect(
            self.window_settings.open_global_units_dialog)
        settings_tab.btn_run_benchmark.clicked.connect(self._open_benchmark_dialog)

        # The X axis unit belongs to the open project (issue #459); a project
        # swap re-syncs the combo through ProjectDocumentHandler.refresh_project_ui.
        settings_tab.set_x_axis_unit(self.app_context.project_session.x_axis_unit)
        settings_tab.combo_x_axis_unit.currentIndexChanged.connect(
            lambda _: self.window_settings.apply_x_axis_unit(settings_tab.x_axis_unit()))

        # Startup behaviour lives in shared_settings so both windows agree on it;
        # ProjectDocumentHandler.run_startup reads it on the next launch.
        shared = self.app_context.shared_settings
        settings_tab.cb_open_last_project.setChecked(
            shared.value("open_last_project_on_startup", False, type=bool))
        settings_tab.cb_open_last_project.toggled.connect(
            lambda on: shared.setValue("open_last_project_on_startup", on))

        # Result-cache compression is application-wide (shared_settings) and is
        # read at write time from AppContext, so a change takes effect on the
        # next batch without touching anything already on disk (ADR §1.21).
        settings_tab.set_cache_compression(self.app_context.result_cache_compression)
        settings_tab.combo_cache_compression.currentIndexChanged.connect(
            lambda _: self.window_settings.apply_cache_compression(
                settings_tab.cache_compression()))
        settings_tab.set_use_result_cache_lookup(self.app_context.use_result_cache_lookup)
        settings_tab.cb_use_result_cache_lookup.toggled.connect(
            self.window_settings.apply_use_result_cache_lookup)

        settings_tab.btn_reset_layout.clicked.connect(self.window_settings.reset_layout)
        settings_tab.btn_reset_all_settings.clicked.connect(self.window_settings.reset_all_settings)

        # The window has two states: the Welcome page (no project) and the
        # workspace (docks + graphs). One stack, one place that swaps them, so
        # "no project" always looks the same however it was reached -- fresh
        # start, or a project closed. See _set_project_ui_enabled.
        self.welcome_page = WelcomePage(job_runner=self.job_manager)
        self.welcome_page.set_changelog(read_changelog())
        self.welcome_page.new_project_requested.connect(self.project_document.new_project)
        self.welcome_page.open_project_requested.connect(
            lambda: self.project_document.open_project())
        self.welcome_page.open_recent_requested.connect(self.project_document.open_project)
        self.welcome_page.path_dropped.connect(self.project_document.try_open_dropped_path)

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.welcome_page)               # index 0
        self.view_stack.addWidget(self.workspace_layout.sub_area)  # index 1
        master_layout.addWidget(self.view_stack)

        self._project_active = False
        self._set_project_ui_enabled(False)

    # ---- frameless title bar --------------------------------------------

    def _open_benchmark_dialog(self) -> None:
        from gui.benchmark import BenchmarkDialog

        dialog = BenchmarkDialog(app_context=self.app_context, parent=self)
        dialog.exec()
        dialog.deleteLater()

    def _build_window_chrome(self, master_layout) -> None:
        """
        One top row (the title bar): app icon, Save, the ribbon's tabs, the
        title centred, min/max/close on the right. Its empty space is the
        window's drag caption -- registered later in bind_frameless_window.
        """
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
        from PySide6.QtWidgets import QLabel, QTabBar
        from core.asset_paths import resource_path
        from core.app_metadata import window_title
        from gui.ribbon.ribbon_widgets import make_ribbon_button
        from gui.shell.title_bar import DraggableTabBar, TitleStrip, WindowControls

        icon = QLabel()
        icon.setPixmap(QIcon(resource_path("resources", "icons", "app_icon.png")).pixmap(18, 18))

        # Icon-only neutral (grey, bordered) button so it reads as a button
        # without the loud commit green; sits before the title.
        self.btn_titlebar_save = make_ribbon_button(
            "", kind="neutral", tooltip="Save project")
        # The black-on-transparent floppy is tinted light so it shows on the
        # dark button; zero padding gives the glyph the whole button.
        # The PNG is black on opaque white: its inverted luminance is the alpha.
        mask = QImage(resource_path("resources", "icons", "disk.png")).scaled(
            48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
        ).convertToFormat(QImage.Format_Grayscale8)
        mask.invertPixels()
        disk = QImage(mask.size(), QImage.Format_ARGB32)
        disk.fill(QColor("#ffffff"))
        disk.setAlphaChannel(mask)
        # Downscaling thins the strokes to faint half-alpha; stacking the glyph
        # on itself makes them solid.
        bold = QImage(disk.size(), QImage.Format_ARGB32)
        bold.fill(Qt.transparent)
        painter = QPainter(bold)
        for _ in range(3):
            painter.drawImage(0, 0, disk)
        painter.end()
        disk = bold
        self.btn_titlebar_save.setIcon(QIcon(QPixmap.fromImage(disk)))
        # Icon-only style: with the default text-beside-icon and no text the
        # glyph sits off-centre.
        self.btn_titlebar_save.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.btn_titlebar_save.setIconSize(QSize(16, 16))
        self.btn_titlebar_save.setStyleSheet(
            self.btn_titlebar_save.styleSheet()
            + "QToolButton { padding: 0; border-radius: 3px; }")
        self.btn_titlebar_save.setFixedSize(_TITLEBAR_HEIGHT - 4, _TITLEBAR_HEIGHT - 4)
        self.btn_titlebar_save.setFocusPolicy(Qt.NoFocus)

        # The ribbon's own tab row is hidden; this bar mirrors it in the title
        # strip, so the tabs and the strip share one row.
        tabs = DraggableTabBar()
        tabs.setExpanding(False)
        tabs.setDrawBase(False)
        tabs.setFocusPolicy(Qt.NoFocus)
        tabs.setStyleSheet(
            "QTabBar::tab { min-height: 22px; padding: 0 12px; margin: 0;"
            "  border: 1px solid rgba(128,128,128,110); background: transparent; }"
            "QTabBar::tab:selected { background: rgba(128,128,128,80); }"
            "QTabBar::tab:hover:!selected { background: rgba(128,128,128,40); }")
        for i in range(self.ribbon.count()):
            tabs.addTab(self.ribbon.tabText(i))
        self.ribbon.tabBar().hide()
        tabs.setCurrentIndex(self.ribbon.currentIndex())
        tabs.currentChanged.connect(self.ribbon.setCurrentIndex)
        self.ribbon.currentChanged.connect(tabs.setCurrentIndex)
        self.title_tabs = tabs
        self.title_tabs.setObjectName("RibbonTabs")

        self.window_controls = WindowControls()
        strip = TitleStrip([icon, self.btn_titlebar_save, tabs], self.window_controls)
        strip.setFixedHeight(_TITLEBAR_HEIGHT)
        self.lbl_titlebar_title = strip.title
        strip.set_title(window_title())
        self._titlebar_brand = strip
        master_layout.addWidget(strip)

        # Late-bound: _build_window_chrome runs at the top of init_ui(), long
        # before the handler exists.
        self.btn_titlebar_save.clicked.connect(lambda: self.project_document.save_project())

    def bind_frameless_window(self, window) -> None:
        """Called by the shell so it can treat the ribbon strip as its title
        bar -- caption drag areas plus the maximise/restore glyph."""
        tab_bar = self.title_tabs
        # The strip's empty space is the strip widget itself; _DragArea refuses
        # any point sitting on a child (icon, Save, tabs, controls).
        window.register_drag_area(self._titlebar_brand)
        window.register_drag_area(tab_bar, veto=lambda p: tab_bar.isEnabled() and tab_bar.tabAt(p) != -1)
        # A real title bar drags by its title text as well.
        window.register_drag_area(self.lbl_titlebar_title)
        window.maximised_changed.connect(self.window_controls.sync_maximised)

    def set_titlebar_text(self, text: str) -> None:
        self._titlebar_brand.set_title(text)

    # ---- welcome / workspace state ----------------------------------------

    def _set_project_ui_enabled(self, active: bool) -> None:
        """
        The single switch between the Welcome page and the workspace.

        The ribbon tabs are disabled rather than hidden so the strip's height
        does not jump when a project opens; the docks live inside sub_area,
        which the stack hides wholesale.
        """
        self._project_active = active
        # Disable the tabs and their pages, but NOT the whole QTabWidget: the
        # window controls live in its corner now, and a disabled ancestor would
        # trap the user on a Welcome page they cannot minimise or close.
        self.title_tabs.setEnabled(active)
        # Each page stays enabled so its Help group works on the Welcome page; every
        # other group of the page follows the project state.
        for i in range(self.ribbon.count()):
            page = self.ribbon.widget(i)
            page.setEnabled(True)
            for group in page.findChildren(RibbonGroup, options=Qt.FindChildOption.FindDirectChildrenOnly):
                group.setEnabled(active or group.objectName() == "RibbonGroupHelp")
        self.view_stack.setCurrentWidget(
            self.workspace_layout.sub_area if active else self.welcome_page)
        if not active:
            self.welcome_page.set_recent(self.app_context.recent_projects_detailed())
        elif not self._layout_restored:
            # First time the docks are on screen: now sub_area has a real size,
            # so restoreState() can place the dock splitters where the user left
            # them. Deferred one tick so the stack's resize event lands first.
            self._layout_restored = True
            # 3-arg form: the window can be closed within the timer's delay,
            # and without a receiver context the callback would then fire
            # against a deleted C++ dock and raise RuntimeError.
            QTimer.singleShot(0, self, self.workspace_layout.restore_state)
        elif active:
            # Re-assert the saved Explorer width on every later workspace show --
            # the frameless resize churn can nudge it between now and then.
            QTimer.singleShot(0, self, self.workspace_layout.apply_saved_explorer_width)
            QTimer.singleShot(0, self, self.workspace_layout.apply_saved_bottom_height)

    def _create_selection_for_workflow(self) -> None:
        name = self.explorer_panel.selections_panel.create_selection()
        if name is not None:
            self.workflow_view.select_input_selection(name)

    def show_workflow_view(self, on: bool) -> None:
        """Swap sub_area's centre between the analysis docks and the Workflow
        panel, driven by the ribbon's Workflow tab (ADR §1.6 phase 7C). The
        Explorer's Block Pool tab rides along -- it only makes sense next to
        the workflow."""
        self.center_stack.setCurrentWidget(
            self.workflow_view if on else self.workspace_tabs
        )
        self.explorer_panel.set_block_pool_visible(on)
        if on:
            self.workflow_view.refresh()

    def show_workspace(self) -> None:
        self._set_project_ui_enabled(True)

    def show_welcome(self) -> None:
        self._set_project_ui_enabled(False)

    def close_workspace_dependencies(self, wait_for_jobs: bool = False) -> bool:
        update_handler = getattr(self, "update_handler", None)
        if update_handler is not None:
            update_handler.cancel_download()
        # Disconnect the cache adopter so saving a closing/closed session does
        # not attempt to submit work to a destroyed QtJobRunner.
        session = getattr(getattr(self, "app_context", None), "project_session", None)
        if session is not None:
            session.set_cache_adopter(None)

        # The folder watcher outlives the widgets it would refresh otherwise,
        # and a notification arriving after the window is gone rebuilds a tree
        # that no longer exists.
        explorer = getattr(self, "explorer_panel", None)
        if explorer is not None and getattr(explorer, "watcher", None) is not None:
            explorer.watcher.stop()

        # The job queue outlives the window too. Left running, its GUI-thread
        # callbacks fire against a window that is gone: _on_run_done commits
        # result sets into a dead ProjectSession (their folders stay on disk
        # with no saved .nvhproj naming them -> orphaned cache dirs), and pool
        # ingest steps refresh a destroyed explorer -> RuntimeError in a Qt
        # slot (audit 02, finding 3.5). Cancel drops queued steps and lets
        # CancelToken-aware steps stop mid-way; a cancelled run discards what
        # it already wrote. Only the last window blocks on the wait, and with
        # a short limit so the user is not kept waiting indefinitely on a
        # long step -- a still-open window must keep working meanwhile.
        # If the wait times out, un-cancellable steps remaining in the pool
        # require a hard exit on shutdown to avoid lingering as an invisible
        # process (#414). Returns whether all pools drained.
        idle = True
        job_manager = getattr(self, "job_manager", None)
        if job_manager is not None:
            job_manager.cancel_all()
            if wait_for_jobs:
                idle = job_manager.wait_for_done(2000)
        return idle
