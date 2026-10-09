# =====================================================================
# FILE: gui/jobs/job_status_bar.py
# =====================================================================
"""
The small "what is running" strip at the foot of the left dock column.

It used to be the last widget of the master layout, shown only while a job
ran. Every short job -- drawing one result from the Result Pool is one --
then flashed it in and out, and the whole dock area jumped by its height
twice in a fraction of a second. So the strip now has a fixed home and never
hides: with nothing running it reads "Idle", and its height never changes.
That home is its own title-less dock under Explorer and Filters rather than
the bottom of the Filters dock, so closing Filters does not take it along.

It shows one job: the newest loud one still running. Two rules keep it from
becoming noise. A quiet job (the folder watcher's re-scan, which fires
whenever a measurement lands on disk) never claims the strip -- it is still
in the Jobs dock, where someone looking for it will find it. And with several
jobs running, the others are a count rather than a second row; the strip is a
reassurance that work is happening, and the dock is the place that
enumerates it.

When the shown job ends, its outcome (100 % Done, Failed, Cancelled) stays on
the strip for LINGER_MS before it falls back to Idle. A job that finishes in
50 ms would otherwise be a blink nobody can read; this way a short job still
visibly says that it ran and how it ended.

Double-clicking the strip emits `open_jobs_requested`; the window answers by
bringing up the Jobs tab, where every job is listed.

All internal documentation strings and variable labels are standardly written
in English.
"""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core.jobs import JobState

# How long a finished job's outcome stays on the strip.
LINGER_MS = 750

_IDLE_TEXT = "Idle"

# The bar's own text while a job runs; Qt fills in %p (#469).
_RUNNING_FORMAT = "Running – %p %"
_PLAIN_FORMAT = "%p %"

# Label indent, in spaces' worth of the label font, so the text sits off the
# dock edge whether it reads Idle or names a job (#469).
_INDENT_SPACES = 3

_OUTCOME_TEXT = {
    JobState.DONE: "Done",
    JobState.FAILED: "Failed",
    JobState.CANCELLED: "Cancelled",
    JobState.SUPERSEDED: "Superseded",
}


class JobStatusBar(QWidget):
    """Progress and Cancel for the job the user is most likely waiting on."""

    open_jobs_requested = Signal()

    def __init__(self, job_manager, parent=None, linger_ms: int = LINGER_MS):
        super().__init__(parent)
        self.job_manager = job_manager
        self._job_id = None
        self._cancelling_job_id = None
        self._full_text = ""

        # Two rows rather than one: the Filters column is narrow, and the
        # label is the part that needs the width.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)
        # Rows sit at the bottom: with Explorer and Filters both closed the
        # dock is given the whole column height (WorkspaceLayout).
        layout.addStretch(1)

        self.label = QLabel("")
        # Ignored, so a long job label is elided instead of widening the
        # whole left dock column.
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.label.setIndent(self.label.fontMetrics().horizontalAdvance(" " * _INDENT_SPACES))
        layout.addWidget(self.label)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(True)
        self.others = QLabel("")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setMaximumWidth(80)
        row.addWidget(self.bar, 1)
        row.addWidget(self.others)
        row.addWidget(self.btn_cancel)
        layout.addLayout(row)

        # Not Fixed vertically: QDockWidget centres a fixed-height widget, and
        # the strip has to fill the dock for the top stretch to push its rows
        # down. Its normal height is pinned on the dock (WorkspaceLayout).
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setToolTip("Double-click to open the Jobs panel")

        self._linger = QTimer(self)
        self._linger.setSingleShot(True)
        self._linger.setInterval(linger_ms)
        self._linger.timeout.connect(self._refresh)

        self.btn_cancel.clicked.connect(self._cancel_current)
        job_manager.job_added.connect(self._refresh)
        job_manager.job_changed.connect(self._refresh)
        job_manager.job_finished.connect(self._refresh)

        self._refresh()

    def _cancel_current(self):
        if self._job_id is not None:
            self.job_manager.cancel(self._job_id)
            # cancel() only sets the token; a job with a step in flight stays
            # RUNNING until it returns, so the button has to disable itself to
            # show the click registered. The old `state is not CANCELLED` guard
            # never fired -- _pick_job only ever returns running jobs (audit 02,
            # finding S3/3.11).
            self._cancelling_job_id = self._job_id
            self.btn_cancel.setEnabled(False)

    def _pick_job(self):
        """Newest loud running job, or None."""
        loud = [r for r in self.job_manager.running_jobs() if not r.quiet]
        return loud[-1] if loud else None

    def _refresh(self, _job_id=None):
        record = self._pick_job()
        if record is not None:
            self._linger.stop()
            self._show_running(record)
            return

        if self._job_id is not None:
            # The job on the strip just ended: hold its outcome for a moment.
            finished = self.job_manager.record(self._job_id)
            self._job_id = None
            if finished is not None and not finished.is_running:
                self._show_finished(finished)
                self._linger.start()
                return

        if not self._linger.isActive():
            self._show_idle()

    def _show_running(self, record):
        self._job_id = record.job_id
        # The step (which file, which channel) lives in the tooltip: on the
        # narrow strip it pushed the counter out of sight.
        counter = f" — {record.progress_text}" if record.total > 1 else ""
        self._set_text(f"{record.label}{counter}", tooltip=record.step_label or None)
        self.bar.setFormat(_RUNNING_FORMAT)
        self.bar.setTextVisible(True)
        self.bar.setValue(record.percent)

        running = len(self.job_manager.running_jobs())
        self.others.setText(f"+{running - 1} more" if running > 1 else "")
        self.btn_cancel.setEnabled(record.job_id != self._cancelling_job_id)

    def _show_finished(self, record):
        outcome = _OUTCOME_TEXT.get(record.state, record.state.value)
        self._set_text(f"{record.label} — {outcome}")
        self.bar.setFormat(_PLAIN_FORMAT)
        self.bar.setTextVisible(True)
        self.bar.setValue(100 if record.state is JobState.DONE else record.percent)
        self.others.setText("")
        self.btn_cancel.setEnabled(False)

    def _show_idle(self):
        self._set_text(_IDLE_TEXT)
        self.bar.setTextVisible(False)
        self.bar.setValue(0)
        self.others.setText("")
        self.btn_cancel.setEnabled(False)

    def _set_text(self, text: str, tooltip=None):
        self._full_text = text
        if text == _IDLE_TEXT:
            self.label.setToolTip(self.toolTip())
        else:
            self.label.setToolTip(text if tooltip is None else f"{text}\n{tooltip}")
        self._elide()

    def _elide(self):
        width = max(self.label.width() - self.label.indent(), 0)
        self.label.setText(self.label.fontMetrics().elidedText(
            self._full_text, Qt.ElideRight, width) if width > 0 else self._full_text)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.open_jobs_requested.emit()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def text(self) -> str:
        """The full, un-elided label text (what the tooltip shows)."""
        return self._full_text
