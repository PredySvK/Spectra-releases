# =====================================================================
# FILE: gui/handlers/project_document.py
# =====================================================================
"""
Every command that changes which project is open (ARCHITECTURE_DECISIONS
§1.78).

`ProjectDocumentHandler` owns what were four modules until #236:

  * `project_actions.py` -- New / Open / Save / Save As / Open recent, plus the
    unsaved-work prompt and the window refresh they all end with;
  * `app_startup.py` -- which of the two views the window opens on;
  * `open_metadata_editor.py` -- the metadata schema editor, which needs a
    project file to store the schema in;
  * `select_data_directory.py` -- the Project tab's "add a measurement folder"
    browser.

They are one handler because all of it changes the same one thing -- which
project is open and what is in it -- and every one of those changes has to
bring the same window back in line afterwards: the title, the recent list, the
Result Pool, the Workflow panel. That tail is `refresh_project_ui`, and a cut
between a "document" handler and a "schema" handler would have run straight
through it.

`ask_for_project_path` stays a module function (#227, spec #148): it takes an
app context and a Qt parent, and three other areas (filter routing, batch runs,
this handler) ask it for a path -- as a method they would all need a project
handler just to ask.

Lives in gui/: it drives Qt dialogs and ProjectSession, so it cannot sit any
lower. Built once by the composition root (`gui/main_window.py`).
`show_welcome`, `show_workspace` and `set_titlebar_text` arrive as callables
rather than as the objects behind them: their owners (`welcome_page`,
`view_stack`) are built at the end of `init_ui()`, long after this handler, so
there is no object to hand over at construction time. Data Pool restoration is
owned directly by this handler because all of its dependencies already exist.

All internal documentation strings and variable labels are standardly written
in English.
"""

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from core.jobs import job_step
from core.project_model import PROJECT_EXTENSION
from gui.project_claim import ProjectClaim, activate_holder
from gui.dialogs.metadata_editor_dialog import MetadataEditorDialog
from io_modules.measurement_files import SUPPORTED_EXTENSIONS, holds_measurement_suffix
from io_modules.project_store import ProjectFormatError
from orchestration.channel_pairing import (
    copy_project_channel_pairing, read_project_channel_pairing)
from orchestration.data_pool import save_metadata_schema
from orchestration.jobs import SynchronousJobRunner

PROJECT_FILTER = f"NVH Project (*{PROJECT_EXTENSION});;All Files (*.*)"

# Built from the one measurement-extension list so a new format shows up here
# the moment it is added there, instead of staying hidden behind a stale string.
_NAME_FILTER = f"Supported NVH Files ({' '.join(SUPPORTED_EXTENSIONS)});;All Files (*.*)"

# One read of channel_pairing.xlsx per purpose ("open", "editor"): a
# newer job for the same purpose supersedes the older, the other purposes' stay.
_PAIRING_SLOT = "project_document.channel_pairing"


# ---------------------------------------------------------------------------
# shared module function
# ---------------------------------------------------------------------------

def ask_for_project_path(app_context, parent_widget) -> str:
    """
    Asks where to put a project file. Returns "" if the user cancelled.

    Handed to ProjectSession.ensure_saved as its path provider, which is how a
    metadata edit or a batch run gets somewhere to store itself without that
    layer knowing a dialog exists. Takes app_context and a Qt parent
    separately -- rather than a frame -- so callers that have no project
    handler of their own (filter routing, batch runs) do not need one just to
    ask this (#227).
    """
    session = app_context.project_session
    suggested = session.path or os.path.join(
        _default_directory(app_context),
        f"{session.project.name}{PROJECT_EXTENSION}",
    )

    chosen, _ = QFileDialog.getSaveFileName(
        parent_widget, "Save NVH Project As…", suggested, PROJECT_FILTER
    )
    if not chosen:
        return ""

    # A user who types a bare name should still get a project file.
    if not chosen.lower().endswith(PROJECT_EXTENSION):
        chosen += PROJECT_EXTENSION
    return chosen


def ensure_project_saved(app_context, parent_widget) -> bool:
    """
    Guarantees the open project has a file, asking for one if it does not --
    the shared gate the metadata editor, Configure Filters and the batch/
    workflow runners all use before they act on a decision worth keeping.

    Wraps ProjectSession.ensure_saved with the same try/except Save / Save As
    already use: a path the user cannot write to (a read-only share, a folder
    with no permission) would otherwise raise OSError or ValueError straight
    through to the three callers and on to sys.excepthook (#370). Reports the
    failure the same way and returns False, exactly as if the user had
    declined to choose a path.
    """
    session = app_context.project_session
    try:
        return session.ensure_saved(
            lambda: ask_for_project_path(app_context, parent_widget))
    except (OSError, ValueError) as error:
        QMessageBox.critical(
            parent_widget, "Cannot save project",
            f"The project was not saved.\n\n{error}",
        )
        app_context.log(f"PROJECT: Save failed: {error}")
        return False


def _default_directory(app_context) -> str:
    return app_context.active_directory or os.path.expanduser("~")


class ProjectDocumentHandler:
    """
    The one owner of "which project is open": the Project ribbon tab's document
    commands, the startup view, the metadata schema editor and the data-folder
    browser (ADR §1.78, ticket #236). See the module docstring for why they are
    one class.
    """

    def __init__(self, app_context, project_ribbon_tab, workspace, explorer_panel,
                 filter_panel, filter_routing, live_order_results, workflow_view,
                 log_panel, data_pool, parent_widget, *, show_welcome, show_workspace,
                 set_titlebar_text, show_x_axis_unit=None, job_runner=None):
        self.app_context = app_context
        # A caller that only drives part of this (a test frame, a spawned
        # view-only workspace) may carry none of the panels -- every read below
        # tolerates None rather than assuming the whole window is there.
        self.project_ribbon_tab = project_ribbon_tab
        self.workspace = workspace
        self.explorer_panel = explorer_panel
        self.filter_panel = filter_panel
        self.filter_routing = filter_routing
        self.live_order_results = live_order_results
        self.workflow_view = workflow_view
        self.log_panel = log_panel
        self.data_pool = data_pool
        self.parent_widget = parent_widget
        self.show_welcome = show_welcome
        self.show_workspace = show_workspace
        self.set_titlebar_text = set_titlebar_text
        # The Settings tab's View/X axis unit combo, re-synced to whichever
        # project is open (issue #459); None for a caller with no ribbon.
        self.show_x_axis_unit = show_x_axis_unit
        # Reads channel_pairing.xlsx off the GUI thread; a caller without a
        # queue (a test frame) gets the inline runner.
        self.job_runner = job_runner or SynchronousJobRunner()
        # Marks the open project as taken for other Spectra processes (#546).
        self.claim = ProjectClaim()
        self.claim.activation_requested.connect(self._raise_window)

    # =========================================================================
    # THE SHARED TAIL
    # =========================================================================

    def confirm_discarding_unsaved(self, action_label: str) -> bool:
        """
        Offers to save before an action that would drop the current project.

        Returns False only when the user backs out entirely. A failed save also
        returns False, so nothing is discarded on the strength of a save that did
        not actually happen.
        """
        context = self.app_context
        session = context.project_session

        if session.is_dirty:
            message = f"'{session.project.name}' has unsaved changes.\n\nSave before {action_label}?"
        elif not session.has_file and getattr(context.pool, "pool_directories", None):
            # An Untitled project never goes dirty just for holding pool folders
            # (ProjectSession does this on purpose, so browsing a folder and
            # leaving asks nothing). But the pool is a working set the user
            # deliberately assembled, and it lives nowhere but this session --
            # discarding it without a word is the loss this guards against.
            message = (
                f"'{session.project.name}' has data loaded but has never been saved.\n\n"
                f"Save it as a project file before {action_label}?"
            )
        else:
            return True

        answer = QMessageBox.question(
            self.parent_widget,
            "Unsaved changes",
            message,
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Discard:
            return True
        return self.save_project()

    def _raise_window(self) -> None:
        """Brings this window to the front when another launch asks for its project."""
        window = self.parent_widget.window() if self.parent_widget is not None else None
        if window is not None:
            window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
            window.show()
            window.raise_()
            window.activateWindow()

    def refresh_project_ui(self) -> None:
        """Brings the window title and the recent list in line with the session."""
        context = self.app_context
        session = context.project_session
        self.claim.hold(getattr(session, "path", None))

        shell = self.parent_widget.window() if self.parent_widget is not None else None
        if shell is not None:
            from core.app_metadata import window_title
            title = window_title(session.display_name)
            shell.setWindowTitle(title)
            # The frameless bar shows its own copy of the title.
            self.set_titlebar_text(title)

        if self.project_ribbon_tab is not None:
            self.project_ribbon_tab.populate_recent(context.recent_projects())

        if self.show_x_axis_unit is not None:
            self.show_x_axis_unit(session.x_axis_unit)

        # Covers opening a project and a finished batch run in one place: the
        # runner's run_finished goes through bind_run_finished below, and both
        # can change the project's result-set list.
        result_pool = getattr(self.explorer_panel, "result_pool_panel", None)
        if result_pool is not None:
            result_pool.rebuild()

        # The Workflow panel lists the project's stored workflows; a new/opened
        # project has a different set (ADR §1.6 phase 7C).
        if self.workflow_view is not None:
            self.workflow_view.refresh()

    def bind_run_finished(self, workflow_runner) -> None:
        """
        Refreshes the window once a batch run finishes, whatever it decided.

        Kept off main_window.py so the wiring itself -- not just
        refresh_project_ui -- has a test (ADR §1.73, #223: before this, a broken
        rename here would only show up by starting the app).
        """
        workflow_runner.run_finished.connect(
            lambda _label, _ok: self.refresh_project_ui())

    def _enter_workspace(self) -> None:
        """Leaves the Welcome page for the workspace once a project is live."""
        if self.show_workspace is not None:
            self.show_workspace()

    def _reset_workspace(self) -> None:
        """Closes the outgoing project's analysis tabs when a project is swapped."""
        if self.workspace is not None:
            self.workspace.close_all_tabs()

    def load_directory_into_workspace(self, path: str) -> None:
        """Replace the pool with one folder and ingest it in the background."""
        self.live_order_results.reset()
        if not self.app_context.pool.reset_pool_to_directory(path):
            return
        self.explorer_panel.rebuild_tree_view()
        self.explorer_panel.reveal_in_browser(path)
        self.data_pool.add_paths([path])

    def load_project_pool(self) -> None:
        """Restore the stored pool snapshot, then refresh its roots in the background."""
        context = self.app_context
        self.live_order_results.reset()

        # Any running scan belonged to the project just closed. The refresh
        # below supersedes it in the usual case, but there may be no roots.
        self.data_pool.cancel()

        recovered = context.restore_pool_from_project()
        self.explorer_panel.rebuild_tree_view()
        if recovered:
            context.log(f"POOL: Restored {recovered} measurement(s) from the project.")

        gone = len(self.explorer_panel.pool_panel.missing_paths)
        if gone:
            context.log(
                f"WARNING: {gone} measurement(s) are not on disk where the project "
                f"expects them. They are marked in the Data Pool; right-click one to locate it."
            )

        directories = context.project_session.resolved_directories()
        if directories:
            self.data_pool.refresh_directories(directories)

    def try_open_dropped_path(self, path: str) -> None:
        """Open a dropped project file or start a project from a dropped folder."""
        if path.lower().endswith(PROJECT_EXTENSION):
            self.open_project(path)
        elif os.path.isdir(path) and self.new_project():
            self.load_directory_into_workspace(path)

    # =========================================================================
    # DOCUMENT COMMANDS
    # =========================================================================

    def new_project(self) -> bool:
        if not self.confirm_discarding_unsaved("starting a new project"):
            return False

        context = self.app_context

        # The pool is the open project's working set, so it goes with the project.
        # Left standing, it showed the previous project's measurements against a
        # project that has no entry for any of them -- no test setup, no metadata,
        # no unit corrections -- and a Save As would have written that empty
        # project beside a full-looking tree.
        self.data_pool.cancel()
        self.live_order_results.reset()
        context.pool.clear_pool()
        self._reset_workspace()

        context.project_session.new_project()
        # Nothing saved yet, so this only clears out the previous project's
        # filter cards and picks (issue #372).
        if self.filter_routing is not None:
            self.filter_routing.restore_filter_state()
        context.log("PROJECT: Started a new untitled project.")
        self.explorer_panel.rebuild_tree_view()
        self.refresh_project_ui()
        self._enter_workspace()
        return True

    def open_project(self, project_path: str = "") -> bool:
        """
        Opens a project, asking for one when no path is supplied.

        The data folders are re-indexed on open, so anything added, renamed or
        removed while the project was closed is reported rather than discovered
        later as a missing file.
        """
        if not self.confirm_discarding_unsaved("opening another project"):
            return False

        context = self.app_context
        if not project_path:
            project_path, _ = QFileDialog.getOpenFileName(
                self.parent_widget, "Open NVH Project",
                _default_directory(context), PROJECT_FILTER,
            )
            if not project_path:
                return False

        if not self.claim.owns(project_path) and activate_holder(project_path):
            context.log(f"PROJECT: {os.path.basename(project_path)} is already open in another "
                        f"Spectra window; switched to it.")
            return False

        try:
            # Load the stored project only; the data folders are re-read in the
            # background by load_project_pool below (audit 02, S6/6.1 --
            # index_all_roots on the GUI thread froze the window on open, worst on
            # the slow/network drives it most needs to stay responsive for). The
            # tree is drawn from the stored snapshot at once and the background
            # scan reconciles it folder by folder, marking the project unsaved if
            # disk moved on; missing files are reported by load_project_pool.
            session = context.project_session
            session.load_project_file(project_path)
        except (OSError, ValueError, ProjectFormatError) as error:
            QMessageBox.critical(
                self.parent_widget, "Cannot open project",
                f"{os.path.basename(project_path)} could not be opened.\n\n{error}",
            )
            context.log(f"PROJECT: Failed to open {project_path}: {error}")
            return False

        context.remember_project(project_path)
        self._read_channel_pairing("open", self._keep_channel_pairs)
        self._reset_workspace()
        context.log(
            f"PROJECT: Opened '{session.project.name}' "
            f"({len(session.project.sources)} measurements)."
        )
        # Restores the project's Data Pool -- every folder, not just the first
        # one: the pool spans as many as the user added, and loading only one
        # used to leave the rest of a multi-root project looking like it had
        # lost its data. load_project_pool shows the stored snapshot before
        # the folders are re-read.
        self.load_project_pool()

        if self.filter_routing is not None:
            self.filter_routing.restore_filter_state()

        if self.workspace is not None:
            self.workspace.restore_open_tabs()

            # A restored dock takes back its saved id (§1.94), so a custom Local
            # filter card whose owner did not come back -- its recipe was
            # skipped, or the project predates saved dock ids -- is orphaned;
            # discard it now that every restored shell is up (§1.37).
            if self.filter_panel is not None:
                self.filter_panel.prune_orphan_dock_cards(self.workspace.open_dock_ids())

        self.refresh_project_ui()
        self._enter_workspace()
        return True

    def save_project(self) -> bool:
        """Saves, falling back to Save As when the project has no file yet."""
        context = self.app_context
        session = context.project_session
        if not session.has_file:
            return self.save_project_as()

        if self.workspace is not None:
            self.workspace.persist_open_tabs()
        try:
            session.save()
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self.parent_widget, "Cannot save project",
                f"The project was not saved.\n\n{error}",
            )
            context.log(f"PROJECT: Save failed: {error}")
            return False

        context.remember_project(session.path)
        context.log(f"PROJECT: Saved {session.path}")
        self.refresh_project_ui()
        return True

    def save_project_as(self) -> bool:
        context = self.app_context
        chosen = ask_for_project_path(context, self.parent_widget)
        if not chosen:
            return False

        if self.workspace is not None:
            self.workspace.persist_open_tabs()
        old_path = context.project_session.path
        try:
            context.project_session.save_as(chosen)
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self.parent_widget, "Cannot save project",
                f"The project was not saved.\n\n{error}",
            )
            context.log(f"PROJECT: Save failed: {error}")
            return False

        if old_path:
            # The pairs live beside the project file, so a new folder needs the workbook too.
            # Copied on the GUI thread (§1.137): a background copy raced the editor's
            # read, which created an empty workbook first and made the copy skip.
            try:
                copy_project_channel_pairing(old_path, chosen)
            except OSError as error:
                context.log(f"WARNING: Channel pairing not copied to the new folder: {error}")
        context.remember_project(chosen)
        context.log(f"PROJECT: Saved {chosen}")
        self.refresh_project_ui()
        return True

    def open_recent_project(self) -> bool:
        """Opens whatever the recent drop-down is pointing at."""
        tab = self.project_ribbon_tab
        chosen = tab.selected_recent_path()
        tab.reset_recent_selection()

        if not chosen:
            return False
        return self.open_project(chosen)

    # =========================================================================
    # STARTUP
    # =========================================================================

    def run_startup(self, project_path: str | None = None) -> None:
        """Validates baseline variables and picks the opening view."""
        context = self.app_context

        from core.app_metadata import APP_NAME
        self.log_panel.log_message(f"SYSTEM: {APP_NAME} startup sequence complete.")

        # "Open last project on startup" (Settings tab checkbox). Opt-in. When it
        # succeeds open_project has already switched to the workspace and
        # restored the project's own pool.
        if project_path is not None:
            # An explicit launch must not fall back to a different recent project
            # when it fails: open_project reports the error, Welcome stays empty.
            if self.open_project(project_path):
                return
        elif context.shared_settings.value("open_last_project_on_startup", False, type=bool):
            recent = context.recent_projects()
            if recent and self.open_project(recent[0]):
                return

        # Otherwise: the Welcome page. No project is open, so the ribbon and docks
        # stay disabled until the user picks New or Open. active_directory is left
        # as it is -- it still seeds file dialogs and the first data folder.
        self.show_welcome()
        self.refresh_project_ui()

    # =========================================================================
    # METADATA SCHEMA
    # =========================================================================

    def open_metadata_editor(self) -> None:
        """
        Opens the dynamic Metadata Schema Editor dashboard.

        The schema -- which metadata fields are shown and what they are called --
        is a user decision, so it is stored in the project rather than in the
        folder cache, which is derived from the measurement files and may be
        deleted to force a re-scan. Editing therefore requires a project with
        somewhere to live, which is what ensure_saved asks for.
        """
        context = self.app_context
        if not context.pool.has_data():
            self.log_panel.log_message(
                "WARNING: Metadata and Filter Settings skipped. Workspace empty.")
            return

        # A schema edit is worth keeping, so it needs a project file to be kept in.
        # Asking before the dialog rather than after means the user is not offered a
        # save prompt for work they have not done yet.
        session = context.project_session
        if not ensure_project_saved(context, self.parent_widget):
            self.log_panel.log_message(
                "SYSTEM: Metadata and Filter Settings cancelled -- the schema needs a saved project to live in."
            )
            return

        # Read again on every opening, so a hand edit made meanwhile shows (#511).
        self._read_channel_pairing("editor", self._show_metadata_editor)

    def _show_metadata_editor(self, channel_pairs, pairing_warnings) -> None:
        context = self.app_context
        session = context.project_session
        # The workbook is the truth; a hand edit counts even if the dialog is cancelled.
        session.set_channel_pairs(channel_pairs)
        schema = context.pool.schema()
        dialog = MetadataEditorDialog(
            schema.master,
            self.parent_widget,
            settings=context.settings,
            baseline_schema=getattr(schema, "baseline", None),
            project=session.project,
            project_path=session.path,
            channel_pairs=channel_pairs,
            pairing_warnings=pairing_warnings,
        )
        accepted = dialog.exec()
        finalized_schema = dialog.get_finalized_schema() if accepted else None
        # Parented to the main window, so nothing else would ever destroy it.
        dialog.deleteLater()

        if not accepted:
            return

        # Stored and saved in one step; a project that already holds other
        # unsaved edits is only marked unsaved, so the schema cannot commit
        # edits the user may still discard at close (#424). A failed save --
        # a share that dropped, a full disk -- leaves the schema safely in
        # memory and marked unsaved rather than reaching the crash handler.
        session.set_channel_pairs(dialog.channel_pairs)
        errors = save_metadata_schema(context.pool, finalized_schema)
        # Which fields are filterable, and what their values now parse to, both
        # just moved -- so did the facets on offer, and with them every open
        # graph's mask (§1.29). Done whether or not the save went through, so
        # a failed save does not leave the panel describing the old schema.
        self._refresh_filters_after_schema_change()
        if errors:
            for message in errors:
                self.log_panel.log_message(f"ERROR: {message}")
            self.refresh_project_ui()
            return

        if session.is_dirty:
            self.log_panel.log_message(
                "SYSTEM: Metadata schema updated; it will be stored with the "
                "project's other unsaved changes."
            )
        else:
            self.log_panel.log_message(
                "SYSTEM: Metadata schema updated and stored in the project."
            )

        self.explorer_panel.rebuild_tree_view()
        self.refresh_project_ui()

    # =========================================================================
    # CHANNEL PAIRING
    # =========================================================================

    def _read_channel_pairing(self, purpose: str, on_read) -> None:
        """Read the open project's channel_pairing.xlsx on the job runner (#513).

        `on_read(pairs, warnings)` runs on the GUI thread, and only while the
        same project is still open (a New or Close meanwhile drops it).
        """
        session = self.app_context.project_session
        project_path = session.path

        def deliver(result, _index):
            if session.path == project_path:
                on_read(*result)

        self.job_runner.submit(
            "Read channel pairing",
            [job_step("Read", read_project_channel_pairing, project_path)],
            lane="interactive", slot_key=f"{_PAIRING_SLOT}.{purpose}", quiet=True, on_step=deliver,
        )

    def _keep_channel_pairs(self, pairs, warnings) -> None:
        self.app_context.project_session.set_channel_pairs(pairs)
        for warning in warnings:
            self.app_context.log(f"WARNING: Channel pairing: {warning}")

    def _refresh_filters_after_schema_change(self) -> None:
        """
        Rebuilds the Filter panel's facets and every open dock's mask against the
        schema that was just saved.

        Forced rather than left to the ordinary staleness gate: a mask closes over
        the schema and source lookup it was built with, and nothing about that is
        visible in the (profile, selection, offering) key a dock compares against
        (FilterRoutingHandler.reapply_active_filter_everywhere). A window with no
        Filter routing handler (a spawned view-only workspace, a test frame) is
        skipped.
        """
        if self.filter_routing is None:
            return

        self.filter_routing.refresh_filter_panel()
        self.filter_routing.reapply_active_filter_everywhere()

    # =========================================================================
    # DATA FOLDERS
    # =========================================================================

    def select_data_directory(self) -> None:
        """
        Launches a customized directory browser and adds the selected folder to
        the Data Pool.

        The chosen folder is added rather than replacing the pool. This button
        used to be the only way in, so it wiped the workspace on every use; now
        that the pool can hold several folders, doing that would silently throw
        away everything the user had lined up. Replacing the pool outright is
        still what app startup does, where there is nothing to lose.

        Qt's own dialog is forced rather than the native one: the Windows folder
        picker hides files, and seeing the supported measurement files is how a
        user tells one folder from another.
        """
        # Opens where the user last worked, so adding a second folder of the
        # same campaign does not start from the home directory again.
        saved_path = _default_directory(self.app_context)

        dialog = QFileDialog(
            self.parent_widget, "Add an NVH Measurement folder to the Data Pool...", saved_path)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        # Explicitly NOT directories-only: that is what lets the name filter
        # below render the measurement files inside a folder selection.
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, False)
        dialog.setNameFilter(_NAME_FILTER)

        if not dialog.exec():
            return

        selected_dirs = dialog.selectedFiles()
        if not selected_dirs:
            return
        selected_dir_path = self._confirm_not_a_subfolder(selected_dirs[0])
        if selected_dir_path is None:
            return

        # Routed through the same background ingest the File Browser uses,
        # so a folder of hundred-megabyte files shows a progress bar here
        # too instead of freezing the window.
        self.data_pool.add_paths([selected_dir_path])
        self.explorer_panel.reveal_in_browser(selected_dir_path)

    def _confirm_not_a_subfolder(self, picked: str) -> Optional[str]:
        """
        Guards against Qt's folder dialog returning the highlighted subfolder
        instead of the folder the user is standing in.

        A click on a subfolder fills the dialog's name field, and Choose then
        returns that subfolder -- here typically a folder of images and
        scripts, so nothing loaded and nothing said why. When the picked folder
        holds no measurement but its parent does, the parent is offered.
        Returns the folder to add, or None when the user cancels.

        Two single-folder listings on the GUI thread, for a pick the user just
        made -- the same trade the folder watcher makes.
        """
        parent = os.path.dirname(os.path.normpath(picked))
        if (holds_measurement_suffix(picked) or not parent or parent == picked
                or not holds_measurement_suffix(parent)):
            return picked
        answer = QMessageBox.question(
            self.parent_widget, "Add to Data Pool",
            f"'{os.path.basename(picked)}' contains no measurement files, but its "
            f"parent folder does.\n\nAdd the parent folder instead?\n{parent}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            return parent
        return picked if answer == QMessageBox.StandardButton.No else None
