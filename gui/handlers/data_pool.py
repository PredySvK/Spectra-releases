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
as a `JobRunner`. What is left here is everything the use
case deliberately cannot do: the modal progress dialog, the Cancel button, the
application-shell effects of each folder, the explorer refresh, the
conflict dialog and the failure popup. Editing an Import template -- from the
misfit report or the project's copy -- is the same kind of shell work: the
wizard, the consequence summary and the library question are here, replacing
the copy and re-reading its files is the use case's `start_template_edit`. An
Add with a library template that differs from the project's copy offers the
same replacement before the Add.

One folder is one step, so a folder of large files would otherwise be a
single jump from 0 to 100 percent. The step is given a `progress_fn` (through
the job's `progress_keyword`) that the scan calls as it re-parses each stale
file; the QtJobRunner mirrors that onto `JobRecord.sub_done/sub_total` and the
dialog reads `record.percent`.

The two hazards of background work are the manager's business
rather than this module's: a second Add supersedes the first through
`slot_key`, and Cancel goes through `job_runner.cancel`, which stops
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
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QProgressDialog

from orchestration.data_pool import MissingMeasurementCheck, PoolIngestUseCase
from view_models.import_template import build_template_edit_summary


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

    def __init__(self, app_context, job_runner, parent_widget, *, read_folder=None):
        super().__init__(parent_widget)
        self.app_context = app_context
        self.parent_widget = parent_widget
        self.explorer_panel = None
        self.job_runner = job_runner
        self._missing_check = MissingMeasurementCheck(
            app_context.pool, job_runner, on_checked=self._on_missing_checked
        )
        self._use_case = PoolIngestUseCase(
            app_context.pool, app_context.project_session, job_runner,
            missing_check=self._missing_check, read_folder=read_folder,
        )
        self._dialog = None
        job_runner.job_changed.connect(self._on_job_changed)

    def set_explorer_panel(self, explorer_panel) -> None:
        """Hands over the Explorer dock once the composition root has built it."""
        self.explorer_panel = explorer_panel

    @property
    def is_running(self) -> bool:
        """Whether a scan the user is waiting on is in flight."""
        return self._use_case.is_running

    # ---- what goes into the pool ---------------------------------------

    def add_paths(self, paths, ask_for_setup: bool = False, import_templates=()) -> None:
        """
        Adds folders and/or individual measurements to the pool, in the background.

        `import_templates` (ImportTemplates) read the files they fit instead of
        the suffix's reader; a file that fits none of the templates its name
        belongs to is listed in a report after the run.

        A template that differs from the project's copy of its name (a library
        change) is offered over the consequence summary first: replacing the
        copy re-reads its files before the Add, keeping it adds with the copy,
        Cancel drops the Add.
        """
        from gui.dialogs.import_template_dialog import ask_library_change
        session = self.app_context.project_session
        replacements = []
        for template in import_templates:
            copy = session.resolve_import_template(template.name)
            if copy is None or copy == template:
                continue
            summary = build_template_edit_summary(
                copy, template, filter_cards=session.project.filter_cards,
                filter_profiles=session.filter_profiles, open_tabs=session.current_open_tabs())
            replace = ask_library_change(self.parent_widget, summary)
            if replace is None:
                return
            if replace:
                replacements.append(template)
        self._replace_then(replacements, lambda: self._start(
            paths, ask_for_setup=ask_for_setup, import_templates=import_templates))

    def _replace_then(self, templates, then) -> None:
        """Replaces the project's copies by `templates` one after another, re-reading each one's files, then `then`."""
        if not templates:
            then()
            return
        self._start([], template_edit=templates[0], then=lambda: self._replace_then(templates[1:], then))

    def refresh_directories(self, directories, quiet: bool = False,
                            on_finished=None, ask_source_amplitude: bool = True) -> None:
        """
        Re-reads folders already in the pool, without undoing what the user did to it.

        The use case re-reads with an empty file selection that admits unknown
        files, and that is the whole rule: a measurement written into the folder since the last scan joins the pool --
        which is the point of watching folders at all -- while one the user took
        out of the pool stays out, and an edited file is simply re-read.

        A file the project does not know yet raises the Source amplitude
        question when it is an Imported result, so no file enters the pool on
        an assumed basis -- except when `ask_source_amplitude` is False, which
        opening a project passes: that is a routine action and stays silent.
        """
        directories = [directory for directory in directories if directory]
        self._start([], refresh=directories, quiet=quiet, on_finished=on_finished,
                    ask_source_amplitude=ask_source_amplitude)

    def check_missing_after_project_open(self) -> None:
        """
        Finds the restored pool's Missing measurements on a worker; the tree
        marks them, and the log counts them, once the check lands.
        """
        self._missing_check.start(after_project_open=True)

    def _ask_source_amplitude(self, questions):
        """The Source amplitude question, with the progress dialog out of its way."""
        from gui.dialogs.source_amplitude_dialog import ask_source_amplitudes
        return self._ask_unobstructed(ask_source_amplitudes, questions)

    def _ask_unobstructed(self, ask, questions):
        progress = self._dialog
        if progress is not None:
            progress.hide()
        try:
            return ask(self.parent_widget, questions)
        finally:
            if progress is not None and self._dialog is progress:
                progress.show()

    def _ask_import_template(self, questions):
        """The which-template question, with the progress dialog out of its way."""
        from gui.dialogs.import_template_dialog import ask_import_templates
        return self._ask_unobstructed(ask_import_templates, questions)

    def _start(self, paths, ask_for_setup: bool = False, quiet: bool = False,
               on_finished=None, refresh=None, ask_source_amplitude: bool = True,
               import_templates=(), template_edit=None, then=None):
        # Every kind is planned on the worker, because planning walks trees and
        # reads file headers (#507); which flags belong to which kind is the use
        # case's to decide. `then` runs after a completed run's own reports, so
        # a run it starts does not have its dialog closed by this one's finish.
        if not (paths or refresh or template_edit):
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
            if then is not None and outcome.completed:
                then()

        if template_edit is not None:
            self._use_case.start_template_edit(template_edit, quiet=quiet, on_folder=self._on_folder,
                                               on_finished=_done)
            return
        options = dict(quiet=quiet, on_folder=self._on_folder, on_finished=_done,
                       ask_source_amplitude=(self._ask_source_amplitude
                                             if ask_source_amplitude else None),
                       ask_import_template=self._ask_import_template if ask_source_amplitude else None)
        if refresh:
            self._use_case.start_refresh(refresh, **options)
        else:
            self._use_case.start_selection(list(paths), ask_for_setup=ask_for_setup,
                                           import_templates=import_templates, **options)

    @property
    def _job_id(self):
        # The use case's, not a copy: a planned run changes jobs midway, and a
        # run over before submit returns already reports None.
        return self._use_case.job_id

    # ---- job callbacks (GUI thread) -----------------------------------

    def _on_job_changed(self, job_id: int):
        """Mirrors the step the manager is on into the modal dialog."""
        if job_id != self._job_id or self._dialog is None:
            return
        record = self.job_runner.record(job_id)
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
        self._report_misfits(outcome)

    def _on_missing_checked(self, outcome):
        """The pool's Missing measurements changed: redraw the tree, say what is owed."""
        for message in outcome.log_messages:
            self.app_context.log(message)
        panel = getattr(self.explorer_panel, "pool_panel", None)
        if panel is not None:
            panel.rebuild_tree_view()

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

    def _report_misfits(self, outcome):
        if not outcome.report_misfits:
            return
        from gui.dialogs.import_template_dialog import show_misfit_report
        misfits = outcome.misfits
        templates = [self._misfit_template(misfit) for misfit in misfits]
        chosen = show_misfit_report(self.parent_widget, misfits, [bool(name) for name in templates])
        if chosen is None:
            return
        name = templates[misfits.index(chosen)]
        self.edit_import_template(name, chosen.path, misfit_paths=[
            misfit.path for misfit, template in zip(misfits, templates) if template == name])

    def _misfit_template(self, misfit) -> str:
        """The project's template a misfit can be fixed in: the first of those it names that the project holds."""
        session = self.app_context.project_session
        return next((name for name in misfit.templates if session.resolve_import_template(name) is not None), "")

    # ---- editing an Import template ------------------------------------

    def edit_project_template(self, name: str) -> None:
        """Edits the project's copy of an Import template on a sample the user picks, one of its files offered."""
        location = self.app_context.project_session.source_location
        files = sorted(run.file_path for run in self.app_context.pool.loaded_runs
                       if (entry := location.entry_for_run(run)) is not None and entry.import_template == name)
        sample, _ = QFileDialog.getOpenFileName(
            self.parent_widget, f"Sample workbook to edit '{name}' on", files[0] if files else "",
            "Table files (*.xlsx *.txt *.csv)")
        if sample:
            self.edit_import_template(name, sample)

    def edit_import_template(self, name: str, sample_path: str, misfit_paths=()) -> None:
        """
        Opens the import wizard on `sample_path` with the project's copy of the
        template `name` loaded.

        From the misfit report (`misfit_paths`, the files that did not fit it)
        the wizard ends in Overwrite or Save as new, and the files are added
        afterwards with the template it ended with. In the project it ends in
        Apply. Overwrite and Apply show the consequence summary first; Cancel
        changes nothing, confirming replaces the copy and re-reads only its
        files, and once they are read offers to save the edit into the library too.
        """
        from gui.dialogs.import_template_dialog import ask_save_to_library, confirm_template_edit
        from gui.dialogs.import_template_wizard import (
            ENDING_MISFIT, ENDING_PROJECT, SAVED_NEW, ImportTemplateWizardDialog,
        )
        template = self.app_context.project_session.resolve_import_template(name)
        if template is None:
            self.app_context.log(f"WARNING: The project holds no Import template '{name}' to edit.")
            return
        dialog = ImportTemplateWizardDialog(
            self.parent_widget, sample_path, self.job_runner, template=template,
            ending=ENDING_MISFIT if misfit_paths else ENDING_PROJECT, taken_names=tuple(self.app_context.project_session.resolve_import_templates()))
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.saved_template is None:
            return
        edited = dialog.saved_template
        add_misfits = (lambda: self.add_paths(list(misfit_paths), import_templates=(edited,))) if misfit_paths else None
        if dialog.saved_as == SAVED_NEW:
            self.app_context.log(f"POOL: Saved the Import template '{edited.name}' into your library.")
            if add_misfits is not None:
                add_misfits()
            return
        session = self.app_context.project_session
        summary = build_template_edit_summary(
            template, edited, filter_cards=session.project.filter_cards,
            filter_profiles=session.filter_profiles, open_tabs=session.current_open_tabs())
        if not confirm_template_edit(self.parent_widget, summary):
            return

        def _after_rescan() -> None:
            saved = ask_save_to_library(self.parent_widget, edited)
            if saved:
                self.app_context.log(f"POOL: {saved}")
            if add_misfits is not None:
                add_misfits()

        self._start([], template_edit=edited, then=_after_rescan)

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
        -- would otherwise leave the old one running. The existence check of
        the old pool goes too, so its answer cannot mark the new one.
        """
        self._cancel_running()
        self._missing_check.cancel()

    def _cancel_running(self):
        """
        Abandons whatever is in flight.

        The folder already being read is allowed to finish -- interrupting a
        header read mid-file buys nothing -- but its result is dropped rather
        than landing in the pool afterwards, and no further folder is started.
        """
        if self._job_id is not None:
            self.job_runner.cancel(self._job_id)
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
