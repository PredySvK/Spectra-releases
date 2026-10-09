"""
Benchmark files, reference signal, and machine facts (ADR §1.132).

`read_benchmark_plan` loads a TOML plan, `read_machine_info` collects the
`machine` section of the Benchmark report from the stdlib only (and
`read_process_rss_mb` the process memory the stopwatches sample), and
`write_benchmark_report` writes the report as JSON and renders the Markdown
from that JSON. `resolve_reference_signal` provides the deterministic
multi-channel reference signal input.
"""

from ._machine import read_machine_info, read_process_rss_mb
from ._plan import DEFAULT_PLAN_PATH, BenchmarkPlan, read_benchmark_plan, write_benchmark_plan
from ._reference import resolve_reference_path, resolve_reference_signal
from ._report import build_benchmark_markdown, read_benchmark_report, write_benchmark_report

__all__ = [
    "BenchmarkPlan",
    "DEFAULT_PLAN_PATH",
    "build_benchmark_markdown",
    "read_benchmark_plan",
    "read_benchmark_report",
    "read_machine_info",
    "read_process_rss_mb",
    "resolve_reference_path",
    "resolve_reference_signal",
    "write_benchmark_plan",
    "write_benchmark_report",
]

