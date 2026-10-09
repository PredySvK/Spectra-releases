"""The Run Benchmark dialog behind the Settings tab button (ADR §1.132, #485)."""

import dataclasses
import os
import re
import sys
import tempfile
from typing import List, Optional

from PySide6.QtCore import QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from core.asset_paths import perf_report_dir
from io_modules.benchmark import DEFAULT_PLAN_PATH, read_benchmark_plan, write_benchmark_plan
from orchestration.benchmark import build_benchmark_command

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_POLL_MS = 300  # how often the running Benchmark's log file is read


class BenchmarkDialog(QDialog):
    def __init__(self, *, app_context, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Run Benchmark")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint)
        self._app_context = app_context
        self._process: Optional[QProcess] = None
        self._output = ""
        self._report_dir = ""
        self._plan_path = ""  # the temp plan of the running Benchmark
        self._log_path = ""  # its temp log: a frozen build has no console to print to
        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._read_output)

        self.edit_plan = QLineEdit(DEFAULT_PLAN_PATH)
        self.edit_plan.editingFinished.connect(self.load_plan)
        self.list_files = QListWidget()
        self.list_files.setMaximumHeight(90)
        self.cb_generated = QCheckBox("Generated reference signal")
        self.edit_out = QLineEdit(perf_report_dir())
        self.combo_variant = QComboBox()
        self.combo_variant.addItems(["Headless", "Full"])
        self.combo_variant.setCurrentText("Full")
        self.cb_quick = QCheckBox("Quick")
        self.cb_quick.setChecked(True)
        self.edit_baseline = QLineEdit()
        self.edit_baseline.setPlaceholderText("Optional -- Benchmark report (JSON) to compare with")
        self.btn_pool = QPushButton("Add from Data Pool")
        self.btn_pool.clicked.connect(self.add_from_data_pool)
        self.btn_file = QPushButton("Add file…")
        self.btn_file.clicked.connect(self._add_file)
        self.btn_run = QPushButton("Run")
        self.btn_run.clicked.connect(self.run)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # busy until the first case is done
        self.progress.setFormat("%v/%m (%p%)")
        self.progress.hide()
        self._stopped = False
        self.btn_open = QPushButton("Open folder")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self._report_dir)))
        self.report_view = QTextBrowser()
        self.report_view.setPlaceholderText("The Benchmark report shows here when the run ends.")
        self.lbl_status = QLabel("")

        grid = QGridLayout()
        for row, (label, edit, browse) in enumerate([
            ("Plan", self.edit_plan, self._browse_plan),
            ("Output folder", self.edit_out, lambda: self._browse_dir(self.edit_out)),
            ("Compare with…", self.edit_baseline, lambda: self._browse(self.edit_baseline, "Report (*.json)")),
        ]):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(edit, row, 1)
            button = QPushButton("…")
            button.clicked.connect(browse)
            grid.addWidget(button, row, 2)
        files_row = QHBoxLayout()
        files_row.addWidget(self.btn_pool)
        files_row.addWidget(self.btn_file)
        files_row.addWidget(self.cb_generated)
        files_row.addStretch()
        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("Variant"))
        options_row.addWidget(self.combo_variant)
        options_row.addWidget(self.cb_quick)
        options_row.addStretch()
        options_row.addWidget(self.btn_open)
        options_row.addWidget(self.btn_stop)
        options_row.addWidget(self.btn_run)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(QLabel("Files"))
        layout.addWidget(self.list_files)
        layout.addLayout(files_row)
        layout.addLayout(options_row)
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.progress)
        layout.addWidget(self.report_view, 1)
        self.resize(760, 900)
        self.load_plan()

    # ---- inputs --------------------------------------------------------

    def load_plan(self) -> None:
        """Show the chosen plan's files and generated flag, which the run then uses."""
        try:
            plan = read_benchmark_plan(self.edit_plan.text())
        except (OSError, ValueError) as exc:
            self.lbl_status.setText(f"Cannot read the plan: {exc}")
            return
        self.lbl_status.setText("")
        self.list_files.clear()
        self.list_files.addItems(plan.files)
        self.cb_generated.setChecked(plan.generated)

    def _browse_plan(self) -> None:
        self._browse(self.edit_plan, "Plan (*.toml)")
        self.load_plan()

    def _files(self) -> List[str]:
        return [self.list_files.item(i).text() for i in range(self.list_files.count())]

    def add_from_data_pool(self) -> None:
        have = set(self._files())
        for run in self._app_context.pool.loaded_runs:
            if run.file_path not in have:
                self.list_files.addItem(run.file_path)

    def _add_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Add file", "", "UNV (*.unv);;All files (*)")
        if path:
            self.list_files.addItem(path)

    def _browse(self, edit: QLineEdit, name_filter: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose", edit.text(), name_filter)
        if path:
            edit.setText(path)

    def _browse_dir(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Output folder", edit.text())
        if path:
            edit.setText(path)

    # ---- run -----------------------------------------------------------

    def build_command(self) -> List[str]:
        """Write the plan the dialog describes to a temp file and return the command that runs it."""
        plan = dataclasses.replace(
            read_benchmark_plan(self.edit_plan.text()),
            generated=self.cb_generated.isChecked(), files=self._files())
        handle, plan_path = tempfile.mkstemp(prefix="nvh_benchmark_plan_", suffix=".toml")
        os.close(handle)
        write_benchmark_plan(plan, plan_path)
        self._plan_path = plan_path
        handle, self._log_path = tempfile.mkstemp(prefix="nvh_benchmark_log_", suffix=".txt")
        os.close(handle)
        return build_benchmark_command(
            sys.executable, _ROOT, plan_path, self.edit_out.text(),
            full=self.combo_variant.currentText() == "Full", quick=self.cb_quick.isChecked(),
            baseline=self.edit_baseline.text().strip() or None, log_path=self._log_path)

    def run(self) -> None:
        try:
            command = self.build_command()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Run Benchmark", f"Cannot read the plan: {exc}")
            return
        self._output = ""
        self.progress.setRange(0, 0)
        self.report_view.clear()
        self._stopped = False
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.show()
        self.lbl_status.setText("Running…")
        # QProcess runs the Benchmark outside this process, so the GUI never blocks.
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedChannels)
        process.finished.connect(self._on_finished)
        process.start(command[0], command[1:])
        self._process = process
        self._poll.start()

    def stop(self) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._stopped = True
            self._process.kill()

    def _read_output(self) -> None:
        try:
            with open(self._log_path, encoding="utf-8", errors="replace") as handle:
                self._output = handle.read()
        except OSError:
            return
        progress = re.findall(r"^PROGRESS (\d+)/(\d+)\s*$", self._output, re.MULTILINE)
        if progress:
            done, total = map(int, progress[-1])
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    def _on_finished(self, exit_code: int, *_) -> None:
        self._poll.stop()
        self._read_output()
        self._remove_plan()
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.hide()
        if self._stopped:
            self.lbl_status.setText("Stopped.")
            return
        lines = self._output.strip().splitlines()
        md_path = lines[-1] if lines and lines[-1].endswith(".md") else ""
        if exit_code != 0 or not os.path.isfile(md_path):
            self.lbl_status.setText("Benchmark failed.")
            self.report_view.setPlainText(self._output)
            return
        self.lbl_status.setText("Done.")
        with open(md_path, encoding="utf-8") as handle:
            self.report_view.setMarkdown(handle.read())
        self._report_dir = os.path.dirname(md_path)
        self.btn_open.setEnabled(True)

    def _remove_plan(self) -> None:
        if self._plan_path:
            try:
                os.remove(self._plan_path)
            except OSError:
                pass
            self._plan_path = ""
        if self._log_path:
            try:
                os.remove(self._log_path)
            except OSError:
                pass
            self._log_path = ""

    def done(self, result: int) -> None:
        if self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(2000)
        self._poll.stop()
        self._remove_plan()
        super().done(result)
