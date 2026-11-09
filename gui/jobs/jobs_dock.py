# =====================================================================
# FILE: gui/jobs/jobs_dock.py
# =====================================================================
"""
The queue and its history, as a table: what is running, what finished, how
long it took and what went wrong.

Sits beside the log rather than in it. The log is a chronological stream the
user reads forward; this answers "what is the application doing right now"
and "why did that export not produce everything", which are lookups, not
reading. A finished job keeps its errors here after the log has scrolled
past them.

Rows are updated in place, not rebuilt: progress moves on every step of every
job, and re-populating a hundred-row table at that rate would spend more time
drawing the queue than working through it.

A Batch run waiting its turn is not a job yet -- the job runner does not know
it -- but the user looks for it here (#966, ADR batch §1.267). The window's
batch-run handle lists the waiting ones; they sit on top, above the jobs,
newest first like them, so the one to start next sits right above the job
computing now. "Cancel Selected" drops just that one; "Clear List" leaves
them, they are not finished.

All internal documentation strings and variable labels are standardly written
in English.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.jobs import JobState

COLUMNS = ("Job", "Progress", "State", "Time")

STATE_TEXT = {
    JobState.QUEUED: "Queued",
    JobState.RUNNING: "Running",
    JobState.DONE: "Done",
    JobState.FAILED: "Failed",
    JobState.CANCELLED: "Cancelled",
    JobState.SUPERSEDED: "Superseded",
}
WAITING_TEXT = "Waiting"
# Where a waiting row keeps the key it is cancelled by; a job row keeps its
# job id under Qt.UserRole.
WAITING_KEY_ROLE = Qt.UserRole + 1

# The widest text each narrow column can show. The columns are sized for these
# up front: sized to their contents they jumped wider and narrower as rows went
# from "Done" to "Running" and back, which made the whole table twitch.
WIDEST_TEXT = {
    1: ("1000/1000",),
    2: (*(f"{text} (999 error(s))" for text in STATE_TEXT.values()),
        "Running – 100 % (999 error(s))"),
    3: ("10000.0 s",),
}
CELL_PADDING = 24   # px, room for the cell margins and header sort arrow


class JobsDockWidget(QWidget):
    """
    Every job the runner remembers, newest on top, under the waiting Batch
    runs of `waiting_batch_runs` (the window's `WorkflowRunBridge`) when given.
    """

    def __init__(self, job_runner, parent=None, *, waiting_batch_runs=None):
        super().__init__(parent)
        self.job_runner = job_runner
        self.waiting_batch_runs = waiting_batch_runs
        self._rows = {}      # job_id -> row index
        self._waiting_rows = 0   # rows 0..n-1 are the waiting Batch runs

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        # The name column carries the text and stretches, its label at the
        # start so "Job" does not float in the middle. The other three are a
        # fixed width wide enough for their longest possible text, centred.
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        metrics = self.table.fontMetrics()
        for column, samples in WIDEST_TEXT.items():
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            widest = max(metrics.horizontalAdvance(text)
                         for text in (*samples, COLUMNS[column]))
            self.table.setColumnWidth(column, widest + CELL_PADDING)
            self.table.horizontalHeaderItem(column).setTextAlignment(Qt.AlignCenter)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel Selected")
        self.btn_cancel_all = QPushButton("Cancel All")
        self.btn_clear = QPushButton("Clear List")
        self.btn_clear.setToolTip("Remove finished jobs from the list; running jobs stay.")
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_cancel_all)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_clear)
        layout.addLayout(buttons)

        self.btn_cancel.clicked.connect(self._cancel_selected)
        self.btn_cancel_all.clicked.connect(self._cancel_all)
        self.btn_clear.clicked.connect(self._clear_history)

        job_runner.job_added.connect(self._on_job_added)
        job_runner.job_changed.connect(self._on_job_changed)

        # A dock created after jobs have already run (restored layout, or a
        # dock the user opens for the first time mid-session) starts from
        # whatever the manager remembers rather than from empty.
        for record in job_runner.all_records():
            self._on_job_added(record.job_id)
        if waiting_batch_runs is not None:
            waiting_batch_runs.connect_waiting_changed(self._on_waiting_changed)
            self._on_waiting_changed()

    # ---- table maintenance --------------------------------------------

    def _on_job_added(self, job_id: int):
        if job_id in self._rows:
            return
        # Newest on top: the job the user just started is the one they look
        # for, and it should not sit below a hundred rows of history. Only
        # the waiting Batch runs, still to come, sit above it.
        row = self._waiting_rows
        for other in self._rows:
            self._rows[other] += 1
        self._insert_row(row)
        self._rows[job_id] = row
        self._on_job_changed(job_id)
        self._drop_trimmed_rows()

    def _on_job_changed(self, job_id: int):
        row = self._rows.get(job_id)
        record = self.job_runner.record(job_id)
        if row is None or record is None:
            return

        state_text = STATE_TEXT.get(record.state, record.state.value)
        if record.state is JobState.RUNNING:
            state_text = f"{state_text} – {record.percent} %"
        if record.errors:
            state_text = f"{state_text} ({len(record.errors)} error(s))"
        duration = record.duration
        time_text = f"{duration:.1f} s" if duration is not None else ""

        self.table.item(row, 0).setText(record.label)
        self.table.item(row, 1).setText(record.progress_text)
        self.table.item(row, 2).setText(state_text)
        self.table.item(row, 3).setText(time_text)

        # The errors are the reason this dock outlives the log line: kept on
        # the row itself so a job that finished ten minutes ago can still say
        # which files it could not read.
        tooltip = "\n".join(record.errors[:10]) if record.errors else record.step_label
        for column in range(len(COLUMNS)):
            self.table.item(row, column).setToolTip(tooltip)

        self.table.item(row, 0).setData(Qt.UserRole, job_id)

    def _insert_row(self, row: int) -> None:
        self.table.insertRow(row)
        for column in range(len(COLUMNS)):
            item = QTableWidgetItem("")
            if column in WIDEST_TEXT:
                item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, column, item)

    def _on_waiting_changed(self):
        """Rebuild the waiting rows: a handful at most, and they change only on a click or a turn."""
        waiting = tuple(reversed(self.waiting_batch_runs.waiting))
        for _ in range(self._waiting_rows):
            self.table.removeRow(0)
        for row, run in enumerate(waiting):
            self._insert_row(row)
            self.table.item(row, 0).setText(run.job_label)
            self.table.item(row, 2).setText(WAITING_TEXT)
            self.table.item(row, 0).setData(WAITING_KEY_ROLE, run.key)
            for column in range(len(COLUMNS)):
                self.table.item(row, column).setToolTip("Starts once the Batch runs before it finish.")
        shift = len(waiting) - self._waiting_rows
        self._waiting_rows = len(waiting)
        for job_id in self._rows:
            self._rows[job_id] += shift

    def _drop_trimmed_rows(self):
        """Keeps the table in step with the manager's bounded history."""
        known = {record.job_id for record in self.job_runner.all_records()}
        for job_id in [j for j in self._rows if j not in known]:
            row = self._rows.pop(job_id)
            self.table.removeRow(row)
            for other, other_row in self._rows.items():
                if other_row > row:
                    self._rows[other] = other_row - 1

    # ---- actions -------------------------------------------------------

    def _clear_history(self):
        self.job_runner.clear_history()
        self._drop_trimmed_rows()

    def _cancel_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        key = item.data(WAITING_KEY_ROLE)
        if key is not None:
            self.waiting_batch_runs.cancel_waiting(key)
            return
        job_id = item.data(Qt.UserRole)
        if job_id is not None:
            self.job_runner.cancel(int(job_id))

    def _cancel_all(self):
        # The waiting ones first: cancelling the running job ends its Batch
        # run, and the next waiting one would take the slot.
        if self.waiting_batch_runs is not None:
            for run in self.waiting_batch_runs.waiting:
                self.waiting_batch_runs.cancel_waiting(run.key)
        self.job_runner.cancel_all()
