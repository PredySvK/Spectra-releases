# =====================================================================
# FILE: gui/handlers/batch_run.py
# =====================================================================
"""
Every way a batch run gets started from the window (ARCHITECTURE_DECISIONS
§1.6, §1.21, §1.77).

`BatchRunHandler` owns two entry points that were two modules until #235:

  * the "Compute Result Set..." button each of the four analysis ribbon tabs
    ends with -- a dialog for the input and an optional name, then the fast
    path: one block, one save, over the Data Pool (a MODE_EXPLICIT
    MeasurementSelection built from `app_context.pool.loaded_runs`, "these
    files, right now") or once per checked saved Selection, the result sets
    run one after another;
  * the Workflow tab's Run button -- a hand-authored graph, run over the
    selection its input node names.

Both only gather their input and then go through one sequence:
coarse refusal with no disk -> save the project -> register folders off-thread
-> the complete plan of every run of the series -> one Overwrite question ->
the Wait / Interrupt / Cancel question, only while a Batch run computes or
waits (§1.266) -> submit or wait. Nothing before that stops a running Batch
run: a refused run and Cancel on any of the questions all leave it be.

One action core for all four tabs. Planning (validation, channel scope,
SaveSpec, selection build, label derivation) is done as pure data via
`plan_calculate_and_save` in `orchestration/batch`; what differs is passed in,
not branched on:

    block_type     "order_tracking" / "spectrum" / "spectrogram" / "overall_level"
    config         that tab's dsp_configs dataclass, straight from its ribbon
                   (Order Tracking with the request's orders swapped in)
    request        the dialog's answer, CalculateAndSaveRequest
    start          which controller runs it

All tabs go through WorkflowRunBridge. The pre-Epic-P
OrderBatchSaveController is gone -- order tracking was the last path still on
it, and the parity it had to keep is pinned by
tests/test_order_tracking_runner_parity.py.

`ask_overwrite_or_save_new` stays a plain function rather than a method,
because it takes one or two things and never the frame (spec #148). A run
without a window goes through `orchestration/batch` directly.

Lives in gui/: it drives Qt dialogs and ProjectSession, so it cannot sit any
lower. Built once by the composition root (`gui/main_window.py`) with its
`app_context`, `ribbon`, `workflow_run_bridge`, `workflow_view`,
Qt `parent_widget` and the shared job runner.

All internal documentation strings and variable labels are standardly written
in English.
"""
from dataclasses import replace
from typing import Callable, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from orchestration.batch import (
    CALCULATE_AND_SAVE_WHAT,
    CalculateAndSaveRequest,
    DataPoolInput,
    WorkflowChainBatch,
    apply_overwrites,
    resolve_overwrite_candidates,
    plan_calculate_and_save,
    plan_workflow_chains,
    resolve_calculate_and_save_refusal,
    resolve_data_pool_scope,
    resolve_selection_scope,
)
from orchestration.data_pool import REGISTRATION_SLOT_KEY, run_pool_registration
from view_models.batch import DATA_POOL_TYPE_OPTIONS

WHAT = CALCULATE_AND_SAVE_WHAT


# ---- the duplicate prompt, shared by both entry points ----------------

def ask_overwrite_or_save_new(parent, existing_labels) -> QMessageBox.StandardButton:
    """
    Warns that result set(s) with these exact settings already exist, and lets
    the user choose what to do instead of silently piling up near-duplicate
    folders.

    One label -> the wording the ribbon fast path has always shown (a test pins
    it). Several -> a bulleted list, for a graph with more than one save node
    or a series of runs.

    Yes = overwrite the existing set(s) in place. No = save as new,
    separately-labelled set(s). Cancel = do nothing.
    """
    labels = list(existing_labels)
    if len(labels) == 1:
        text = (
            f"A result set with these exact settings already exists: '{labels[0]}'.\n\n"
            f"Overwrite it, or save this as a new result set?"
        )
    else:
        listing = "\n".join(f"  • {label}" for label in labels)
        text = (
            f"{len(labels)} result sets with these exact settings already exist:\n\n"
            f"{listing}\n\n"
            f"Overwrite them, or save these as new result sets?"
        )

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Result set already exists")
    box.setText(text)
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
    )
    box.button(QMessageBox.StandardButton.Yes).setText("Overwrite")
    box.button(QMessageBox.StandardButton.No).setText("Save as New")
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    return box.exec()


def ask_wait_or_interrupt(parent) -> QMessageBox.StandardButton:
    """
    Asks what a new Batch run does about the ones computing or waiting (ADR
    §1.266). Yes = Wait: start after all of them. No = Interrupt: stop the
    running one, drop the waiting ones and start this one. Cancel = do nothing.
    """
    return _ask_wait(
        parent,
        "Wait: start this one after everything that runs or waits.\n"
        "Interrupt: stop the running one, drop the waiting ones and start only this one.",
        "Interrupt and Start New",
    )


def ask_wait_or_interrupt_before(parent, action_label: str) -> QMessageBox.StandardButton:
    """
    Asks what New, Open, Save As or closing the window does about the Batch
    runs computing or waiting (#968). Yes = Wait: do it once they have all
    finished. No = Interrupt: stop them and do it now. Cancel = do nothing,
    they go on. `action_label` is what waits, as an imperative ("close Spectra").
    """
    return _ask_wait(
        parent,
        f"Wait: {action_label} once everything that runs or waits has finished.\n"
        f"Interrupt: stop the running one (what it computes is not saved), drop the "
        f"waiting ones and {action_label} now.",
        "Interrupt",
    )


def _ask_wait(parent, choices: str, interrupt_text: str) -> QMessageBox.StandardButton:
    """The one Wait / Interrupt / Cancel box; Wait is the default."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("A computation is running")
    box.setText(f"A computation is running or waiting.\n\n{choices}")
    box.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
    )
    box.button(QMessageBox.StandardButton.Yes).setText("Wait")
    box.button(QMessageBox.StandardButton.No).setText(interrupt_text)
    box.setDefaultButton(QMessageBox.StandardButton.Yes)
    return box.exec()


def confirm_leaving_batch_runs(batch_runs, parent, action_label: str, retry: Callable[[], None]) -> bool:
    """
    The Wait / Interrupt / Cancel question New, Open, Save As and closing the
    window ask before their own questions, only while a Batch run computes or
    waits (#968). Work the user did not start (scans, caches, quiet jobs) is
    never asked about.

    True: go on now (nothing computes, or Interrupt stopped it all). False:
    stop here -- Cancel, or Wait, which calls `retry` once the line has
    finished. `retry` runs from a fresh event-loop turn, not from inside the
    last run's finish.
    """
    if batch_runs is None or not batch_runs.busy:
        return True
    answer = ask_wait_or_interrupt_before(parent, action_label)
    if answer == QMessageBox.StandardButton.Yes:
        batch_runs.run_when_idle(action_label, lambda: QTimer.singleShot(0, retry))
        return False
    if answer == QMessageBox.StandardButton.No:
        batch_runs.interrupt()
        return True
    return False


class BatchRunHandler:
    """
    The ribbon's four "Compute Result Set..." buttons and the Workflow tab's
    Run button, with the pool catch-up and duplicate prompt they share.
    """

    def __init__(self, app_context, ribbon, workflow_run_bridge, workflow_view,
                 parent_widget, *, job_runner):
        self.app_context = app_context
        self.ribbon = ribbon
        self.workflow_run_bridge = workflow_run_bridge
        self.workflow_view = workflow_view
        self.parent_widget = parent_widget
        self.job_runner = job_runner

    # ---- the four ribbon entry points ---------------------------------

    def calculate_and_save_order_results(self, request: CalculateAndSaveRequest) -> None:
        tab = self.ribbon.tab_acc_order_tracking

        # The tab's FFT/tracking settings, with the orders the dialog asked for
        # in place of the ones the live plot shows.
        if not request.orders:
            self.app_context.log(f"ERROR: {WHAT} skipped -- no orders specified.")
            return
        config = replace(tab.get_dsp_config(), orders_to_extract=list(request.orders))

        self.calculate_and_save(
            save_section=tab.save_section,
            block_type="order_tracking", config=config, request=request,
        )

    def calculate_and_save_spectrum_results(self, request: CalculateAndSaveRequest) -> None:
        tab = self.ribbon.tab_acc_spectrum
        self.calculate_and_save(
            save_section=tab.save_section,
            block_type="spectrum", config=tab.get_dsp_config(), request=request,
        )

    def calculate_and_save_spectrogram_results(self, request: CalculateAndSaveRequest) -> None:
        tab = self.ribbon.tab_acc_spectrogram
        self.calculate_and_save(
            save_section=tab.save_section,
            block_type="spectrogram", config=tab.get_dsp_config(), request=request,
        )

    def calculate_and_save_overall_level_results(self, request: CalculateAndSaveRequest) -> None:
        tab = self.ribbon.tab_acc_overall_level
        self.calculate_and_save(
            save_section=tab.save_section,
            block_type="overall_level", config=tab.get_dsp_config(), request=request,
        )

    def _track_status(self, section, labels: tuple[str, ...], *,
                      waiting: bool = False) -> tuple[Callable[[], None], Callable[[str, bool], None]]:
        """
        Drive one ribbon button's status line for a Batch run about to be
        submitted or put to wait: "Waiting: '<label>'..." while it waits,
        "Computing '<label>'..." from `started` on, and the end once `finished`
        has heard every run. Returns `(started, finished)` for the bridge.

        `finished` hears only this series' own runs: the runs
        ahead of a waiting one, or an interrupted one ending late, may carry
        the same label, and must not end this line. A dropped waiting series
        is heard too, so its line does not stay on "Waiting". With several
        result sets the line names the next one still computing and clears
        once the last has finished.
        """
        pending = list(labels)
        failed = []
        if waiting:
            section.set_status(f"Waiting: '{pending[0]}'...")

        def started() -> None:
            section.set_status(f"Computing '{pending[0]}'...")

        def finished(done_label: str, ok: bool) -> None:
            if done_label not in pending:
                return
            pending.remove(done_label)
            if not ok:
                failed.append(done_label)
            if pending:
                section.set_status(f"Computing '{pending[0]}'...")
            elif not failed:
                section.set_status("")
            elif len(failed) == 1:
                section.set_status(f"'{failed[0]}': nothing saved -- see System Log.")
            else:
                section.set_status(f"{len(failed)} result sets: nothing saved -- see System Log.")

        return started, finished

    def _start_planned(self, chains: tuple[WorkflowChainBatch, ...], *, cancelled: str,
                       section=None) -> None:
        """
        The common end of both entry points, once every run of the series has
        its complete plan: one Overwrite question over all the runs' duplicates
        (none for a refused run) -- saved ones, and ones a running or waiting
        Batch run will write, marked "(computing)" / "(waiting)" (#967) --
        then, only while a Batch run computes or waits and this one has
        something to run, Wait / Interrupt / Cancel, then the submit or the wait. Cancel logs `cancelled` (or that the
        running ones were left alone) and changes nothing (§1.264, §1.266).
        """
        context = self.app_context
        bridge = self.workflow_run_bridge
        candidates = resolve_overwrite_candidates(context.project_session, chains,
                                                  upcoming=bridge.upcoming_result_sets)
        labels = [candidate.prompt_label for found in candidates for candidate in found.values()]
        if labels:
            choice = ask_overwrite_or_save_new(self.parent_widget, labels)
            if choice == QMessageBox.StandardButton.Cancel:
                context.log(cancelled)
                return
            if choice == QMessageBox.StandardButton.Yes:
                chains = apply_overwrites(chains, candidates)

        wait = False
        if bridge.busy and any(chain.batch.runnable for chain in chains):
            choice = ask_wait_or_interrupt(self.parent_widget)
            if choice == QMessageBox.StandardButton.Cancel:
                context.log("SYSTEM: New Batch run cancelled -- the running one goes on.")
                return
            wait = choice == QMessageBox.StandardButton.Yes

        started = finished = None
        if section is not None and hasattr(section, "set_status"):
            started, finished = self._track_status(
                section, tuple(chain.batch.label for chain in chains), waiting=wait)
        bridge.start_chains(chains, wait=wait, on_started=started, on_finished=finished)

    # ---- what all four "Calculate & Save Data" tabs do -----------------

    def calculate_and_save(self, *, save_section, block_type, config,
                           request: CalculateAndSaveRequest) -> None:
        context = self.app_context
        session = context.project_session

        loaded_runs = list(context.pool.loaded_runs)

        def log_lines(messages):
            for message in messages:
                context.log(message)

        # Refuse what needs no source lookup before asking to save the project.
        refusal = resolve_calculate_and_save_refusal(loaded_runs)
        if refusal:
            log_lines(refusal)
            return

        def registered(sources_by_path):
            # Plan against the stored channel types after folder registration.
            plans = plan_calculate_and_save(
                block_type,
                config,
                request,
                tacho_cleaning=context.tacho_cleaning,
                loaded_runs=loaded_runs,
                sources_by_path=sources_by_path,
                find_selection=session.find_selection,
                schema=context.pool.schema().master,
            )

            for plan in plans:
                if not plan.runnable:
                    log_lines(plan.messages)
            chains = self.workflow_run_bridge.build_result_set_batches(plans)
            if not chains:
                return
            for chain in chains:
                log_lines(chain.batch.messages)

            self._start_planned(
                chains, section=save_section,
                cancelled=f"SYSTEM: {WHAT} cancelled -- a result set with these settings already exists.")

        self.ensure_pool_registered(WHAT, registered)

    # ---- "Compute Result Set" dialog: one ribbon entry point per tab ----

    def _open_compute_dialog(self, *, section, folder_action: Callable,
                             extra_orders: bool = False) -> None:
        """
        Opens the dialog to gather the input (Data Pool or saved Selections),
        the orders and an optional result-set name, then hands its answer -- a
        CalculateAndSaveRequest -- straight to the calculate_and_save_* action.
        The dialog is handed the counts it shows rather than reaching into
        `app_context` for them.
        """
        from gui.dialogs.compute_result_set_dialog import ComputeResultSetDialog

        context = self.app_context
        session = context.project_session
        loaded_runs = list(context.pool.loaded_runs)
        # In-memory counts over the pool index, no file read: synchronous on
        # purpose (§1.218, §1.219).
        entries = session.source_location.entries_by_path
        schema = context.pool.schema().master
        data_pool_scopes = {
            label: resolve_data_pool_scope(DataPoolInput(types), loaded_runs, entries)
            for label, types in DATA_POOL_TYPE_OPTIONS.items()
        }
        selection_scopes = tuple(
            resolve_selection_scope(selection, loaded_runs, entries, schema)
            for selection in session.selections()
        )

        dialog = ComputeResultSetDialog(
            settings_prefix=section._settings_prefix, settings=getattr(context, "settings", None),
            data_pool_scopes=data_pool_scopes, selection_scopes=selection_scopes,
            extra_orders=extra_orders, folder_count=len(loaded_runs),
            parent=self.parent_widget,
        )
        if not dialog.exec():
            return

        folder_action(dialog.request)

    # `open_*` rather than the button's own word: opening the dialog is what
    # these four do, and `compute_*` names DSP number-crunching, which lives on
    # another floor (architecture.md > Pravidlá mien).
    def open_compute_result_set_spectrum(self) -> None:
        tab = self.ribbon.tab_acc_spectrum
        self._open_compute_dialog(
            section=tab.save_section,
            folder_action=self.calculate_and_save_spectrum_results,
        )

    def open_compute_result_set_spectrogram(self) -> None:
        tab = self.ribbon.tab_acc_spectrogram
        self._open_compute_dialog(
            section=tab.save_section,
            folder_action=self.calculate_and_save_spectrogram_results,
        )

    def open_compute_result_set_order_tracking(self) -> None:
        tab = self.ribbon.tab_acc_order_tracking
        self._open_compute_dialog(
            section=tab.save_section,
            folder_action=self.calculate_and_save_order_results, extra_orders=True,
        )

    def open_compute_result_set_overall_level(self) -> None:
        tab = self.ribbon.tab_acc_overall_level
        self._open_compute_dialog(
            section=tab.save_section,
            folder_action=self.calculate_and_save_overall_level_results,
        )

    # ---- the pool catch-up both entry points run first -----------------

    def ensure_pool_registered(self, what: str, on_ready: Callable) -> None:
        """Save the project, register missing folders off-thread, then continue."""
        context = self.app_context
        session = context.project_session
        from gui.handlers.project_document import ensure_project_saved

        self.job_runner.cancel_slot(REGISTRATION_SLOT_KEY)
        if not ensure_project_saved(context, self.parent_widget):
            context.log(f"SYSTEM: {what} cancelled -- a result set needs a saved project to live in.")
            return

        run_pool_registration(
            session, self.job_runner, tuple(context.pool.pool_directories),
            on_ready=on_ready, log=context.log)

    # ---- the Workflow tab's Run button ---------------------------------

    def run_selected_workflow(self) -> None:
        """Run every chain of the active workflow."""
        self._run_workflow_scope()

    def run_selected_chain(self) -> None:
        """Run the chain containing the active block."""
        block_id = self.workflow_view.current_block_id() if self.workflow_view is not None else None
        if block_id is None:
            QMessageBox.information(self.parent_widget, "Run Chain", "Select a block to run its chain.")
            return
        self._run_workflow_scope(block_id=block_id)

    def run_chain(self, block_id: str) -> None:
        """Context-menu entry point for a specific block's chain."""
        self._run_workflow_scope(block_id=block_id)

    def _run_workflow_scope(self, *, block_id: Optional[str] = None) -> None:
        """
        Run the workflow currently shown in the Workflow panel. Every way it cannot
        run yet gets its own message box -- a user who just pressed Run is owed a
        modal, not a line in the log.
        """
        context = self.app_context
        session = context.project_session
        parent = self.parent_widget
        view = self.workflow_view

        name = view.current_workflow_name() if view is not None else None
        workflow = session.find_workflow(name) if name else None
        if workflow is None:
            QMessageBox.information(parent, "Run Workflow", "Select a workflow to run.")
            return

        chains = plan_workflow_chains(workflow, session.find_selection, block_id=block_id,
                                      tacho_cleaning=context.tacho_cleaning)
        if not any(chain.run.runnable for chain in chains):
            messages = [message for chain in chains for message in chain.run.messages]
            for message in messages:
                context.log(message)
            QMessageBox.warning(parent, "Run Workflow", "\n\n".join(messages) or "No chains to run.")
            return

        def registered(_sources_by_path):
            batches = self.workflow_run_bridge.build_chain_batches(chains)
            for chain in batches:
                for message in chain.batch.messages:
                    context.log(message)
            refused = [chain for chain in batches if not chain.batch.runnable]
            if refused:
                QMessageBox.warning(parent, "Skipped chains", "\n\n".join(
                    "\n".join(chain.batch.messages) for chain in refused))
            self._start_planned(
                batches, cancelled="SYSTEM: Run Workflow cancelled -- a matching result set already exists.")

        self.ensure_pool_registered("Run Workflow", registered)
