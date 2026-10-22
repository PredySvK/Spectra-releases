"""
Live preview array computation for the synthetic signal generator.

Pure, deterministic numerical calculation that builds sliced time, RPM, and
vibration arrays for interactive UI plotting without disk I/O or Qt dependencies.
"""

import numpy as np

from io_modules.signal_generation._signal_generation_engine import (
    compose_vibration_signal,
    generate_rpm_profile,
    generate_tacho_pulse,
    generate_time_vector,
)

PREVIEW_NOISE_SEED = 0
# Grid the RPM profile is sampled on to read the speed at one instant: the profile
# shape (ramps, plateaus, direction) is only defined over the whole record.
_START_RPM_GRID_POINTS = 1000


def compute_preview_arrays(params: dict, active_components: list) -> dict:
    """
    Builds the RPM profile and (if the active channel has components) the vibration
    waveform, then returns only the slice the preview window asks for.

    Pure numerical work designed to run on a background worker thread. Uses a
    fixed preview noise seed (0) so the preview does not jitter across redraws.
    No Qt, no I/O.
    """
    fs = params["fs"]
    duration = params["duration"]

    prev_start = max(0.0, min(params["prev_start"], duration - 0.001))
    prev_end = max(prev_start + 0.001, min(params["prev_end"], duration))
    idx_start = int(prev_start * fs)
    idx_end = int(prev_end * fs)

    t = generate_time_vector(duration, fs)
    rpm = generate_rpm_profile(
        t, params["rpm_start"], params["rpm_stop"],
        params["direction"], params["plateaus_on"],
        params["plateaus"], params["plateau_ratio"],
    )

    result = {
        "x_axis_mode": params["x_axis_mode"],
        "t": t[idx_start:idx_end],
        "rpm": rpm[idx_start:idx_end],
        "vib": None,
    }

    if active_components:
        phase_rad, _ = generate_tacho_pulse(rpm, 1.0 / fs, 1)
        # Fixed seed: the preview redraws on every keystroke (300 ms debounce),
        # and unseeded noise made the curve jitter between redraws even when
        # nothing was edited. The preview only has to look like the record, so
        # a constant seed here is unrelated to the exported file's seed.
        vib = compose_vibration_signal(
            t, phase_rad, active_components, rpm,
            rng=np.random.default_rng(PREVIEW_NOISE_SEED),
        )
        result["vib"] = vib[idx_start:idx_end]

    return result


def compute_preview_start_rpm(params: dict, start_time: float) -> float:
    """
    The RPM of the generated profile at `start_time`, whatever its shape
    (ramp direction, plateaus). Sampled on a coarse grid over the whole
    duration and interpolated. No Qt, no I/O.
    """
    t = np.linspace(0, params["duration"], _START_RPM_GRID_POINTS)
    rpm = generate_rpm_profile(
        t, params["rpm_start"], params["rpm_stop"],
        params["direction"], params["plateaus_on"],
        params["plateaus"], params["plateau_ratio"],
    )
    return float(np.interp(start_time, t, rpm))
