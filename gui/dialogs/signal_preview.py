# =====================================================================
# FILE: gui/dialogs/signal_preview.py
# =====================================================================
"""
Preview handler for the Signal Generator dialog.
Acts as the bridge between the dumb View (UI) and the core Math models.
Handles debounce timing, live preview calculations, and dynamic view scaling.
Forces strict Auto-Ranging on plots to prevent viewport lock-ups during axis swaps.

The live preview builds the same full-length arrays the export does, so it runs
as a quiet background job over the JobRunner port (see
io_modules.signal_generation.compute_preview_arrays) rather than on the GUI
thread -- otherwise every parameter edit at a high sampling rate would freeze the
dialog while tens of millions of samples are regenerated.
Submitting onto slot 'signal_generator_preview' supersedes any in-flight preview
automatically.
All internal documentation strings and variable labels are standardly written in English.
"""

import numpy as np
from PySide6.QtCore import QTimer
import pyqtgraph as pg

from core.jobs import job_step
from orchestration.jobs import JobRunner
from io_modules.signal_generation import compute_preview_arrays
from io_modules.signal_generation.signal_generation_engine import generate_rpm_profile

PREVIEW_SLOT_KEY = "signal_generator_preview"


class SignalPreviewHandler:
    def __init__(self, view, job_runner: JobRunner):
        self.view = view
        self.job_runner = job_runner
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.update_live_preview)

        self._bind_signals()

        # Enforce "View All" on startup
        self.set_view_all()

    def _bind_signals(self):
        self.view.sig_parameters_changed.connect(self.trigger_preview_update)
        self.view.btn_view_all.clicked.connect(self.set_view_all)
        self.view.btn_view_4p.clicked.connect(self.set_view_4_periods)
        self.view.tabs_channels.currentChanged.connect(self.trigger_preview_update)

    def trigger_preview_update(self):
        self.preview_timer.start(300)

    def set_view_all(self):
        params = self.view.get_generation_parameters()
        self.view.spin_prev_start.blockSignals(True)
        self.view.spin_prev_end.blockSignals(True)
        self.view.spin_prev_start.setValue(0.0)
        self.view.spin_prev_end.setValue(params["duration"])
        self.view.spin_prev_start.blockSignals(False)
        self.view.spin_prev_end.blockSignals(False)
        self.trigger_preview_update()

    def set_view_4_periods(self):
        components = self.view.get_active_channel_components()
        if not components:
            return

        params = self.view.get_generation_parameters()
        start_time = params["prev_start"]
        duration = params["duration"]

        # Robustly determine the RPM exactly at 'start_time' regardless of the complex profile shape
        t_dummy = np.linspace(0, duration, 1000)
        rpm_dummy = generate_rpm_profile(
            t_dummy,
            params["rpm_start"],
            params["rpm_stop"],
            params["direction"],
            params["plateaus_on"],
            params["plateaus"],
            params["plateau_ratio"]
        )
        current_rpm = np.interp(start_time, t_dummy, rpm_dummy)

        if current_rpm <= 0:
            current_rpm = 60.0

        min_freq = float('inf')

        for comp in components:
            c_type = comp["type"]
            c_val = comp["value"]

            if c_val <= 0:
                continue

            if c_type == "Sine signal":
                freq = c_val
            elif c_type == "Order":
                freq = c_val * (current_rpm / 60.0)
            else:
                continue

            if freq < min_freq:
                min_freq = freq

        if min_freq == float('inf'):
            self.view.spin_prev_end.setValue(start_time + 0.1)
        else:
            period = 1.0 / min_freq
            new_end = start_time + (4.0 * period)
            self.view.spin_prev_end.setValue(min(new_end, duration))

    def update_live_preview(self):
        params = self.view.get_generation_parameters()

        active_idx = self.view.tabs_channels.currentIndex()
        if active_idx >= 0 and params["channels"]:
            active_unit = params["channels"][active_idx]["unit"]
            self.view.vib_plot.setLabel('left', 'Amplitude', active_unit)

        # Read from the widgets here, on the GUI thread; hand plain data to the worker.
        active_components = self.view.get_active_channel_components()

        self.job_runner.submit(
            "Signal generator preview",
            steps=[job_step("Compute preview", compute_preview_arrays, params, active_components)],
            lane="interactive",
            slot_key=PREVIEW_SLOT_KEY,
            quiet=True,
            on_step=lambda payload, _idx: self._on_preview_ready(payload),
            on_error=lambda message, _idx: self._on_preview_error(message),
        )

    def shutdown(self):
        """Stop accepting preview results before the dialog is destroyed.

        An in-flight preview job calls back later; without cancelling the slot,
        its on_step/on_error would draw into plot widgets whose C++ objects
        the dialog's deleteLater() already freed -> RuntimeError in a Qt slot
        -> crash popup (audit 02, S11/11.1). Cancelling the slot marks any
        running job superseded/cancelled so its callbacks are suppressed.
        """
        self.preview_timer.stop()
        self.job_runner.cancel_slot(PREVIEW_SLOT_KEY)

    def _on_preview_ready(self, data: dict):
        self.view.rpm_plot.clear()
        self.view.rpm_plot.plot(data["t"], data["rpm"], pen=pg.mkPen('r', width=2))
        self.view.rpm_plot.enableAutoRange(axis=pg.ViewBox.XYAxes)

        self.view.vib_plot.clear()
        if data["vib"] is None:
            return

        # Dynamic X-Axis plotting with forced auto-ranging to prevent locked viewports
        if data["x_axis_mode"] == "Time":
            self.view.vib_plot.setLabel('bottom', 'Time', 's')
            self.view.vib_plot.plot(data["t"], data["vib"], pen=pg.mkPen('y', width=1))
        elif data["x_axis_mode"] == "RPM":
            self.view.vib_plot.setLabel('bottom', 'Speed', 'RPM')
            self.view.vib_plot.plot(data["rpm"], data["vib"], pen=pg.mkPen('y', width=1))

        self.view.vib_plot.enableAutoRange(axis=pg.ViewBox.XYAxes)

    def _on_preview_error(self, _message: str = ""):
        self.view.vib_plot.setTitle("Preview failed - check parameters")


