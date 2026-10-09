"""
Benchmark (ADR §1.132): time every Benchmark case of a plan.

Qt-free -- `benchmark.py` drives it headless; `gui.benchmark` (Full variant) reuses
the case plan and the report builders. `run_benchmark` times each case
with the core stopwatches and returns the Benchmark report as a plain dict;
reading the plan and writing the report live in `io_modules.benchmark`.
`resolve_benchmark_files` resolves input file paths including generated signals.
"""

from ._command import build_benchmark_command
from ._delta import resolve_benchmark_delta
from ._run import (build_benchmark_report, build_benchmark_run, plan_benchmark_cases,
                   resolve_benchmark_channels, resolve_benchmark_config, resolve_benchmark_files,
                   resolve_benchmark_runs_per_case, resolve_benchmark_skip, run_benchmark)

__all__ = [
    "build_benchmark_command",
    "build_benchmark_report",
    "build_benchmark_run",
    "plan_benchmark_cases",
    "resolve_benchmark_channels",
    "resolve_benchmark_config",
    "resolve_benchmark_delta",
    "resolve_benchmark_files",
    "resolve_benchmark_runs_per_case",
    "resolve_benchmark_skip",
    "run_benchmark",
]


