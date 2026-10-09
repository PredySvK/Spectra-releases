"""
Full Benchmark (ADR §1.132): time the real click path up to paint.

`main.py --benchmark` builds a `BenchmarkApplication` -- a QApplication that
times graph paints and main-window repaints as Benchmark steps -- and hands
the window over to `run_full_benchmark`, which runs every Benchmark case of
the plan in this separate process with isolated QSettings and an empty
project, writes the Benchmark report and ends the process.
"""

from ._application import BenchmarkApplication
from ._dialog import BenchmarkDialog
from ._full import run_full_benchmark

__all__ = ["BenchmarkDialog", "BenchmarkApplication", "run_full_benchmark"]
