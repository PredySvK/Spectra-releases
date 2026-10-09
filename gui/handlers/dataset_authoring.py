# =====================================================================
# FILE: gui/handlers/dataset_authoring.py
# =====================================================================
"""
Dataset authoring actions behind the "Generate Signal" and "Realize Test Dataset"
buttons in the Project ribbon tab.

Groups:
- Generating synthetic signals through SignalGeneratorDialog and exporting
  them asynchronously via QtJobRunner batch lane.
- Realizing predefined version-controlled test datasets (signal_library) as
  measurement .asc files plus their metadata/pairing spreadsheets on disk via
  QtJobRunner batch lane.

Both operations produce files on disk via QtJobRunner and are accessed from the
same Project tab button pair.

All internal documentation strings and variable labels are standardly written
in English.
"""

import os
from typing import Optional

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from core.jobs import JobState, job_step
from gui.dialogs.signal_generator_dialog import SignalGeneratorDialog
from gui.dialogs.signal_preview import SignalPreviewHandler
from io_modules.signal_generation import write_dataset_sheets
from io_modules.signal_generation.signal_library import (
    build_dataset,
    list_datasets,
    realize_measurement,
)
from io_modules.signal_generation.synthetic_pipeline import (
    generate_and_export_synthetic,
)

__all__ = ["DatasetAuthoringHandler", "EXPORT_SLOT_KEY", "SLOT_KEY"]

SLOT_KEY = "realize_dataset"
# One export action backs the Signal Generator export, so a single fixed key
# is enough -- a second export click before the first finished supersedes it in
# QtJobRunner, which withholds a cancelled job's on_step/on_error.
EXPORT_SLOT_KEY = "synthetic_signal_export"


class DatasetAuthoringHandler:
    """
    Handles signal generation dialog launch and test dataset realization.

    Explicit dependencies injected via constructor:
    - app_context: application settings, active directory, and logging.
    - job_manager: background worker runner.
    - parent_widget: parent QWidget for modal dialogs and file dialogs.
    - log_panel and data_pool: refresh the workspace after an export finishes.
    """

    def __init__(
        self,
        app_context,
        job_manager,
        parent_widget: Optional[QWidget] = None,
        *,
        log_panel,
        data_pool,
    ) -> None:
        self.app_context = app_context
        self.job_manager = job_manager
        self.parent_widget = parent_widget
        self.log_panel = log_panel
        self.data_pool = data_pool

    def on_export_finished(self, ok: bool, message: str, export_path: str) -> None:
        """Log an export result and route a new file through normal pool ingest."""
        self.log_panel.log_message(message)
        if ok and export_path:
            self.data_pool.add_paths([export_path])

    def export_synthetic_signal(self, params: dict, export_path: str) -> None:
        """
        Run synthetic signal generation and file export in the background batch lane.
        """
        self.app_context.log(
            f"SYSTEM: Generating synthetic signal ({len(params['channels'])} channel(s)) "
            f"in the background..."
        )
        # Batch lane: a long write the user leaves running, not something they
        # are staring at waiting for like a Compare plot refresh.
        self.job_manager.submit(
            "Synthetic signal export",
            fn=generate_and_export_synthetic,
            args=(params, export_path),
            lane="batch",
            slot_key=EXPORT_SLOT_KEY,
            on_step=self._on_export_step,
            on_error=self._on_export_error,
        )

    def _on_export_step(self, payload: dict, _step_index: int) -> None:
        message = (
            f"SUCCESS: Generated {payload['channels']}-channel ASC "
            f"({payload['samples']} samples/channel, seed={payload['seed']}) "
            f"-> {payload['path']}"
        )
        # Aliasing warnings are advisory -- the file was still written. Surface
        # them so a user who set an order above Nyquist sees why the spectrum
        # folds, instead of only finding it in the plot later.
        for warning in payload.get("nyquist_warnings", []):
            message += f"\nWARNING: {warning}"
        self.on_export_finished(True, message, payload["path"])

    def _on_export_error(self, message: str, _step_index: int) -> None:
        self.on_export_finished(False, f"CRITICAL_GENERATION_FAULT: {message}", "")

    @property
    def _active_directory(self) -> str:
        return getattr(self.app_context, "active_directory", None) or ""

    def generate_signal(self) -> None:
        """
        Open the Signal Generator dialog, collect parameters, prompt for save
        location, and hand generation + export to QtJobRunner batch lane so the UI
        never freezes during large signal synthesis.
        """
        settings = getattr(self.app_context, "settings", None)
        dialog = SignalGeneratorDialog(self.parent_widget, settings=settings)
        # Held on the dialog on purpose: PySide6 does NOT keep a receiver alive
        # through signal.connect(self.method), so an unreferenced handler is
        # garbage-collected the moment this function returns -- taking its live
        # preview QTimer with it, which is why the preview plots stayed blank.
        dialog._preview_handler = SignalPreviewHandler(
            dialog,
            self.job_manager,
        )

        try:
            if not dialog.exec():
                return
            params = dialog.get_generation_parameters()
        finally:
            # The dialog is parented to the main window, so nothing else would ever
            # destroy it -- and each one takes its handler and live-preview QTimer
            # down with it for the rest of the session. Read everything first, then let it go.
            # shutdown() before deleteLater(): cancels the preview job slot so an
            # in-flight worker cannot draw into the freed plot widgets (audit 02, S11/11.1).
            dialog._preview_handler.shutdown()
            dialog.deleteLater()

        file_path, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
            "Save Synthetic NVH Signal (Siemens Format)",
            self._active_directory,
            "Siemens ASCII Files (*.asc)",
        )

        if not file_path:
            return

        # Array generation and np.savetxt run on a background worker via
        # QtJobRunner batch lane so the UI never freezes during large synthesis.
        self.export_synthetic_signal(params, file_path)

    def realize_dataset(self) -> None:
        """
        Prompt for dataset key and target directory, then submit batch job to
        QtJobRunner to synthesize and write every measurement file, then
        metadata.xlsx (and channel_pairing.xlsx where the dataset has pairs).
        """
        keys = list_datasets()
        if not keys:
            return

        if len(keys) == 1:
            key = keys[0]
        else:
            key, ok = QInputDialog.getItem(
                self.parent_widget,
                "Realize Test Dataset",
                "Dataset:",
                keys,
                0,
                False,
            )
            if not ok or not key:
                return

        spec = build_dataset(key)
        count = len(spec.measurements)

        out_root = QFileDialog.getExistingDirectory(
            self.parent_widget,
            f"Choose output folder for {key} ({count} measurements)",
            self._active_directory,
        )
        if not out_root:
            return

        confirm = QMessageBox.question(
            self.parent_widget,
            "Realize Test Dataset",
            f"Write {count} measurement file(s) of '{key}' and its metadata "
            f"spreadsheet under:\n{out_root}\n\n"
            "Existing files with the same names are overwritten.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        app_context = self.app_context
        # Collected across steps so one summary line reports all aliasing warnings
        # rather than one log line per file.
        state = {"written": 0, "warnings": []}

        def on_step(payload, index):
            if index == count:  # the spreadsheets step after the measurements
                state["sheets"] = payload
                return
            state["written"] += 1
            for warning in payload.get("nyquist_warnings", []):
                state["warnings"].append(f"{os.path.basename(payload['path'])}: {warning}")

        def on_error(message, index):
            app_context.log(f"ERROR: Realize '{key}' -- {message}")

        def on_done(record):
            # "Realized 12/25" without reading record.state reads as a progress
            # counter, not an aborted run -- the caller sees a full dataset and the
            # missing files surface months later (audit 02, S11/11.4; the sibling
            # paths workflow_run_bridge / data_pool already branch here).
            if record.state is JobState.SUPERSEDED:
                app_context.log(
                    f"SYSTEM: Realize '{key}' superseded by a newer run -- "
                    f"{state['written']}/{count} file(s) written before it stopped"
                )
                return
            if record.state is not JobState.DONE:
                app_context.log(
                    f"WARNING: Realize '{key}' {record.state.value} after "
                    f"{state['written']}/{count} file(s) -- '{out_root}' is incomplete"
                )
                return
            app_context.log(
                f"SYSTEM: Realized {state['written']}/{count} measurement(s) of "
                f"'{key}' -> {out_root}"
            )
            for path in state.get("sheets", []):
                app_context.log(f"SYSTEM: Wrote {os.path.basename(path)}")
            for warning in state["warnings"]:
                app_context.log(f"WARNING: {warning}")

        steps = [
            job_step(measurement.rel_path, realize_measurement, measurement, out_root)
            for measurement in spec.measurements
        ] + [job_step("metadata.xlsx", write_dataset_sheets, spec, out_root)]
        self.job_manager.submit(
            f"Realize dataset '{key}' - {count} file(s)",
            steps,
            lane="batch",
            slot_key=SLOT_KEY,
            on_step=on_step,
            on_error=on_error,
            on_done=on_done,
        )
