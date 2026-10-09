"""Deterministic reference signal generator and cache for Benchmark (ADR §1.132, #482)."""

import hashlib
import json
import os
import tempfile
from typing import Any, Dict, Optional

REFERENCE_FS_HZ = 25600.0
REFERENCE_DURATION_S = 75.0
REFERENCE_RPM_START = 600.0
REFERENCE_RPM_STOP = 12000.0
REFERENCE_SEED = 20261004


def build_reference_params(duration: float = REFERENCE_DURATION_S,
                           seed: int = REFERENCE_SEED) -> Dict[str, Any]:
    """Build parameters for the 16-channel + tacho benchmark reference signal."""
    channels = []
    for i in range(16):
        unit = "g" if i < 8 else "Pa"
        components = [
            {"type": "Order", "value": 1.0, "amplitude": 0.2 + 0.02 * (i % 4)},
            {"type": "Order", "value": 2.0, "amplitude": 0.1},
            {"type": "Order", "value": 3.0, "amplitude": 0.05},
            {"type": "Sine signal", "value": 1000.0, "amplitude": 0.05},
            {"type": "Pink Noise", "value": 0.0, "amplitude": 0.01},
        ]
        channels.append({
            "name": f"Channel_{i + 1}",
            "unit": unit,
            "components": components,
        })

    return {
        "fs": REFERENCE_FS_HZ,
        "duration": duration,
        "rpm_start": REFERENCE_RPM_START,
        "rpm_stop": REFERENCE_RPM_STOP,
        "direction": "Ramp Up",
        "plateaus_on": False,
        "plateaus": 0,
        "plateau_ratio": 0.0,
        "seed": seed,
        "channels": channels,
        "tacho_noise": None,
    }


def resolve_reference_path(directory: Optional[str] = None,
                           duration: float = REFERENCE_DURATION_S,
                           seed: int = REFERENCE_SEED) -> str:
    """Return the filesystem path where the reference signal lives, without disk I/O.

    The name carries a fingerprint of the generator parameters, so a changed
    preset or seed gets a new file instead of reusing a stale one."""
    params = json.dumps(build_reference_params(duration=duration, seed=seed), sort_keys=True)
    fingerprint = hashlib.sha256(params.encode("utf-8")).hexdigest()[:8]
    target_dir = tempfile.gettempdir() if directory is None else directory
    return os.path.join(target_dir, f"benchmark_reference_{duration:g}s_16ch_{fingerprint}.asc")


def write_reference_signal(export_path: str,
                           duration: float = REFERENCE_DURATION_S,
                           seed: int = REFERENCE_SEED) -> str:
    """Generate and write the reference signal to export_path using the existing generator."""
    from io_modules.signal_generation import generate_and_export_synthetic

    params = build_reference_params(duration=duration, seed=seed)
    summary = generate_and_export_synthetic(params, export_path)
    return summary["path"]


def _is_valid_reference_file(path: str,
                             duration: float = REFERENCE_DURATION_S,
                             channels_count: int = 16) -> bool:
    """True if path exists, has valid headers and is complete up to duration."""
    if not os.path.isfile(path):
        return False
    size = os.path.getsize(path)
    if size < 1000:
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            header_lines = []
            for _ in range(25):
                line = handle.readline()
                if not line:
                    break
                header_lines.append(line.strip())
                if line.strip() == "END":
                    break

            if "BEGIN" not in header_lines or "END" not in header_lines:
                return False

            expected_delta = f"DELTA = {1.0 / REFERENCE_FS_HZ:.12f}"
            if not any(l == expected_delta for l in header_lines):
                return False

            ch_line = next((l for l in header_lines if l.startswith("CHANNELNAME = ")), None)
            if not ch_line or "Tacho_Master" not in ch_line:
                return False

            handle.seek(max(0, size - 2048))
            tail = handle.read()
            tail_lines = [l.strip() for l in tail.splitlines() if l.strip()]
            if not tail_lines:
                return False
            last_line = tail_lines[-1]
            parts = [p.strip() for p in last_line.split(",")]
            if len(parts) != channels_count + 2:
                return False
            last_time = float(parts[0])
            expected_last_time = duration - (1.0 / REFERENCE_FS_HZ)
            if abs(last_time - expected_last_time) > 0.01:
                return False
        return True
    except Exception:
        return False


def resolve_reference_signal(directory: Optional[str] = None,
                             duration: float = REFERENCE_DURATION_S,
                             seed: int = REFERENCE_SEED) -> str:
    """Return path to valid reference signal, generating it if absent or incomplete."""
    target_path = resolve_reference_path(directory, duration=duration, seed=seed)
    if _is_valid_reference_file(target_path, duration=duration):
        return target_path

    return write_reference_signal(target_path, duration=duration, seed=seed)
