"""
Headless Benchmark (ADR §1.132): time a plan's analyses without Qt and write
the Benchmark report as JSON + Markdown.

    python benchmark.py plan.toml [--out DIR] [--quick] [--baseline BASELINE]

Kept apart from main.py, which imports PySide6 on its first lines; this entry
must never load Qt so it runs on a server without a display.
"""

import argparse
import dataclasses
import os
import sys

from core.asset_paths import perf_report_dir
from io_modules.benchmark import DEFAULT_PLAN_PATH, read_benchmark_plan, write_benchmark_report
from orchestration.benchmark import run_benchmark

DEFAULT_OUT_DIR = perf_report_dir()


def redirect_output(log_path) -> None:
    """Send stdout and stderr to `log_path`; a frozen build without a console has neither."""
    if log_path:
        sys.stdout = sys.stderr = open(log_path, "w", buffering=1, encoding="utf-8")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("plan", nargs="?", default=DEFAULT_PLAN_PATH, help="Benchmark plan (TOML)")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR, help="folder for the Benchmark report")
    parser.add_argument("--quick", action="store_true", help="one run per case")
    parser.add_argument("--baseline", help="path to baseline Benchmark report (JSON)")
    parser.add_argument("--log", help="file that receives the output instead of stdout")
    args = parser.parse_args(argv)
    redirect_output(args.log)

    plan = read_benchmark_plan(args.plan)
    if args.quick:
        plan = dataclasses.replace(plan, quick=True)
    report = run_benchmark(plan, baseline=args.baseline,
                           on_case_done=lambda done, total: print(f"PROGRESS {done}/{total}", flush=True))
    json_path, md_path = write_benchmark_report(report, args.out)
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
