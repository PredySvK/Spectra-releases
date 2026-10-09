"""The Benchmark plan: what to time, read from a TOML file."""

import json
import os
import tomllib
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Union

from core.asset_paths import resource_path
from core.block_kinds import KIND_ORDER_CUT, KIND_OVERALL_LEVEL, KIND_SPECTROGRAM, KIND_SPECTRUM

DEFAULT_PLAN_PATH = resource_path("benchmark_plan.toml")


@dataclass(frozen=True)
class BenchmarkPlan:
    files: List[str] = field(default_factory=list)
    generated: bool = False
    analyses: List[str] = field(default_factory=lambda: [
        KIND_SPECTRUM, KIND_SPECTROGRAM, KIND_ORDER_CUT, KIND_OVERALL_LEVEL])
    channels: List[Union[int, str]] = field(default_factory=lambda: [1, "all"])
    # Plan keys (nfft, rpm_step) over the program defaults; each
    # analysis takes only the ones its config has.
    base: Dict[str, Any] = field(default_factory=dict)
    sweep: Dict[str, List[Any]] = field(default_factory=dict)
    mode: str = "sweep"
    repeats: int = 3
    quick: bool = False
    timeout_s: float = 600.0

    def __post_init__(self):
        if self.mode not in ("sweep", "product"):
            raise ValueError(f"Unknown Benchmark plan mode: {self.mode!r}; expected 'sweep' or 'product'")


def read_benchmark_plan(path: str) -> BenchmarkPlan:
    with open(path, "rb") as handle:
        raw = tomllib.load(handle)
    unknown = raw.keys() - BenchmarkPlan.__dataclass_fields__.keys()
    if unknown:
        raise ValueError(f"Unknown Benchmark plan keys: {sorted(unknown)}")
    if "timeout_s" in raw:
        raw["timeout_s"] = float(raw["timeout_s"])
    return BenchmarkPlan(**raw)



def write_benchmark_plan(plan: BenchmarkPlan, path: str) -> None:
    """Write `plan` as TOML that `read_benchmark_plan` reads back."""
    scalars, tables = [], []
    for item in fields(plan):
        value = getattr(plan, item.name)
        if isinstance(value, dict):
            if value:
                tables.append(f"[{item.name}]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in value.items()))
        else:
            scalars.append(f"{item.name} = {json.dumps(value)}\n")  # JSON literals are valid TOML here
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("".join(scalars) + "\n" + "\n".join(tables))
