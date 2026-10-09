# =====================================================================
# FILE: gui/handlers/data_pool.py
# =====================================================================
"""
The window's one owner of what the Data Pool holds: adding, re-reading and
removing measurements.

Adding is the one explorer action that can take minutes. A folder of hundred-
megabyte UNV files has to have every header read before the pool can list its
channels, so doing it inline would lock the window for exactly as long as the
user is most likely to think the application has died.

The run itself -- which folders are read, in what order, what each one does to
the pool, and what the whole thing adds up to -- is
`orchestration.data_pool.PoolIngestUseCase`, submitted through the QtJobRunner
as a `JobRunner` (ADR 1.13, 1.70). What is left here is everything the use
case deliberately cannot do: the modal progress dialog, the Cancel button, the
application-shell effects of each folder (ADR 1.69), the explorer refresh, the
conflict dialog and the failure popup.

One folder is one step, so a folder of large files would otherwise be a
single jump from 0 to 100 percent. The step is given a `progress_fn` (through
the job's `progress_keyword`) that the scan calls as it re-parses each stale
file; the QtJobRunner mirrors that onto `JobRecord.sub_done/sub_total` and the
dialog reads `record.percent`.

The two hazards of background work are the manager's business
rather than this module's: a second Add supersedes the first through
`slot_key`, and Cancel goes through `job_manager.cancel`, which stops
dispatching further folders and drops what the one in flight returns.

The modal progress dialog is deliberately still here rather than being left to
the status bar, and it stays. It is the one place in the application where the
user has just clicked something and cannot usefully do anything else until the
pool exists, so the window it blocks is not a window they wanted -- and a
folder of large files is exactly the case where a status-bar line is too quiet
to reassure someone who thinks the application has hung. A refresh nobody asked
for still gets no dialog (`quiet`); the modal one is only for the explicit
click.

All internal documentation strings and variable labels are standardly written
in English.
"""

import os

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from orchestration.data_pool import PoolIngestUseCase, plan_pool_ingest


class DataPoolHandler(QObject):
    """
    Everything the window does to the Data Pool, and the one object that knows
    whether a scan is in flight.

    Long-lived rather than created per click: the progress dialog has to
    survive until the job reports back, and a handler that went out of scope
    the moment the action returned would take its own callbacks with it. It
    used to be cached on the main window for exactly that reason; the
    composition root owns it now (#240).

    Per-run state is the use case's business, not this object's: a superseded
    ingest's late-arriving folder never reaches `_on_finished` here, so the
    dialog and job id below always belong to the run currently on screen
    (audit 02, S3/3.1).

    `explorer_panel` arrives after construction: this handler has to exist
    before `UnvChannelExplorer`, which hands it down to the three panels that
    call it, while the panel it refreshes is that same explorer.
    """

    def __init__(self, app_context, job_manager, parent_widget):
        super().__init__(parent_widget)
        self.app_context = app_context
        self.parent_widget = parent_widget
        self.explorer_panel = None
        self.job_manager = job_manager
        self._use_case = PoolIngestUseCase(
            app_context.pool, app_context.project_session, job_manager
        )
        self._dialog = None
        job_manager.job_changed.connect(self._on_job_changed)

    def set_explorer_panel(self, explorer_panel) -> None:
        """Hands over the Explorer dock once the composition root has built it."""
        self.explorer_panel = explorer_panel

    @property
    def is_running(self) -> bool:
        """Whether a scan the user is waiting on is in flight."""
        return self._use_case.is_running

    # ---- what goes into the pool ---------------------------------------

    def add_paths(self, paths, ask_for_setup: bool = False) -> None:
        """Adds folders and/or individual measurements to the pool, in the background."""
        self._start(paths, ask_for_setup=ask_for_setup)

    def refresh_directories(self, directories, quiet: bool = False,
                            on_finished=None) -> None:
        """
        Re-reads folders already in the pool, without undoing what the user did to it.

        The empty file selection plus admit_unknown is the whole rule: a
        measurement written into the folder since the last scan joins the pool --
        which is the point of watching folders at all -- while one the user took
        out of the pool stays out, and an edited file is simply re-read.
        """
        plan = {directory: set() for directory in directories}
        self._start([], plan=plan, quiet=quiet, admit_unknown=True,
                    on_finished=on_finished)

    def _start(self, paths, ask_for_setup: bool = False, plan=None, quiet: bool = False,
               admit_unknown: bool = False, on_finished=None):
        # A re-scan names its folders and is ready to run; a path selection is
        # planned on the worker, because planning walks trees and reads file
        # headers (#507).
        ingest_plan = plan_pool_ingest([], plan) if plan is not None else None
        if not (ingest_plan or paths):
            return

        # A second Add supersedes the first rather than interleaving with it:
        # both would be writing into the same pool and the same project. The
        # dialog is closed here because the use case's submit cancels the old
        # job, and the old job's finish must not take the new run's dialog
        # down with it.
        self._close_dialog()

        # A refresh nobody asked for gets no dialog. The folder watcher fires
        # whenever a measurement lands on disk, and a progress window stealing
        # focus each time would make the feature something to switch off.
        if not quiet:
            # 0..100 rather than one tick per folder: a single big folder is
            # one step, and its own re-parse progress (reported through the
            # step's progress_fn) is what the user needs to see move.
            self._dialog = QProgressDialog(
                "Reading measurement folders…", "Cancel", 0, 100, self.parent_widget
            )
            self._dialog.setWindowTitle("Add to Data Pool")
            self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
            # Shown immediately: a folder already in the OS cache finishes in
            # milliseconds, but the user has just clicked and needs to see that
            # something is happening either way.
            self._dialog.setMinimumDuration(0)
            # A planned run's planning job reaches 100 % before its folder job
            # starts; the default auto-close would take the dialog, and Cancel
            # with it, down in between. _on_finished closes it.
            self._dialog.setAutoClose(False)
            self._dialog.setAutoReset(False)
            self._dialog.canceled.connect(self._cancel_running)
            self._dialog.show()

        def _done(outcome):
            if on_finished is not None:
                on_finished(outcome)
            self._on_finished(outcome)

        options = dict(quiet=quiet, admit_unknown=admit_unknown,
                       ask_for_setup=ask_for_setup,
                       on_folder=self._on_folder, on_finished=_done)
        if ingest_plan is not None:
            self._use_case.start(ingest_plan, **options)
        else:
            self._use_case.start_selection(list(paths), **options)

    @property
    def _job_id(self):
        # The use case's, not a copy: a planned run changes jobs midway, and a
        # run over before submit returns (ADR 1.70) already reports None.
        return self._use_case.job_id

    # ---- job callbacks (GUI thread) -----------------------------------

    def _on_job_changed(self, job_id: int):
        """Mirrors the step the manager is on into the modal dialog."""
        if job_id != self._job_id or self._dialog is None:
            return
        record = self.job_manager.record(job_id)
        if record is None:
            return
        self._dialog.setValue(record.percent)
        if record.step_label:
            counted = (f" ({record.sub_done}/{record.sub_total})"
                       if record.sub_total else "")
            self._dialog.setLabelText(f"Reading {record.step_label}…{counted}")

    def _on_folder(self, report):
        """Applies one folder's shell effects, as the use case reports it."""
        for message in report.log_messages:
            self.app_context.log(message)
        if report.integrated is None:
            return
        self.app_context.apply_integrate_effects(report.integrated)
        # Redrawn per folder so a long queue shows its progress in the tree
        # itself, not only in the dialog.
        self._refresh_explorer()

    def _on_finished(self, outcome):
        self._close_dialog()

        # A cancelled ingest reports nothing: the folders it did read are
        # already in the pool and in the tree, and the outcome of a run the
        # user just abandoned carries neither a summary nor conflicts.
        self._refresh_explorer()
        for message in outcome.log_messages:
            self.app_context.log(message)

        if outcome.ask_for_setup:
            from gui.file_explorer.actions.assign_test_setup import execute_assign_test_setup
            execute_assign_test_setup(self.app_context, self.explorer_panel,
                                      list(outcome.added_paths))

        self._report_conflicts(outcome)
        self._report_failures(outcome)

    # ---- reporting ----------------------------------------------------

    def _refresh_explorer(self):
        panel = self.explorer_panel
        if panel is not None:
            panel.rebuild_tree_view()
            panel.refresh_browser()

    def _report_conflicts(self, outcome):
        if not outcome.schema_conflicts:
            return
        from gui.dialogs.schema_conflict_dialog import show_schema_conflicts
        show_schema_conflicts(self.app_context, self.parent_widget,
                              list(outcome.schema_conflicts))

    def _report_failures(self, outcome):
        if not outcome.report_failures:
            return
        failures = outcome.failures
        detail = "\n".join(f"• {os.path.basename(d) or d}: {m}" for d, m in failures)
        QMessageBox.warning(
            self.parent_widget, "Some folders could not be read",
            f"{len(failures)} folder(s) were skipped:\n\n{detail}",
        )

    # ---- cancellation --------------------------------------------------

    def cancel(self):
        """
        Drops a scan in flight, results and all.

        Called whenever the project underneath the pool is replaced. The folders
        being read were queued for the project that is going away; letting them
        land afterwards registers them as data roots of the one that replaced it
        and marks that project unsaved. add_paths() already supersedes a previous
        ingest, but the paths that only sometimes queue a scan -- opening a project
        whose data roots do not resolve, or New Project, which queues none at all
        -- would otherwise leave the old one running.
        """
        self._cancel_running()

    def _cancel_running(self):
        """
        Abandons whatever is in flight.

        The folder already being read is allowed to finish -- interrupting a
        header read mid-file buys nothing -- but its result is dropped rather
        than landing in the pool afterwards, and no further folder is started.
        """
        if self._job_id is not None:
            self.job_manager.cancel(self._job_id)
        self._close_dialog()

    def _close_dialog(self):
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None

    # ---- what leaves the pool ------------------------------------------

    def remove_directories(self, directories) -> None:
        """
        Takes whole folders out of the pool from the disk browser.

        The folder stays registered with the project (its sources keep their
        metadata, unit corrections, test setup and result sets); what leaves is
        the in-memory working set and the folder's schema columns. Re-adding the
        folder brings it all back, so this needs no confirmation.
        """
        directories = [d for d in directories if d]
        if not directories:
            return

        removed = sum(self.app_context.pool.remove_pool_directory(d) for d in directories)

        self.app_context.log(
            f"POOL: Removed {len(directories)} folder(s) "
            f"({removed} measurement(s)) from the Data Pool."
        )
        self._refresh_explorer()

    def remove_measurements(self, file_paths) -> None:
        """
        Takes measurements out of the pool.

        The project keeps its entries -- their metadata, unit corrections and test
        setup, and every result set that refers to them, none of which the user
        asked to throw away. What is removed is the working set, which is what the
        pool is.
        """
        if not file_paths:
            return

        removed = self.app_context.pool.remove_pool_runs(file_paths)
        if not removed:
            return

        self.app_context.log(f"POOL: Removed {removed} measurement(s) from the Data Pool.")
        self._refresh_explorer()
