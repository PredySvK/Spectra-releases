"""
Compute Benchmark deltas against a baseline report (ADR §1.132, #483).

Pure function over two Benchmark report dicts: matches cases present in both
reports, calculates wall time and per-step deltas from medians, and tracks cases
only present in one report without dropping them silently.
"""

import copy
import json
import ntpath
import os
import statistics
from typing import Any, Dict, List, Optional, Tuple


def resolve_benchmark_delta(
    benchmark_report: Dict[str, Any],
    baseline_report: Dict[str, Any],
    *,
    baseline_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compare `benchmark_report` against `baseline_report`.

    Returns a new report dict with `baseline` reference, `case["delta"]` for common
    cases, `case["baseline_matched"]` on every case, and `baseline_only_cases`.
    """
    report = copy.deepcopy(benchmark_report)
    ref = baseline_path or baseline_report.get("path") or "baseline"
    report["baseline"] = ref
    display = report.get("machine", {}).get("display")
    baseline_display = baseline_report.get("machine", {}).get("display")
    if display != baseline_display:
        # Headless ("none"), offscreen and a real screen time different work; their delta is noise.
        report["baseline_mismatch"] = f"display {display!r} vs baseline {baseline_display!r}: no delta"
        return report
    baseline_cases = baseline_report.get("cases", [])
    current_cases = report.get("cases", [])

    matched_baseline_indices = set()
    baseline_by_exact: Dict[tuple, Tuple[int, Dict[str, Any]]] = {}
    for idx, b_case in enumerate(baseline_cases):
        key = _resolve_case_identity(b_case)
        baseline_by_exact[key] = (idx, b_case)

    unmatched_current: List[Dict[str, Any]] = []
    matched_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

    # Pass 1: exact identity match (file path, analysis, channels, settings)
    for c_case in current_cases:
        key = _resolve_case_identity(c_case)
        if key in baseline_by_exact:
            idx, b_case = baseline_by_exact[key]
            matched_baseline_indices.add(idx)
            matched_pairs.append((c_case, b_case))
        else:
            unmatched_current.append(c_case)

    # Pass 2: basename fallback matching for cases across different directories/machines
    if unmatched_current:
        unmatched_baseline = [
            (idx, b) for idx, b in enumerate(baseline_cases)
            if idx not in matched_baseline_indices
        ]
        basename_map: Dict[tuple, List[Tuple[int, Dict[str, Any]]]] = {}
        for idx, b_case in unmatched_baseline:
            b_key = _resolve_case_basename_identity(b_case)
            basename_map.setdefault(b_key, []).append((idx, b_case))

        still_unmatched_current = []
        for c_case in unmatched_current:
            c_key = _resolve_case_basename_identity(c_case)
            candidates = basename_map.get(c_key, [])
            if len(candidates) == 1 and candidates[0][0] not in matched_baseline_indices:
                idx, b_case = candidates[0]
                matched_baseline_indices.add(idx)
                matched_pairs.append((c_case, b_case))
            else:
                still_unmatched_current.append(c_case)
        unmatched_current = still_unmatched_current

    # Compute deltas for matched pairs
    for c_case, b_case in matched_pairs:
        c_case["baseline_matched"] = True
        # A quick report has only its cold first run; then compare cold with cold.
        warm = _has_warm_runs(c_case) and _has_warm_runs(b_case)
        c_wall, c_steps = _resolve_case_medians(c_case, warm)
        b_wall, b_steps = _resolve_case_medians(b_case, warm)
        if c_wall is not None and b_wall is not None:
            delta_wall = c_wall - b_wall
            step_deltas = {}
            for name, c_step_wall in c_steps.items():
                if name in b_steps:
                    step_deltas[name] = c_step_wall - b_steps[name]
            c_case["delta"] = {
                "wall_s": delta_wall,
                "baseline_wall_s": b_wall,
                "steps": step_deltas,
            }
        else:
            c_case["delta"] = None

    # Cases only in current report receive no delta and are tracked
    for c_case in unmatched_current:
        c_case["baseline_matched"] = False
        c_case["delta"] = None

    # Cases only in baseline report are tracked explicitly
    baseline_only = [
        copy.deepcopy(b_case) for idx, b_case in enumerate(baseline_cases)
        if idx not in matched_baseline_indices
    ]
    report["baseline_only_cases"] = baseline_only

    return report


def _normalize_file(path: str) -> str:
    if not path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return os.path.normcase(os.path.normpath(path))


def _resolve_identity_tuple(file_ident: str, case: Dict[str, Any]) -> tuple:
    settings_str = json.dumps(case.get("settings", {}), sort_keys=True)
    return (
        file_ident,
        case.get("analysis"),
        str(case.get("channels")),
        settings_str,
    )


def _resolve_case_identity(case: Dict[str, Any]) -> tuple:
    return _resolve_identity_tuple(_normalize_file(case.get("file", "")), case)


def _resolve_case_basename_identity(case: Dict[str, Any]) -> tuple:
    base_file = ntpath.basename(case.get("file", ""))  # splits on / and \, so PC paths match on Linux
    return _resolve_identity_tuple(base_file, case)


def _has_warm_runs(case: Dict[str, Any]) -> bool:
    return len(case.get("runs", [])) > 1


def _resolve_case_medians(case: Dict[str, Any], warm: bool) -> Tuple[Optional[float], Dict[str, float]]:
    """Median of the warm runs (runs[1:]) when `warm`, else the cold first run."""
    if case.get("status") != "ok":
        return None, {}
    runs = case.get("runs", [])
    if not runs:
        return None, {}

    target_runs = runs[1:] if warm else runs[:1]
    case_wall = statistics.median(run["wall_s"] for run in target_runs)
    step_times: Dict[str, List[float]] = {}
    for run in target_runs:
        for step in run.get("steps", []):
            name = step.get("name")
            wall = step.get("wall_s")
            if name and wall is not None:
                step_times.setdefault(name, []).append(wall)

    step_medians = {
        name: statistics.median(times)
        for name, times in step_times.items()
        if times
    }
    return case_wall, step_medians
