"""Run a Benchmark plan: one Benchmark case per file x analysis x channel count."""

import dataclasses
import itertools
import json
import statistics
import threading
import time
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Union

from core.benchmark import benchmark_step, discard_benchmark_recording, record_benchmark_steps
from core.block_kinds import KIND_ORDER_CUT, KIND_OVERALL_LEVEL, KIND_SPECTROGRAM, KIND_SPECTRUM
from core.dsp_configs import (OrderTrackingConfig, OverallLevelConfig, SpectrogramConfig,
                              SpectrumConfig)
from io_modules.benchmark import BenchmarkPlan, read_machine_info, read_process_rss_mb
from io_modules.data_accessor import DataAccessor
from io_modules.measurement_files import discard_reader_caches, open_measurement_reader
from selection.tacho import find_tacho_channel
from signal_processing.result_blocks import (TrackingScratch, compute_order_cuts,
                                             compute_overall_level, compute_spectrogram,
                                             compute_spectrum)


class _Analysis(NamedTuple):
    compute: Callable  # (vibration block, tacho block or None, config, per-measurement scratch)
    config_type: type
    tracked: bool  # has a tracking_mode; the order cut is always tracked against rpm


class _Skipped(Exception):
    """The case cannot run on this file (no tacho); not a failure."""


# Adding an analysis to the Benchmark is one entry here.
_ANALYSES = {
    KIND_SPECTRUM: _Analysis(lambda block, tacho, config, scratch: compute_spectrum(block, config),
                             SpectrumConfig, False),
    KIND_SPECTROGRAM: _Analysis(compute_spectrogram, SpectrogramConfig, True),
    KIND_ORDER_CUT: _Analysis(compute_order_cuts, OrderTrackingConfig, True),
    KIND_OVERALL_LEVEL: _Analysis(compute_overall_level, OverallLevelConfig, True),
}

# Plan key -> config field it overrides, where the config has that field.
# No analysis config has an overlap: the program fixes it, so a plan cannot sweep it.
_PLAN_KEY_TO_FIELD = {"nfft": "fft_size", "rpm_step": "step"}

# After a timeout the worker gets an exception at its next Python line; a C call
# (FFT, disk read) runs on until it returns. This long it may take to stop.
_STOP_GRACE_S = 10.0


def resolve_benchmark_files(plan: BenchmarkPlan, *, generate: bool = True) -> List[str]:
    """Resolve the list of files to benchmark, adding the generated reference signal when requested."""
    files = list(plan.files)
    if plan.generated:
        if generate:
            from io_modules.benchmark import resolve_reference_signal
            ref_path = resolve_reference_signal()
        else:
            from io_modules.benchmark import resolve_reference_path
            ref_path = resolve_reference_path()
        if ref_path not in files:
            files.append(ref_path)
    return files


def plan_benchmark_cases(plan: BenchmarkPlan) -> List[Dict[str, Any]]:
    """Plan all Benchmark cases for plan without running them."""
    return [case for case, _, _, _, _ in _iter_planned_cases(plan, generate=False)]


def run_benchmark(
    plan: BenchmarkPlan,
    *,
    baseline: Optional[Union[str, Dict[str, Any]]] = None,
    on_case_done: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """Time every case of `plan`. Nothing is saved or looked up; like the app, a
    case keeps its TrackingPlan between runs (#500), so the first run is a first
    click on the file and the rest are repeated clicks.

    `on_case_done(done, total)` is called after each case."""
    runs_per_case = resolve_benchmark_runs_per_case(plan)
    timeout_s = plan.timeout_s
    cases = []
    planned = list(_iter_planned_cases(plan, generate=True))
    still_running = False
    for case, analysis, config, path, count in planned:
        if still_running:
            # Its steps would land in this case and its CPU would slow it down.
            case.update(status="skipped", reason="not run: a timed-out case before it is still running")
        else:
            still_running = _run_case(case, analysis, config, path, count, runs_per_case, timeout_s)
        cases.append(case)
        if on_case_done:
            on_case_done(len(cases), len(planned))
    machine = read_machine_info(resolve_benchmark_files(plan, generate=False))
    return build_benchmark_report(plan, cases, machine, baseline=baseline)


def resolve_benchmark_runs_per_case(plan: BenchmarkPlan) -> int:
    """How many times each case runs: once in quick mode, else the plan's repeats."""
    return 1 if plan.quick else max(1, plan.repeats)


def resolve_benchmark_config(case: Dict[str, Any]):
    """The analysis config a planned case runs with, rebuilt from its settings."""
    return _ANALYSES[case["analysis"]].config_type(**case["settings"])


def resolve_benchmark_skip(case: Dict[str, Any], has_tacho: bool) -> Optional[str]:
    """Why the case cannot run on its file, or None when it can."""
    return _skip_reason(_ANALYSES[case["analysis"]], resolve_benchmark_config(case), has_tacho)


def build_benchmark_run(steps, wall_s: float) -> Dict[str, Any]:
    """One run of a case: its wall time and the recorded steps merged by name."""
    return {"wall_s": wall_s, "steps": _merge_by_name(steps)}


def build_benchmark_report(plan: BenchmarkPlan, cases: List[Dict[str, Any]], machine: Dict[str, Any],
                           *, baseline: Optional[Union[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The Benchmark report over finished cases; an ok case gets its first/median summary."""
    for case in cases:
        if case.get("status") == "ok" and case.get("runs"):
            case["summary"] = _summary(case["runs"])
    report = {
        "machine": machine,
        "plan": dataclasses.asdict(plan),
        "cases": cases,
    }
    if baseline:
        from io_modules.benchmark import read_benchmark_report
        from ._delta import resolve_benchmark_delta
        if isinstance(baseline, str):
            baseline_data = read_benchmark_report(baseline)
            report = resolve_benchmark_delta(report, baseline_data, baseline_path=baseline)
        else:
            report = resolve_benchmark_delta(report, baseline)
    return report


def _iter_planned_cases(plan: BenchmarkPlan, *, generate: bool = True):
    for path in resolve_benchmark_files(plan, generate=generate):
        for kind in plan.analyses:
            analysis = _ANALYSES[kind]
            for config in _configs_for(analysis.config_type, plan):
                for count in plan.channels:
                    case = {
                        "file": path,
                        "analysis": kind,
                        "channels": count,
                        "settings": dataclasses.asdict(config),
                    }
                    yield case, analysis, config, path, count


def _expand_settings(plan: BenchmarkPlan) -> List[Dict[str, Any]]:
    """Expand plan.base and plan.sweep into a list of setting dicts."""
    unknown = (plan.base.keys() | plan.sweep.keys()) - _PLAN_KEY_TO_FIELD.keys()
    if unknown:
        # Silently dropped, it would look swept in the report while no case used it.
        raise ValueError(f"Unknown Benchmark setting(s) {sorted(unknown)}; "
                         f"a plan can set {sorted(_PLAN_KEY_TO_FIELD)}")
    if plan.quick or not plan.sweep:
        return [dict(plan.base)]

    swept = {k: v for k, v in plan.sweep.items() if v}
    if not swept:
        return [dict(plan.base)]

    if plan.mode == "product":
        keys = list(swept.keys())
        combinations = []
        for values in itertools.product(*[swept[k] for k in keys]):
            combo = dict(plan.base)
            combo.update(dict(zip(keys, values)))
            if combo not in combinations:
                combinations.append(combo)
        return combinations

    # Default: sweep mode -- vary one knob at a time around base
    combinations = [dict(plan.base)]
    for knob, values in swept.items():
        for val in values:
            combo = dict(plan.base)
            combo[knob] = val
            if combo not in combinations:
                combinations.append(combo)
    return combinations


def _configs_for(config_type: type, plan: BenchmarkPlan) -> List[Any]:
    combos = _expand_settings(plan)
    configs = []
    seen = []
    for combo in combos:
        cfg = _config_for(config_type, combo)
        cfg_dict = dataclasses.asdict(cfg)
        if cfg_dict not in seen:
            seen.append(cfg_dict)
            configs.append(cfg)
    return configs


def _run_case(case: Dict[str, Any], analysis: _Analysis, config, path: str, count,
              runs_per_case: int, timeout_s: float) -> bool:
    """Run the case into `case`; True when it timed out and its worker would not stop."""
    discard_reader_caches()  # else only the first case of a file would read it cold

    tracking = TrackingScratch()  # one per case, as SpectralRequests keeps one across clicks

    def execute():
        return [_time_one_run(analysis, config, path, count, tracking) for _ in range(runs_per_case)]

    if timeout_s <= 0:
        try:
            runs = execute()
            case.update(status="ok", runs=runs)
        except _Skipped as skipped:
            case.update(status="skipped", reason=str(skipped))
        except Exception as error:
            case.update(status="error", reason=f"{type(error).__name__}: {error}")
        return False

    runs = None
    error = None

    def worker():
        nonlocal runs, error
        try:
            runs = execute()
        except BaseException as ex:
            error = ex

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout_s)

    if t.is_alive():
        discard_benchmark_recording()
        case.update(status="timeout", reason=f"exceeded {timeout_s}s timeout")
        return not _stop_thread(t)
    if error is not None:
        if isinstance(error, _Skipped):
            case.update(status="skipped", reason=str(error))
        else:
            case.update(status="error", reason=f"{type(error).__name__}: {error}")
    else:
        case.update(status="ok", runs=runs)
    return False


def _stop_thread(thread: threading.Thread) -> bool:
    """Raise TimeoutError in a timed-out worker and wait for it; True once it ended."""
    if thread.ident is not None:
        import ctypes
        set_async_exc = ctypes.pythonapi.PyThreadState_SetAsyncExc
        set_async_exc.argtypes = [ctypes.c_ulong, ctypes.py_object]
        set_async_exc.restype = ctypes.c_int
        if set_async_exc(thread.ident, TimeoutError) > 1:
            set_async_exc(thread.ident, None)
    thread.join(timeout=_STOP_GRACE_S)
    return not thread.is_alive()


def _read_measurement_index(path: str):
    reader = open_measurement_reader(path)
    run_index = reader.scan_file_structure()
    reader.load_channels_on_demand(run_index)
    return run_index


def resolve_benchmark_channels(run_index, tacho, count) -> List:
    """The case's channels: the first `count` non-tacho readable channels, or all."""
    channels = [meta for meta in run_index.readable_channels() if meta is not tacho]
    return channels if count == "all" else channels[:int(count)]


def _config_for(config_type: type, base: Dict[str, Any]):
    fields = {f.name for f in dataclasses.fields(config_type)}
    overrides = {_PLAN_KEY_TO_FIELD[key]: value for key, value in base.items()
                 if _PLAN_KEY_TO_FIELD.get(key) in fields}
    return config_type(**overrides)


def _time_one_run(analysis: _Analysis, config, path: str, count,
                  tracking: TrackingScratch) -> Dict[str, Any]:
    wall_start = time.perf_counter()
    with record_benchmark_steps(read_process_rss_mb) as steps:
        # Opening and indexing the file is part of reading it.
        with benchmark_step("read"):
            run_index = _read_measurement_index(path)
        tacho = find_tacho_channel(run_index)
        reason = _skip_reason(analysis, config, tacho is not None)
        if reason:
            raise _Skipped(reason)
        tacho_block = None
        if tacho is not None and analysis.tracked:
            tacho_block = DataAccessor.fetch_channel_data(run_index, tacho)  # times its own "read"
        # Shared by all channels like the app does, and by the case's later runs.
        scratch = tracking.resolve_scratch(tacho_block, config) if analysis.tracked else {}
        for meta in resolve_benchmark_channels(run_index, tacho, count):
            block = DataAccessor.fetch_channel_data(run_index, meta)
            analysis.compute(block, tacho_block, config, scratch)  # steps are timed inside the DSP
    return build_benchmark_run(steps, time.perf_counter() - wall_start)


def _skip_reason(analysis: _Analysis, config, has_tacho: bool) -> Optional[str]:
    if analysis.tracked and getattr(config, "tracking_mode", "rpm") == "rpm" and not has_tacho:
        return "the file has no tacho channel"
    return None


def _merge_by_name(steps) -> List[Dict[str, Any]]:
    """One row per step name, in first-seen order: summed times, highest RAM peak."""
    merged: Dict[str, Dict[str, Any]] = {}
    for step in steps:
        row = merged.setdefault(step.name, {"name": step.name, "wall_s": 0.0, "cpu_s": 0.0,
                                            "peak_rss_mb": None})
        row["wall_s"] += step.wall_s
        row["cpu_s"] += step.cpu_s
        if step.peak_rss_mb is not None:
            row["peak_rss_mb"] = max(row["peak_rss_mb"] or 0.0, step.peak_rss_mb)
    return list(merged.values())


def _summary(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """First run (cold) and the median of the rest (warm), when there is a rest."""
    warm = [run["wall_s"] for run in runs[1:]]
    return {"first_wall_s": runs[0]["wall_s"],
            "median_wall_s": statistics.median(warm) if warm else None}
