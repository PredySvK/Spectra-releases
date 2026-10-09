"""The command line that runs a Benchmark plan in its own process."""

import os
import sys
from typing import List, Optional


def build_benchmark_command(python: str, root: str, plan_path: str, out_dir: str, *,
                            full: bool, quick: bool = False, baseline: Optional[str] = None,
                            log_path: Optional[str] = None) -> List[str]:
    """`benchmark.py` for Headless, `main.py --benchmark` for Full (ADR §1.132).

    A frozen build has no scripts to hand to `python`: it runs itself
    (`Spectra.exe --benchmark[-headless]`), and, having no console, reports
    through the `log_path` file instead of stdout."""
    if getattr(sys, "frozen", False):
        command = [python, "--benchmark" if full else "--benchmark-headless", plan_path]
    elif full:
        command = [python, os.path.join(root, "main.py"), "--benchmark", plan_path]
    else:
        command = [python, os.path.join(root, "benchmark.py"), plan_path]
    command += ["--out", out_dir]
    if quick:
        command.append("--quick")
    if baseline:
        command += ["--baseline", baseline]
    if log_path:
        command += ["--log", log_path]
    return command
