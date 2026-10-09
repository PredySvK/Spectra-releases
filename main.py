# =====================================================================
# FILE: main.py
# =====================================================================
"""
Core OS shell layout container initializing global runtime context engines.
All internal documentation strings and variable labels are standardly written in English.
"""

import sys
import os
import threading
import traceback
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QSurfaceFormat, QIcon
from PySide6.QtCore import Qt, QTimer, QByteArray, QEventLoop
import pyqtgraph as pg

from gui.shell import FramelessWindow


def run_keeping_gui_alive(func, *args) -> None:
    """Run ``func`` on a thread while this one keeps pumping events; re-raise its error.

    Starting a freshly downloaded installer can block for many seconds in the
    antimalware scan, and a GUI thread that does not pump events is flagged
    "not responding" by Windows.
    """
    error: list[BaseException] = []

    def target():
        try:
            func(*args)
        except BaseException as exc:  # re-raised on the calling thread
            error.append(exc)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if not thread.is_alive() else None)
    timer.start(50)
    if thread.is_alive():
        loop.exec()
    timer.stop()
    if error:
        raise error[0]


class MainApplicationShell(FramelessWindow):
    """
    Core OS shell layout container initializing global runtime context engines.
    """

    def __init__(self, startup_project_path: str | None = None):
        super().__init__()
        self._jobs_drained = True
        from core.app_metadata import window_title
        self.setWindowTitle(window_title())

        # Initialize visual frame
        from gui.main_window import MainWindowFrame
        self.workspace_frame = MainWindowFrame(parent=self, startup_project_path=startup_project_path,
                                               install_update=self.run_update)
        self.setCentralWidget(self.workspace_frame)

        # Hand the ribbon strip to the frameless base as this window's title bar.
        if hasattr(self.workspace_frame, "bind_frameless_window"):
            self.workspace_frame.bind_frameless_window(self)

        self._restore_window_geometry()

    # ---- window geometry ---------------------------------------------

    def _geometry_key(self) -> str:
        return "window_geometry"

    def _restore_window_geometry(self) -> None:
        """
        Bring the window back where the user last left it (size, monitor and
        maximised state all ride inside saveGeometry()). Restoring an explicit
        normal geometry is what stops a later restore-down from letting Qt
        invent a rect on the wrong monitor -- the reported "jumps to another
        screen" bug. First launch has nothing saved: pick a sane centred size
        on the primary screen, then maximise.
        """
        settings = self.workspace_frame.app_context.settings
        saved = settings.value(self._geometry_key(), None)
        if isinstance(saved, QByteArray) and not saved.isEmpty() \
                and self.restoreGeometry(saved):
            # restoreGeometry replays the maximised flag but leaves the actual
            # show() call to us; calling the matching one forces a clean
            # relayout (a plain show() left a white strip along the frame until
            # the first manual maximise).
            if self.windowState() & Qt.WindowMaximized:
                self.showMaximized()
            else:
                self.showNormal()
            return

        screen = QApplication.primaryScreen()
        area = screen.availableGeometry()
        w, h = int(area.width() * 0.82), int(area.height() * 0.82)
        self.resize(w, h)
        self.move(area.center().x() - w // 2, area.center().y() - h // 2)
        self.showMaximized()

    def _save_window_geometry(self) -> None:
        settings = self.workspace_frame.app_context.settings
        settings.setValue(self._geometry_key(), self.saveGeometry())

    def run_update(self, installer) -> bool:
        """Use the normal close; closeEvent launches the installer after teardown."""
        self._update_installer = installer
        try:
            return self.close()
        finally:
            self._update_installer = None

    def closeEvent(self, event):
        """Guarantees that all un-pinned graph windows and children are destroyed cleanly."""
        if hasattr(self, 'workspace_frame') and self.workspace_frame:
            # Asked first: closing cancels every job, and a cancelled batch run
            # discards every result set it already computed (#411). A batch
            # that finishes while this question is open marks the project
            # dirty, so the unsaved-changes question below still covers it.
            if not _confirm_cancelling_running_jobs(self.workspace_frame.job_manager, self):
                event.ignore()
                return

            # Metadata edits and unit corrections live only in the project, so
            # closing with them unsaved would discard them silently. Browsing a
            # folder never reaches here: it does not mark the project unsaved.
            if not self.workspace_frame.project_document.confirm_discarding_unsaved("closing"):
                event.ignore()
                return

            from gui.help import close_help
            close_help()

            ctx = self.workspace_frame.app_context

            # Lock the current directory into the startup memory slot.
            if ctx.active_directory:
                ctx.settings.setValue("primary_startup_data_directory", ctx.active_directory)

            # Force active configurations serialization before window gets dismantled by OS.
            # save_state() is a no-op if the layout was not restored this session (#413).
            self.workspace_frame.workspace_layout.save_state()
            self._save_window_geometry()
            ctx.settings.sync()
            # The only window, so its job queue is always waited on before close.
            self._jobs_drained = bool(self.workspace_frame.close_workspace_dependencies(wait_for_jobs=True))

            # Launched only after settings are saved and the workspace is torn
            # down: the installer closes a still-running Spectra, and that must
            # never interrupt the saves above. Teardown cannot be undone, so a
            # failed launch still closes the window.
            installer = getattr(self, "_update_installer", None)
            if installer is not None:
                from io_modules.update import remove_installer, run_installer
                self.setWindowTitle("Spectra - starting update...")
                try:
                    run_keeping_gui_alive(run_installer, installer)
                except OSError as error:
                    remove_installer(installer)
                    QMessageBox.warning(self, "Spectra Update",
                                        "Could not start the Update installer, so Spectra is "
                                        f"closing without updating. Start it again to retry.\n{error}")

        event.accept()


def _confirm_cancelling_running_jobs(job_runner, parent) -> bool:
    """
    Asks before closing would cancel work the user started and is waiting on.

    Only loud batch-lane jobs count: those are the runs whose results a cancel
    throws away. Quiet jobs (the folder watcher's re-scan) and the interactive
    lane (previews, cache adoption) lose nothing worth a question. Returns
    False when the user chooses to keep the window open.
    """
    running = [r for r in job_runner.running_jobs()
               if r.lane == "batch" and not r.quiet]
    if not running:
        return True

    labels = "\n".join(f"  - {r.label}" for r in running)
    count = f"{len(running)} job is" if len(running) == 1 else f"{len(running)} jobs are"
    answer = QMessageBox.question(
        parent,
        "Jobs still running",
        f"{count} still running:\n{labels}\n\n"
        "Closing cancels them and discards what they have computed so far.\n"
        "Cancel them and close?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


# =====================================================================
# GLOBAL EXCEPTION HANDLER FOR COMPILED EXECUTABLES
# =====================================================================
def global_exception_handler(exc_type, exc_value, exc_traceback):
    """
    Catches all unhandled exceptions globally and writes them to a persistent crash log file.
    Crucial for debugging compiled .exe applications where the console is hidden.
    Triggers a GUI pop-up alert to notify the end-user.
    """
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Logs must land in a per-user writable location: an installed build sits in
    # Program Files (read-only), so writing next to the executable would fail
    # silently exactly when the crash log is needed most.
    from core.asset_paths import user_data_dir
    log_dir = user_data_dir()
    log_path = os.path.join(str(log_dir), "crash_log.txt")

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n")
            f.write(f"CRITICAL SYSTEM CRASH AT: {timestamp}\n")
            f.write(f"{'=' * 60}\n")
            f.write(error_msg)
            f.write("\n")
    except Exception:
        pass  # Failsafe if the directory is strictly write-protected

    # Trigger GUI Pop-up Alert safely if QApplication is active. sys.excepthook can
    # run on whatever thread raised the exception; QMessageBox.exec() is only legal
    # on the main/GUI thread, so the popup is marshalled there via a queued call on
    # the QApplication instance (which always lives on the main thread) rather than
    # constructed directly here.
    try:
        app = QApplication.instance()
        if app:
            def _show_crash_popup():
                msg_box = QMessageBox()
                msg_box.setIcon(QMessageBox.Icon.Critical)
                msg_box.setWindowTitle("Unexpected Application Error")
                # The handler does not terminate the process: on PySide6 6.11 an
                # unhandled exception in a Qt slot passes through sys.excepthook
                # and the event loop keeps running (measured in audit S2). Claiming
                # "the application must close" while it stays open is worse than
                # either real outcome -- the user cannot tell whether to restart.
                msg_box.setText(
                    "An unexpected error occurred. The application will try to "
                    "continue; save your work and restart.")
                msg_box.setInformativeText(
                    f"A detailed crash log has been saved to:\n{log_path}\n\nPlease share this file with the engineering team.")
                msg_box.setDetailedText(error_msg)
                msg_box.exec()

            QTimer.singleShot(0, app, _show_crash_popup)
    except Exception:
        pass  # Popup is best-effort; the crash log on disk is the real record.

    # Pass the exception back to the default system handler
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


# Override the default system exception hook with our custom logging engine
sys.excepthook = global_exception_handler

# =====================================================================
# THE MAIN EXECUTION BLOCK (ALWAYS AT THE BOTTOM)
# =====================================================================
def resolve_startup_project_path(argv: list[str]) -> str | None:
    """Pick the first project argument, preserving its spelling for project open."""
    if "--benchmark" in argv:
        return None
    from core.project_model import PROJECT_EXTENSION

    return next((arg for arg in argv if arg.lower().endswith(PROJECT_EXTENSION)), None)


def _parse_benchmark_args(argv):
    """`main.py --benchmark [plan.toml] [--out DIR] [--quick] [--baseline REPORT]`, or None."""
    if "--benchmark" not in argv:
        return None
    import argparse
    from benchmark import DEFAULT_OUT_DIR
    from io_modules.benchmark import DEFAULT_PLAN_PATH
    parser = argparse.ArgumentParser(description="Full Benchmark: time the real window up to paint")
    parser.add_argument("--benchmark", nargs="?", const=DEFAULT_PLAN_PATH, metavar="PLAN",
                        help="Benchmark plan (TOML)")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR, help="folder for the Benchmark report")
    parser.add_argument("--quick", action="store_true", help="one run per case")
    parser.add_argument("--baseline", help="path to baseline Benchmark report (JSON)")
    parser.add_argument("--log", help="file that receives the output instead of stdout")
    return parser.parse_known_args(argv)[0]


if __name__ == "__main__":
    if sys.argv[1:2] == ["--benchmark-headless"]:  # a frozen build has no benchmark.py to run
        import benchmark
        benchmark.main(sys.argv[2:])
        sys.exit(0)
    benchmark_args = _parse_benchmark_args(sys.argv[1:])
    if benchmark_args:
        from benchmark import redirect_output
        redirect_output(benchmark_args.log)
        # A crash popup would hang a run nobody is watching.
        sys.excepthook = sys.__excepthook__

    # Globally share OpenGL contexts to enable background caching in PySide6
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    fmt = QSurfaceFormat()
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    # Core high-speed performance parameters configurations for GPU rendering
    pg.setConfigOptions(antialias=False, useOpenGL=True, enableExperimental=True)

    # Fire up application execution layer loop
    if benchmark_args:
        from gui.benchmark import BenchmarkApplication
        app = BenchmarkApplication(sys.argv)
    else:
        app = QApplication(sys.argv)

    from core.app_metadata import APP_NAME, APP_USER_MODEL_ID, APP_VERSION
    from core.asset_paths import resource_path
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setWindowIcon(QIcon(resource_path("resources", "icons", "app_icon.png")))

    # Windows groups taskbar entries and picks their icon by AppUserModelID; without
    # an explicit one a script run shows the generic python.exe icon.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass  # Taskbar grouping/icon only; not worth failing startup over.

    if benchmark_args:
        from gui.benchmark import run_full_benchmark
        run_full_benchmark(app, MainApplicationShell, benchmark_args.benchmark, benchmark_args.out,
                           quick=benchmark_args.quick, baseline=benchmark_args.baseline)

    startup_project_path = resolve_startup_project_path(sys.argv[1:])
    if startup_project_path:
        from gui.project_claim import activate_holder
        if activate_holder(startup_project_path):  # already open in another Spectra (#546)
            sys.exit(0)
    window = MainApplicationShell(startup_project_path=startup_project_path)
    # The shell is already shown, so the check starts after the window
    # appears; the Full Benchmark above never gets here, so it never asks
    # the network or opens an Update dialog mid-run.
    QTimer.singleShot(0, window, window.workspace_frame.update_handler.run_startup_check)
    from gui.help import show_help_at_startup
    QTimer.singleShot(0, window, lambda: show_help_at_startup(window))
    exit_code = app.exec()
    if not getattr(window, "_jobs_drained", True):
        # A background job step did not finish within the wait_for_done limit
        # (e.g. an un-cancellable read or computation). The event loop has returned,
        # the window is closed, and user state was saved in closeEvent. Hard exit
        # terminates the abandoned worker threads without lingering on QThreadPool
        # destructor (#414).
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(exit_code)
    sys.exit(exit_code)




