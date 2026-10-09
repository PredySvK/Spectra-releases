"""Write the Benchmark report: JSON first, Markdown rendered from that JSON."""

import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from io_modules.atomic_write import write_json_atomic, write_text_atomic


def read_benchmark_report(path: str) -> Dict[str, Any]:
    """Read a Benchmark report from JSON."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write_benchmark_report(benchmark_report: Dict[str, Any], out_dir: str) -> Tuple[str, str]:
    """Write `benchmark_<hostname>_<timestamp>.json` and `.md` into `out_dir`."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = os.path.join(out_dir, f"benchmark_{benchmark_report['machine']['hostname']}_{stamp}")
    json_path = write_json_atomic(stem + ".json", benchmark_report)
    with open(json_path, encoding="utf-8") as handle:
        markdown = build_benchmark_markdown(json.load(handle))
    md_path = write_text_atomic(stem + ".md", lambda handle: handle.write(markdown), encoding="utf-8")
    return json_path, md_path


def build_benchmark_markdown(benchmark_report: Dict[str, Any]) -> str:
    lines = ["# Benchmark report"]
    if benchmark_report.get("baseline"):
        lines += ["", f"Baseline: `{benchmark_report['baseline']}`"]
        if benchmark_report.get("baseline_mismatch"):
            lines += ["", f"Not compared: {benchmark_report['baseline_mismatch']}"]
    lines += ["", "## Machine", "", "| key | value |", "|---|---|"]
    lines += [f"| {key} | {value} |" for key, value in benchmark_report["machine"].items()]
    has_baseline = bool(benchmark_report.get("baseline")) and not benchmark_report.get("baseline_mismatch")
    for case in benchmark_report["cases"]:
        lines += ["", f"## {case['analysis']} · {case['channels']} ch · "
                      f"{os.path.basename(case['file'])}", "",
                  f"Status: `{case['status']}`" + (f" — {case['reason']}" if "reason" in case else ""), "",
                  "Settings: " + ", ".join(f"`{k}={v}`" for k, v in case["settings"].items())]
        if has_baseline and (case.get("baseline_matched") is False or (case.get("delta") is None and "baseline_matched" not in case)):
            lines += ["", "Comparison: only in this report (no matching baseline)"]
        if "summary" in case and case["summary"]:
            summary = case["summary"]
            first_ms = f"{summary['first_wall_s'] * 1000:.1f} ms" if summary.get("first_wall_s") is not None else "—"
            median_ms = f"{summary['median_wall_s'] * 1000:.1f} ms" if summary.get("median_wall_s") is not None else "—"
            timing_line = f"Timing: first {first_ms} · median {median_ms}"
            if case.get("delta") and case["delta"].get("wall_s") is not None:
                d_ms = case["delta"]["wall_s"] * 1000
                timing_line += f" · Δ {d_ms:+.1f} ms"
            lines += ["", timing_line]
        for number, run in enumerate(case.get("runs", []), start=1):
            lines += ["", f"Run {number}: {run['wall_s'] * 1000:.1f} ms", ""] + _step_table(run, case.get("delta"))

    if benchmark_report.get("baseline_only_cases"):
        lines += ["", "## Cases only in baseline", ""]
        for case in benchmark_report["baseline_only_cases"]:
            settings_str = ", ".join(f"`{k}={v}`" for k, v in case.get("settings", {}).items())
            lines.append(f"- {case['analysis']} · {case['channels']} ch · "
                         f"{os.path.basename(case['file'])} ({settings_str})")

    return "\n".join(lines) + "\n"


def _step_table(run: Dict[str, Any], delta: Optional[Dict[str, Any]] = None) -> List[str]:
    has_delta = delta is not None and delta.get("steps") is not None
    step_deltas = delta.get("steps", {}) if has_delta else {}
    if has_delta:
        rows = ["| step | wall ms | Δ | CPU ms | share | peak RAM MB |",
                "|---|---:|---:|---:|---:|---:|"]
    else:
        rows = ["| step | wall ms | CPU ms | share | peak RAM MB |",
                "|---|---:|---:|---:|---:|"]

    for step in run["steps"]:
        share = step["wall_s"] / run["wall_s"] if run["wall_s"] else 0.0
        ram = f"{step['peak_rss_mb']:.0f}" if step["peak_rss_mb"] is not None else "—"
        if has_delta:
            d_str = f"{step_deltas[step['name']] * 1000:+.1f} ms" if step["name"] in step_deltas else "—"
            rows.append(f"| {step['name']} | {step['wall_s'] * 1000:.1f} | {d_str} | "
                        f"{step['cpu_s'] * 1000:.1f} | {share:.0%} | {ram} |")
        else:
            rows.append(f"| {step['name']} | {step['wall_s'] * 1000:.1f} | {step['cpu_s'] * 1000:.1f} "
                        f"| {share:.0%} | {ram} |")
    if run["wall_s"] and sum(step["wall_s"] for step in run["steps"]) > run["wall_s"]:
        rows += ["", "Shares add up to more than 100 %: some steps run inside others "
                     "(`gui_wait` holds the computing, `repaint_window` the graph paints) "
                     "or on several threads at once."]
    return rows
