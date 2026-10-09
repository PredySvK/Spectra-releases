"""
Benchmark stopwatches: named steps that are timed only while a Benchmark records.

`benchmark_step(name)` wraps a piece of reading or computing. Outside a
Benchmark it is one global read and nothing is recorded (ADR §1.132), so the
stopwatches can stay in io_modules and signal_processing for good. Inside
`record_benchmark_steps(read_rss_mb)` every finished step is appended as a
`StepTiming`. Reading the process memory is the OS's business, so the caller
hands the reader in (io_modules.benchmark has one).
"""

import contextlib
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional

__all__ = ["StepTiming", "benchmark_step", "record_benchmark_steps", "discard_benchmark_recording"]

_SAMPLE_S = 0.005  # how often the process RAM is sampled while a Benchmark records


@dataclass(frozen=True)
class StepTiming:
    """One finished step. `cpu_s` is process CPU time (all threads), so
    cpu_s / wall_s above 1 means the step ran on several cores.
    `peak_rss_mb` is the highest resident memory of the process seen while the
    step ran (sampled every few ms, plus its start and end)."""
    name: str
    thread: str
    wall_s: float
    cpu_s: float
    peak_rss_mb: Optional[float]


_recording: Optional[List[StepTiming]] = None
_active_token: Optional[object] = None
_open_peaks: Dict[object, List[Optional[float]]] = {}  # running step -> [highest RSS seen]
_read_rss_mb: Callable[[], Optional[float]] = lambda: None
_lock = threading.Lock()


@contextlib.contextmanager
def benchmark_step(name: str) -> Iterator[None]:
    """Time the block as step `name` if a Benchmark is recording; else do nothing."""
    steps = _recording
    if steps is None:
        yield
        return
    token = _active_token
    key, peak = object(), [_read_rss_mb()]
    with _lock:
        _open_peaks[key] = peak
    wall_start, cpu_start = time.perf_counter(), time.process_time()
    try:
        yield
    finally:
        wall_s, cpu_s = time.perf_counter() - wall_start, time.process_time() - cpu_start
        end_rss = _read_rss_mb()
        with _lock:
            _open_peaks.pop(key, None)
            seen = [value for value in (peak[0], end_rss) if value is not None]
            step = StepTiming(name=name, thread=threading.current_thread().name, wall_s=wall_s,
                              cpu_s=cpu_s, peak_rss_mb=max(seen) if seen else None)
            if _recording is steps and _active_token is token:
                steps.append(step)


@contextlib.contextmanager
def record_benchmark_steps(read_rss_mb: Optional[Callable[[], Optional[float]]] = None
                           ) -> Iterator[List[StepTiming]]:
    """Record every step finished inside the block, from any thread.
    `read_rss_mb` gives the current process memory in MB; without it the RAM peak is None."""
    global _recording, _active_token, _read_rss_mb
    steps: List[StepTiming] = []
    token = object()
    with _lock:
        _recording = steps
        _active_token = token
        _read_rss_mb = read_rss_mb or (lambda: None)
    stop = threading.Event()
    sampler = threading.Thread(target=_sample_peaks, args=(stop,), name="benchmark-ram", daemon=True)
    sampler.start()
    try:
        yield steps
    finally:
        stop.set()
        sampler.join()
        with _lock:
            if _active_token is token:
                _recording = None
                _active_token = None


def discard_benchmark_recording() -> None:
    """Invalidate any active recording session (e.g. on per-case timeout)."""
    global _recording, _active_token
    with _lock:
        _recording = None
        _active_token = None


def _sample_peaks(stop: threading.Event) -> None:
    while not stop.wait(_SAMPLE_S):
        rss = _read_rss_mb()
        if rss is None:
            return
        with _lock:
            for peak in _open_peaks.values():
                if peak[0] is None or rss > peak[0]:
                    peak[0] = rss
