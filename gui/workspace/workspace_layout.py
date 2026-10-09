# gui/workspace/workspace_layout.py
"""
Owns the docks around the workspace -- Explorer, Filters, the job status
strip at the foot of their column, and the bottom
Output panel (System Log / Jobs / Evaluation tabs) -- plus their QSettings-
backed geometry. Split out of MainWindowFrame so the docks stop being loose
window attributes shared with gui/handlers/ (ADR §1.74).
"""
from PySide6.QtCore import Qt, QTimer

# Fresh-install width of the Explorer dock column: its tab bar needs ~300px for
# the five labels (File Browser, Data Pool, Result Pool, Selections, Block Pool).
# Overridden by a saved layout / the per-user explorer_dock_width key.
DEFAULT_EXPLORER_WIDTH = 420

# Fresh-install height of the bottom panel (System Log / Jobs / Evaluation).
# Overridden by a saved layout / the per-user bottom_dock_height key.
DEFAULT_BOTTOM_HEIGHT = 160

# Qt's "no maximum" for a widget dimension.
_QWIDGETSIZE_MAX = 16777215


class WorkspaceLayout:
    """The docks around the workspace and their saved geometry.

    Built once, in ``MainWindowFrame.init_ui()``, from the already-constructed
    dock widgets -- it does not build them itself, since building them is
    interleaved with the panels main_window.py still owns (Explorer, Filter,
    Workspace, Evaluation).
    """

    # (settings key fragment, attribute name) -- which bottom-panel tabs are on
    # is not carried by QMainWindow.saveState() (it tracks docks, not the
    # inner tab bar), so it rides its own key.
    _BOTTOM_TAB_KEYS = (("log", "log_panel"), ("jobs", "jobs_panel"),
                        ("evaluation", "evaluation_panel"))

    def __init__(self, app_context, sub_area, explorer_dock, filter_dock,
                 job_status_dock, bottom_dock, bottom_panel, log_panel, jobs_panel,
                 evaluation_panel):
        self.app_context = app_context
        self.sub_area = sub_area
        self.explorer_dock = explorer_dock
        self.filter_dock = filter_dock
        self.job_status_dock = job_status_dock
        self.bottom_dock = bottom_dock
        self.bottom_panel = bottom_panel
        self.log_panel = log_panel
        self.jobs_panel = jobs_panel
        self.evaluation_panel = evaluation_panel
        # Guard against overwriting a persisted layout with factory/uninitialized
        # state when closing from the Welcome page before any project opens (#413).
        self.is_restored: bool = False

        # Closing, floating or moving Explorer / Filters to another area all
        # change whether the strip still shares its column.
        for dock in (self.explorer_dock, self.filter_dock):
            dock.visibilityChanged.connect(self.fit_job_status_dock)
            dock.topLevelChanged.connect(self.fit_job_status_dock)
            dock.dockLocationChanged.connect(self.fit_job_status_dock)
        self.fit_job_status_dock()

    # ---- job status strip -------------------------------------------------

    def _shares_job_status_column(self, dock) -> bool:
        return (not dock.isHidden() and not dock.isFloating()
                and self.sub_area.dockWidgetArea(dock)
                == self.sub_area.dockWidgetArea(self.job_status_dock))

    def fit_job_status_dock(self, *_args) -> None:
        """Keep the job status strip at the foot of the left column.

        Normally it is pinned to its own height and Explorer / Filters take
        the rest. With neither of them left in the column -- closed, floating,
        or moved to another area -- it would be the column's only dock, and Qt
        puts a lone height-capped dock at the top. So then the cap is lifted,
        the dock fills the column, and the strip's own top stretch keeps its
        rows at the bottom."""
        height = self.job_status_dock.sizeHint().height()
        alone = not any(self._shares_job_status_column(dock)
                        for dock in (self.explorer_dock, self.filter_dock))
        self.job_status_dock.setMinimumHeight(height)
        self.job_status_dock.setMaximumHeight(_QWIDGETSIZE_MAX if alone else height)

    # ---- QSettings keys -----------------------------------------------

    def _layout_key(self) -> str:
        return "window_layout_state"

    def _explorer_width_key(self) -> str:
        return "explorer_dock_width"

    def _bottom_height_key(self) -> str:
        return "bottom_dock_height"

    def _bottom_tabs_key(self) -> str:
        return "bottom_tabs_visible"

    # ---- factory layout -------------------------------------------------

    def restore_factory(self) -> None:
        """Puts the docks back where init_ui first placed them and saves that state."""
        self.is_restored = True
        sub_area = self.sub_area

        self.explorer_dock.setVisible(True)
        self.filter_dock.setVisible(True)
        # Factory bottom panel: System Log + Jobs on. The saved key is already
        # cleared by the caller, so the panel picks this up on the next restore too.
        self.bottom_panel.set_tab_visible(self.log_panel, True)
        self.bottom_panel.set_tab_visible(self.jobs_panel, True)
        self.bottom_panel.show_tab(self.log_panel)
        self.bottom_dock.setVisible(True)

        sub_area.addDockWidget(Qt.LeftDockWidgetArea, self.explorer_dock)
        sub_area.addDockWidget(Qt.LeftDockWidgetArea, self.filter_dock)
        sub_area.splitDockWidget(self.explorer_dock, self.filter_dock, Qt.Vertical)
        sub_area.addDockWidget(Qt.LeftDockWidgetArea, self.job_status_dock)
        sub_area.splitDockWidget(self.filter_dock, self.job_status_dock, Qt.Vertical)
        sub_area.resizeDocks(
            [self.explorer_dock, self.filter_dock], [65, 35], Qt.Vertical)
        # Wide enough for the three Explorer tab labels.
        sub_area.resizeDocks(
            [self.explorer_dock], [DEFAULT_EXPLORER_WIDTH], Qt.Horizontal)
        self.apply_saved_explorer_width()

        sub_area.addDockWidget(Qt.BottomDockWidgetArea, self.bottom_dock)
        sub_area.resizeDocks([self.bottom_dock], [DEFAULT_BOTTOM_HEIGHT], Qt.Vertical)

        self.save_state()

    # ---- toggling ---------------------------------------------------------

    def toggle_dock(self, target_dock) -> None:
        target_dock.setVisible(not target_dock.isVisible())
        self.save_state()

    def toggle_bottom_tab(self, widget) -> None:
        """Settings-tab "System Log" / "Jobs" / "Evaluation" buttons. Each one
        adds or removes its own tab in the bottom panel (the Explorer's Block
        Pool does the same); the dock as a whole disappears once its last tab
        is gone and comes back when a tab is turned on."""
        self.bottom_panel.set_tab_visible(widget, not self.bottom_panel.is_tab_visible(widget))
        self.bottom_dock.setVisible(self.bottom_panel.visible_tab_count() > 0)
        self.save_state()

    def show_bottom_tab(self, widget) -> None:
        """Bring a bottom tab on and to the front -- never off, unlike
        toggle_bottom_tab. The job status strip's double-click uses it."""
        self.bottom_panel.show_tab(widget)
        self.bottom_dock.setVisible(True)
        self.save_state()

    def apply_saved_bottom_tabs(self) -> None:
        """Restore which of System Log / Jobs / Evaluation are on. Default:
        everything on."""
        raw = self.app_context.settings.value(self._bottom_tabs_key(), None)
        wanted = set(raw.split(",")) if isinstance(raw, str) else {"log", "jobs", "evaluation"}
        for key, attr in self._BOTTOM_TAB_KEYS:
            self.bottom_panel.set_tab_visible(getattr(self, attr), key in wanted)
        self.bottom_dock.setVisible(self.bottom_panel.visible_tab_count() > 0)

    # ---- persisted layout state -------------------------------------------

    def save_state(self) -> None:
        if not self.is_restored:
            return
        settings = self.app_context.settings
        settings.setValue(self._layout_key(), self.sub_area.saveState())
        # QMainWindow.saveState() carries dock sizes, but restoreState() does not
        # reliably re-apply them through the frameless window's post-show resize
        # churn -- the Explorer column in particular snapped back to its size
        # hint. Pin its width on its own key and force it after every restore.
        if self.explorer_dock.isVisible() and not self.explorer_dock.isFloating():
            width = self.explorer_dock.width()
            if width > 50:
                settings.setValue(self._explorer_width_key(), width)
        # Same story vertically for the bottom panel -- pin its height so the
        # splitter drag survives a restart.
        if self.bottom_dock.isVisible() and not self.bottom_dock.isFloating():
            height = self.bottom_dock.height()
            if height > 50:
                settings.setValue(self._bottom_height_key(), height)
        # Which bottom tabs are on -- restoreState() cannot carry this.
        visible = [key for key, attr in self._BOTTOM_TAB_KEYS
                   if self.bottom_panel.is_tab_visible(getattr(self, attr))]
        settings.setValue(self._bottom_tabs_key(), ",".join(visible))

    def restore_state(self) -> None:
        self.is_restored = True
        settings = self.app_context.settings
        saved_state = settings.value(self._layout_key(), None)
        if saved_state is not None:
            self.sub_area.restoreState(saved_state)
        self.apply_saved_bottom_tabs()
        # A dock restoreState() leaves hidden never reports visibilityChanged.
        self.fit_job_status_dock()
        self.apply_saved_explorer_width()
        self.apply_saved_bottom_height()
        # A late re-assert: on first boot the frameless window is still settling
        # its client size when the line above runs, which can override the width.
        # 3-arg form, receiver = sub_area: the window can be closed within the
        # timer's delay, and without a receiver context the callback would then
        # fire against a deleted C++ dock and raise RuntimeError.
        QTimer.singleShot(150, self.sub_area, self.apply_saved_explorer_width)
        QTimer.singleShot(150, self.sub_area, self.apply_saved_bottom_height)

    def apply_saved_explorer_width(self) -> None:
        """Force the Explorer column to the width the user left it at, or to a
        default wide enough for the three tab labels on a fresh install.

        Done here rather than at construction time because resizeDocks() only
        sticks once sub_area is laid out and visible. Idempotent -- safe on
        every show."""
        raw = self.app_context.settings.value(self._explorer_width_key(), None)
        try:
            width = int(raw)
        except (TypeError, ValueError):
            width = DEFAULT_EXPLORER_WIDTH
        if width > 50:
            self.sub_area.resizeDocks([self.explorer_dock], [width], Qt.Horizontal)

    def apply_saved_bottom_height(self) -> None:
        """Force the bottom panel to the height the user left it at, or a
        sensible default. Idempotent -- safe on every workspace show."""
        raw = self.app_context.settings.value(self._bottom_height_key(), None)
        try:
            height = int(raw)
        except (TypeError, ValueError):
            height = DEFAULT_BOTTOM_HEIGHT
        if height > 50:
            self.sub_area.resizeDocks([self.bottom_dock], [height], Qt.Vertical)
