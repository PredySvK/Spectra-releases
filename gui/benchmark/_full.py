"""Run a Benchmark plan through the real window: click, compute, draw, paint."""

import dataclasses
import os
import shutil
import sys
import tempfile
import time
import traceback

from PySide6.QtCore import QEventLoop, QSettings, QTimer

from core.benchmark import benchmark_step, discard_benchmark_recording, record_benchmark_steps
from core.jobs import JobState
from core.block_kinds import KIND_ORDER_CUT, KIND_OVERALL_LEVEL, KIND_SPECTROGRAM, KIND_SPECTRUM
from io_modules.benchmark import (read_benchmark_plan, read_machine_info, read_process_rss_mb,
                                  write_benchmark_report)
from io_modules.measurement_files import discard_reader_caches, open_measurement_reader
from orchestration.benchmark import (build_benchmark_report, build_benchmark_run,
                                     plan_benchmark_cases, resolve_benchmark_channels, resolve_benchmark_config,
                                     resolve_benchmark_files, resolve_benchmark_runs_per_case,
                                     resolve_benchmark_skip)
from selection.tacho import find_tacho_channel
from view_models.analysis_kinds import ANALYSIS_KINDS, resolve_analysis_kind, resolve_analysis_mode_of_kind

# Analysis -> the ribbon tab clicked to enter its mode; the mode and the AppContext
# attribute its config is read from come from the Analysis mode register.
_RIBBON_TAB = {
    KIND_SPECTRUM: 4,
    KIND_SPECTROGRAM: 3,
    KIND_ORDER_CUT: 2,
    KIND_OVERALL_LEVEL: 1,
}

# Not copied into the isolated settings: the startup folder would be scanned
# on start, and the last project would be opened (and could be written to).
_NOT_COPIED = {"primary_startup_data_directory", "open_last_project_on_startup"}

_QUIET_S = 1.5  # settled = no running jobs and no paint for this long


def run_full_benchmark(app, build_window, plan_path, out_dir, *, quick=False, baseline=None) -> None:
    """Run the plan, write the Benchmark report into `out_dir`, print its paths and end the process."""
    try:
        plan = read_benchmark_plan(plan_path)
        if quick:
            plan = dataclasses.replace(plan, quick=True)
        settings_folder = tempfile.mkdtemp(prefix="nvh_benchmark_")
        try:
            report = _run(app, build_window, plan, baseline, settings_folder)
        finally:
            shutil.rmtree(settings_folder, ignore_errors=True)
        for path in write_benchmark_report(report, out_dir):
            print(path)
        code = 0
    except Exception:
        traceback.print_exc()
        code = 1
    # Qt teardown of a window that never closed is not worth waiting on;
    # without the flush the paths above would be lost (ADR §1.132).
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def _run(app, build_window, plan, baseline, settings_folder):
    import app_context
    app_context.QSettings = _isolated_settings(settings_folder)

    if app.platformName() == "offscreen":
        # No GL context offscreen: pyqtgraph's GL curve paint would fail on every frame.
        import pyqtgraph
        pyqtgraph.setConfigOptions(useOpenGL=False)
    files = resolve_benchmark_files(plan)  # generates the reference signal before the window opens
    window = build_window()
    frame = window.workspace_frame
    context, jobs = frame.app_context, frame.job_manager
    context.use_result_cache_lookup = False
    _settle(app, jobs, deadline=None)
    if not frame.project_document.new_project():
        raise RuntimeError("could not start an empty project")
    _settle(app, jobs, deadline=None)

    runs_per_case = resolve_benchmark_runs_per_case(plan)
    indexes, cases = {}, []
    planned = list(plan_benchmark_cases(plan))
    still_running = False
    for case in planned:
        if still_running:
            # Its steps would land in this case and its CPU would slow it down.
            case.update(status="skipped", reason="not run: a job of a timed-out case is still running")
        else:
            try:
                still_running = _run_case(app, frame.ribbon, frame.workspace, context, jobs, case,
                                          indexes, runs_per_case, plan.timeout_s)
            except Exception as error:
                discard_benchmark_recording()
                case.update(status="error", reason=f"{type(error).__name__}: {error}")
        cases.append(case)
        print(f"PROGRESS {len(cases)}/{len(planned)}", flush=True)

    machine = read_machine_info(files)
    machine.update(_display_info(app, window))
    return build_benchmark_report(plan, cases, machine, baseline=baseline)


def _run_case(app, ribbon, workspace, context, jobs, case, indexes, runs_per_case, timeout_s) -> bool:
    """Run the case into `case`; True when it timed out and a job of it would not stop."""
    # The timeout covers the whole case, all its runs, as in the Headless variant.
    deadline = time.perf_counter() + timeout_s if timeout_s > 0 else None
    path = case["file"]
    if path not in indexes:
        # ponytail: a read hung inside the scan blocks the GUI thread; only a later wait sees the deadline
        reader = open_measurement_reader(path)
        indexes[path] = reader.scan_file_structure()
        reader.load_channels_on_demand(indexes[path])
    run_index = indexes[path]
    tacho = find_tacho_channel(run_index)
    reason = resolve_benchmark_skip(case, tacho is not None)
    if reason:
        case.update(status="skipped", reason=reason)
        return False
    rows = [(run_index, meta, meta.name)
            for meta in resolve_benchmark_channels(run_index, tacho, case["channels"])]
    analysis_mode = resolve_analysis_mode_of_kind(next(kind.name for kind in ANALYSIS_KINDS if kind.block_kind == case["analysis"]))
    capacity = resolve_analysis_kind(analysis_mode.analysis_kind).max_channels
    if capacity is not None and len(rows) > capacity:
        case.update(status="skipped", reason=f"the {analysis_mode.analysis_kind} tab shows only the first of several channels")
        return False

    # Entered as a click; setting current_analysis_mode alone does not switch the view.
    tab = _RIBBON_TAB[case["analysis"]]
    ribbon.setCurrentIndex(tab)
    if context.current_analysis_mode != analysis_mode.name:
        # A reordered ribbon would otherwise time another analysis under this name.
        raise RuntimeError(
            f"ribbon tab {tab} gave mode {context.current_analysis_mode!r}, expected {analysis_mode.name!r}")
    setattr(context, analysis_mode.settings_name, resolve_benchmark_config(case))
    # A comparison tab computes through the channel drop, which finds each file's tacho in the pool.
    if run_index not in context.pool.loaded_runs:
        context.pool.loaded_runs.append(run_index)
    discard_reader_caches()  # else only the first case of a file would read it cold

    runs = []
    for _ in range(runs_per_case):
        workspace.close_all_tabs()
        run = _time_one_click(app, workspace, jobs, rows, deadline) if _settle(app, jobs, deadline) else None
        if run is None:
            jobs.cancel_all()
            # A job deaf to cancel gets this long; after that the rest is skipped.
            _settle(app, jobs, deadline=time.perf_counter() + max(timeout_s, 2 * _QUIET_S))
            case.update(status="timeout", reason=f"exceeded {timeout_s}s timeout")
            return bool(jobs.running_jobs())
        runs.append(run)
    case.update(status="ok", runs=runs)
    return False


def _time_one_click(app, workspace, jobs, rows, deadline):
    """One click to a settled screen, or None when it ran past the deadline.
    Raises when a job of the click failed: its short time is no speed-up."""
    seen = {record.job_id for record in jobs.all_records()}
    start = time.perf_counter()
    with record_benchmark_steps(read_process_rss_mb) as steps:
        with benchmark_step("create_tab"):
            workspace.open_channels_tab(rows)
        with benchmark_step("gui_wait"):
            computed = _wait(lambda: not jobs.running_jobs(), deadline)
        if computed:
            done = time.perf_counter()
            settled = _settle(app, jobs, deadline)
    if not computed or not settled:
        discard_benchmark_recording()
        return None
    started = [record for record in jobs.all_records() if record.job_id not in seen]
    failed = [record for record in started if record.state is JobState.FAILED or record.errors]
    if failed or not started:
        raise RuntimeError("; ".join(f"job {record.label!r} {record.state.value}: {record.errors}"
                                     for record in failed) or "the click started no job")
    return build_benchmark_run(steps, max(done, app.last_paint) - start)


def _settle(app, jobs, deadline) -> bool:
    """Wait for no running jobs and _QUIET_S without a paint; False past the deadline."""
    return _wait(lambda: not jobs.running_jobs() and time.perf_counter() - app.last_paint >= _QUIET_S,
                 deadline)


def _wait(condition, deadline) -> bool:
    while not condition():
        if deadline is not None and time.perf_counter() > deadline:
            return False
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return True


def _isolated_settings(folder):
    """A QSettings(org, app) stand-in on an INI in `folder`, seeded once from the user's
    settings, which are only read. QSettings(org, app) ignores setDefaultFormat, hence the swap."""
    def build(organization, application):
        settings = QSettings(os.path.join(folder, application + ".ini"), QSettings.Format.IniFormat)
        if not settings.allKeys():
            user = QSettings(organization, application)
            for key in user.allKeys():
                if key not in _NOT_COPIED:
                    settings.setValue(key, user.value(key))
            settings.sync()
        return settings
    return build


def _display_info(app, window):
    screen = window.screen()  # the saved geometry may put it on a second monitor
    size = screen.size() if screen else None
    return {
        "display": app.platformName(),
        "screen": f"{size.width()}x{size.height()} @{screen.devicePixelRatio():g}" if size else "none",
        "opengl_renderer": _opengl_renderer(),
    }


def _opengl_renderer() -> str:
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext
        context, surface = QOpenGLContext(), QOffscreenSurface()
        surface.create()
        if not context.create() or not context.makeCurrent(surface):
            return "unavailable"
        renderer = context.functions().glGetString(0x1F01)  # GL_RENDERER
        context.doneCurrent()
        return str(renderer or "unavailable")
    except Exception as error:
        return f"unavailable ({type(error).__name__})"
