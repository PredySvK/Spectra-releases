# =====================================================================
# FILE: gui/handlers/batch_run.py
# =====================================================================
"""
Every way a batch run gets started from the window (ARCHITECTURE_DECISIONS
§1.6, §1.21, §1.77).

`BatchRunHandler` owns two entry points that were two modules until #235:

  * the "Compute Result Set..." button each of the four analysis ribbon tabs
    ends with -- a dialog for the channel scope and an optional name, then the
    fast path: one block, one save, over a MODE_EXPLICIT MeasurementSelection
    built from `app_context.pool.loaded_runs` ("these files, right now");
  * the Workflow tab's Run button -- a hand-authored graph, run over the
    selection its input node names.

They are one handler because they end in the same runner and share the same
two preliminaries -- `ensure_pool_registered` and `resolve_overwrites`. While
they were two modules the shared half lived in the workflow one and the batch
one reached back into it, which is the lazy import `run_batch_workflow` needed
to dodge the cycle; joined up, there is nothing left to dodge.

One action core for all four tabs. Planning (validation, channel scope,
SaveSpec, selection build, label derivation) is done as pure data via
`plan_calculate_and_save` in `orchestration/batch`; what differs is passed in,
not branched on:

    block_type     "order_tracking" / "spectrum" / "spectrogram" / "overall_level"
    config         that tab's dsp_configs dataclass, straight from its ribbon
    start          which controller runs it

All tabs go through WorkflowRunBridge. The pre-Epic-P
OrderBatchSaveController is gone -- order tracking was the last path still on
it, and the parity it had to keep is pinned by
tests/test_order_tracking_runner_parity.py.

Three things stay plain functions rather than methods, because they take one
or two things and never the frame (spec #148): `ask_overwrite_or_save_new`,
`resolve_overwrites` and `run_workflow`, the headless / test entry point.

Lives in gui/: it drives Qt dialogs and ProjectSession, so it cannot sit any
lower. Built once by the composition root (`gui/main_window.py`) with its
`app_context`, `ribbon`, `workflow_run_bridge`, `workflow_view`,
Qt `parent_widget` and the shared job runner.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Callable, Optional

from PySide6.QtWidgets import QMessageBox

from core.measurement_selection import MeasurementSelection
from core.workflow_graph import Workflow
from orchestration.batch import (
    REFUSAL_INVALID_GRAPH,
    REFUSAL_NO_CHANNELS_CHOSEN,
    REFUSAL_NO_LOADED_FOLDER,
    REFUSAL_NO_MATCHING_CHANNELS,
    default_result_set_label,
    find_overwrite_candidates,
    plan_calculate_and_save,
    plan_workflow_run,
    resolve_calculate_and_save_refusal,
)
from orchestration.data_pool import REGISTRATION_SLOT_KEY, run_pool_registration
from signal_processing.workflow import sole_terminal_node

WHAT = "Calculate & Save Data"

_CALCULATE_AND_SAVE_REFUSALS = {
    REFUSAL_NO_LOADED_FOLDER: "no folder is loaded.",
    REFUSAL_NO_CHANNELS_CHOSEN: "no channels chosen. Use 'Choose…' first.",
    REFUSAL_NO_MATCHING_CHANNELS: "no matching channels in the loaded folder.",
}


# ---- the per-node duplicate prompt, shared by both entry points -------

def ask_overwrite_or_save_new(parent, existing_labels) -> QMessageBox.StandardButton:
    """
    Warns that result set(s) with these exact settings already exist, and lets
    the user choose what to do instead of silently piling up near-duplicate
    folders.

    One label -> the wording the ribbon fast path has always shown (a test pins
    it, because that path still runs through here). Several -> a bulleted list,
    for a hand-authored graph with more than one save node.

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


def resolve_overwrites(parent, session, workflow: Workflow) -> Optional[dict]:
    """
    For every node marked to save, decide whether it replaces an existing result
    set in place. Returns `{node_id: existing result set id}` for the nodes to
    overwrite (an empty dict when nothing matches, or the user chose to save new
    copies), or None when the user cancelled.

    One prompt covers all the matches -- a five-save graph should not spawn five
    dialogs in a row.
    """
    duplicates = find_overwrite_candidates(session, workflow)
    if not duplicates:
        return {}

    choice = ask_overwrite_or_save_new(parent, [ref.label for ref in duplicates.values()])
    if choice == QMessageBox.StandardButton.Cancel:
        return None
    if choice == QMessageBox.StandardButton.Yes:
        return {node_id: ref.id for node_id, ref in duplicates.items()}
    return {}


# ---- the headless / test entry point ----------------------------------

def run_workflow(workflow_runner, workflow: Workflow, selection: MeasurementSelection,
                 label: str = None) -> None:
    """
    Run a graph over a selection with no window involved -- it takes the runner
    itself, not a frame that happens to hold one.
    """
    if not label and workflow.nodes:
        try:
            label = default_result_set_label(workflow, selection)
        except ValueError:
            # A branching / multi-terminal graph has no single terminal to name
            # the run after -- the per-node sinks (7B) derive their own labels.
            label = None
    label = label or workflow.name or selection.name or "workflow"
    workflow_runner.start(workflow, selection, label)


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

    def calculate_and_save_order_results(self, custom_label: str = "") -> None:
        tab = self.ribbon.tab_acc_order_tracking

        config = tab.get_save_dsp_config()
        if not config.orders_to_extract:
            self.app_context.log(f"ERROR: {WHAT} skipped -- no orders specified.")
            return

        self.calculate_and_save(
            save_section=tab.save_section,
            block_type="order_tracking", config=config,
            start=self._runner_start(section=tab.save_section),
            custom_label=custom_label,
        )

    def calculate_and_save_spectrum_results(self, custom_label: str = "") -> None:
        tab = self.ribbon.tab_acc_spectrum
        self.calculate_and_save(
            save_section=tab.save_section,
            block_type="spectrum", config=tab.get_dsp_config(),
            start=self._runner_start(section=tab.save_section),
            custom_label=custom_label,
        )

    def calculate_and_save_spectrogram_results(self, custom_label: str = "") -> None:
        tab = self.ribbon.tab_acc_spectrogram
        self.calculate_and_save(
            save_section=tab.save_section,
            block_type="spectrogram", config=tab.get_dsp_config(),
            start=self._runner_start(section=tab.save_section),
            custom_label=custom_label,
        )

    def calculate_and_save_overall_level_results(self, custom_label: str = "") -> None:
        tab = self.ribbon.tab_acc_overall_level
        self.calculate_and_save(
            save_section=tab.save_section,
            block_type="overall_level", config=tab.get_dsp_config(),
            start=self._runner_start(section=tab.save_section),
            custom_label=custom_label,
        )

    def _track_status(self, section, label: str) -> None:
        """
        Drive one ribbon button's status line for the run about to be submitted.

        A one-shot connection: `run_finished` is a single shared callback list
        on the one bridge, so without disconnecting, a run started from
        another tab would later overwrite this tab's line. Armed before
        `bridge.start()` because an early refusal (bad graph, nothing
        resolved) emits `run_finished` synchronously from inside it.
        """
        bridge = self.workflow_run_bridge
        section.set_status(f"Computing '{label}'...")

        def _finished(done_label: str, ok: bool) -> None:
            if done_label != label:
                return
            bridge.run_finished.disconnect(_finished)
            section.set_status(
                f"Saved '{done_label}'." if ok
                else f"'{done_label}': nothing saved -- see System Log."
            )

        bridge.run_finished.connect(_finished)

    def _runner_start(self, what: str = WHAT, section=None) -> Callable:
        bridge = self.workflow_run_bridge

        def start(workflow, selection, label, overwrite_result_set_id):
            # The fast path builds a single-save two-node graph, so its one
            # terminal is the one save node the duplicate dialog could have
            # matched.
            overwrite_by_node = (
                {sole_terminal_node(workflow).node_id: overwrite_result_set_id}
                if overwrite_result_set_id else None
            )
            if section is not None and hasattr(section, "set_status"):
                self._track_status(section, label)
            bridge.start(
                workflow, selection, label, overwrite_by_node=overwrite_by_node, what=what,
            )
        return start

    # ---- what all four "Calculate & Save Data" tabs do -----------------

    def calculate_and_save(self, *, save_section, block_type, config,
                           start: Callable, custom_label: str = "") -> None:
        context = self.app_context
        session = context.project_session

        loaded_runs = list(getattr(context.pool, "loaded_runs", []))
        channel_types = save_section.get_save_channel_types()
        all_channels_mode = save_section.is_save_mode_all_channels()
        picked_identities = save_section.selected_channel_identities()

        def refuse(reason):
            context.log(f"WARNING: {WHAT} skipped -- {_CALCULATE_AND_SAVE_REFUSALS[reason]}")

        # Refuse what needs no source lookup before asking to save the project.
        refusal = resolve_calculate_and_save_refusal(
            loaded_runs, all_channels_mode, picked_identities)
        if refusal is not None:
            refuse(refusal)
            return

        def registered(sources_by_path):
            # Plan against the stored channel types after folder registration.
            plan = plan_calculate_and_save(
                block_type,
                config,
                loaded_runs=loaded_runs,
                channel_types=channel_types,
                all_channels=all_channels_mode,
                picked_identities=picked_identities,
                sources_by_path=sources_by_path,
                custom_label=custom_label,
            )

            if not plan.runnable:
                refuse(plan.refusal_reason)
                return

            workflow = plan.workflow
            selection = plan.selection
            label = plan.label
            terminal = sole_terminal_node(workflow)

            overwrites = resolve_overwrites(self.parent_widget, session, workflow)
            if overwrites is None:
                context.log(
                    f"SYSTEM: {WHAT} cancelled -- a result set with these settings already exists."
                )
                return
            overwrite_result_set_id = overwrites.get(terminal.node_id)

            start(workflow, selection, label, overwrite_result_set_id)

        self.ensure_pool_registered(WHAT, registered)

    # ---- "Compute Result Set" dialog: one ribbon entry point per tab ----

    def _open_compute_dialog(self, *, section, folder_action: Callable,
                             extra_orders: bool = False) -> None:
        """
        Opens the dialog to gather the channel scope and an optional result-set
        name, then runs the unchanged calculate_and_save_* action (it re-reads
        `section`, which the dialog has just updated in QSettings).
        """
        from gui.dialogs.compute_result_set_dialog import ComputeResultSetDialog

        context = self.app_context
        loaded_runs = list(getattr(context.pool, "loaded_runs", []))

        dialog = ComputeResultSetDialog(
            settings_prefix=section._settings_prefix, app_context=context,
            extra_orders=extra_orders, folder_count=len(loaded_runs),
            parent=self.parent_widget,
        )
        if not dialog.exec():
            return

        folder_action(custom_label=dialog.custom_label)

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

        plan = plan_workflow_run(workflow, session.find_selection)
        if not plan.runnable:
            if plan.refusal_reason == REFUSAL_INVALID_GRAPH:
                QMessageBox.warning(
                    parent, "Run Workflow", f"This workflow cannot run yet:\n\n{plan.message}"
                )
            else:
                QMessageBox.warning(parent, "Run Workflow", plan.message)
            return

        selection = plan.selection

        def registered(_sources_by_path):
            overwrites = resolve_overwrites(parent, session, workflow)
            if overwrites is None:
                context.log(
                    "SYSTEM: Run Workflow cancelled -- a matching result set already exists."
                )
                return

            self.workflow_run_bridge.start(
                workflow, selection, workflow.name, overwrite_by_node=overwrites or None,
            )

        self.ensure_pool_registered("Run Workflow", registered)
