# =====================================================================
# FILE: io_modules/signal_generation/signal_generation_engine.py
# =====================================================================
"""
Core mathematical domain module for synthetic NVH signal generation.
Computes waveforms, integrations, dynamic mechanical resonance envelopes,
and complex RPM profiles (Ramp Up/Down, Plateaus).
All internal documentation strings and variable labels are written in English.
"""

from typing import Optional

import numpy as np


def generate_time_vector(duration: float, fs: float) -> np.ndarray:
    """Generates the primary 1D time array vector."""
    return np.arange(int(duration * fs)) / fs


def _generate_base_profile(t_norm: np.ndarray, start: float, stop: float,
                           plateaus_on: bool, steps: int, p_ratio: float) -> np.ndarray:
    """Internal helper to generate a normalized ramp segment with or without plateaus."""
    if not plateaus_on or steps < 1 or p_ratio <= 0.0:
        # Pure linear interpolation
        return start + (stop - start) * t_norm

    y = np.zeros_like(t_norm)
    segment_length = 1.0 / steps
    levels = np.linspace(start, stop, steps + 1)

    for i in range(steps):
        t0 = i * segment_length
        # Ensure the final sample belongs to the last plateau despite rounding.
        t1 = 1.0 if i == steps - 1 else (i + 1) * segment_length

        ramp_duration = segment_length * (1.0 - p_ratio)
        t_ramp_end = t0 + ramp_duration

        # Mask for the ramp portion
        mask_ramp = (t_norm >= t0) & (t_norm < t_ramp_end)
        if ramp_duration > 0:
            y[mask_ramp] = levels[i] + (levels[i + 1] - levels[i]) * ((t_norm[mask_ramp] - t0) / ramp_duration)
        else:
            y[mask_ramp] = levels[i + 1]

        # Mask for the plateau holding portion
        mask_hold = (t_norm >= t_ramp_end) & (t_norm <= t1)
        y[mask_hold] = levels[i + 1]

    return y


def generate_rpm_profile(t: np.ndarray, rpm_start: float, rpm_stop: float,
                         direction: str, plateaus_on: bool, steps: int, p_ratio: float) -> np.ndarray:
    """Calculates instantaneous rotational speeds dynamically with step and direction support."""
    if len(t) < 2:
        return np.full_like(t, rpm_start)

    if direction == "Ramp Up":
        t_norm = (t - t[0]) / (t[-1] - t[0])
        return _generate_base_profile(t_norm, rpm_start, rpm_stop, plateaus_on, steps, p_ratio)

    elif direction == "Ramp Down":
        t_norm = (t - t[0]) / (t[-1] - t[0])
        return _generate_base_profile(t_norm, rpm_stop, rpm_start, plateaus_on, steps, p_ratio)

    elif direction == "Ramp Up & Down":
        mid_idx = len(t) // 2
        # Split time array into two halves
        t_up = (t[:mid_idx] - t[0]) / (t[mid_idx - 1] - t[0]) if mid_idx > 1 else np.array([0.0])
        t_down = (t[mid_idx:] - t[mid_idx]) / (t[-1] - t[mid_idx]) if len(t) - mid_idx > 1 else np.array([0.0])

        y_up = _generate_base_profile(t_up, rpm_start, rpm_stop, plateaus_on, steps, p_ratio)
        y_down = _generate_base_profile(t_down, rpm_stop, rpm_start, plateaus_on, steps, p_ratio)
        return np.concatenate([y_up, y_down])

    return np.full_like(t, rpm_start)


def generate_tacho_pulse(rpm_profile: np.ndarray, dt: float, pulses_per_rev: int = 1):
    """
    Integrates the RPM profile into accumulated shaft angle.

    Trapezoidal, and starting at exactly zero. The previous
    `np.cumsum(omega * dt)` was a right-endpoint rectangle sum, which put
    `omega[0] * dt` into phase[0] instead of 0 and left a phase lead of
    `dt * (omega[0] + omega[i]) / 2` -- for a linear ramp that grows with speed
    and, because compose_vibration_signal multiplies phase by the order number,
    scales with order too (~44 deg at order 24 by the end of the reference
    run-up). The trapezoid rule is exact for a linear ramp, which is the profile
    this generator actually produces, so the error goes to zero rather than
    merely getting smaller.

    Nothing measurable by this tool changed: order amplitudes do not depend on
    phase, the implied frequency error was ~0.0002 Hz, every channel shares this
    one array so inter-channel phase was always exact, and the analysis side
    never integrates RPM into angle at all.
    """
    if len(rpm_profile) == 0:
        return np.zeros(0), np.zeros(0)

    omega = rpm_profile / 60.0 * 2.0 * np.pi
    increments = 0.5 * (omega[:-1] + omega[1:]) * dt
    phase = np.concatenate(([0.0], np.cumsum(increments)))

    pulse = np.sin(phase * pulses_per_rev)
    return phase, pulse


def _colored_noise(rng: np.random.Generator, n: int, dt: float, amp: float,
                   exponent: float) -> np.ndarray:
    """
    Gaussian noise shaped to a 1/f**exponent power spectrum, rescaled so its
    standard deviation is `amp`.

    exponent == 1 is pink (equal energy per octave), exponent == 2 is brown /
    red. Real NVH background is closer to pink than to the flat White Noise
    component, which is the only reason this exists.
    """
    white = rng.normal(0.0, 1.0, n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, d=dt)
    scale = np.ones_like(freqs)
    nonzero = freqs > 0
    scale[nonzero] = freqs[nonzero] ** (-exponent / 2.0)
    shaped = np.fft.irfft(spectrum * scale, n=n)
    std = float(np.std(shaped))
    if std > 0:
        shaped *= amp / std
    return shaped


def _resonance_noise(rng: np.random.Generator, n: int, dt: float, amp: float,
                     fn: float, q: float) -> np.ndarray:
    """
    White noise passed through an SDOF magnitude response centred at `fn`,
    rescaled so its standard deviation is `amp`.

    Unlike the resonance envelope applied to an Order, this is a fixed spectral
    bump that does NOT move with speed -- it is how a structural mode that is
    excited broadband (not by one order sweeping through it) is planted.
    """
    white = rng.normal(0.0, 1.0, n)
    spectrum = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, d=dt)
    zeta = 1.0 / (2.0 * max(q, 1e-6))
    ratio = freqs / fn
    magnitude = 1.0 / np.sqrt((1.0 - ratio ** 2) ** 2 + (2.0 * zeta * ratio) ** 2)
    shaped = np.fft.irfft(spectrum * magnitude, n=n)
    std = float(np.std(shaped))
    if std > 0:
        shaped *= amp / std
    return shaped


def _stochastic_component(ctype: str, rng: np.random.Generator, n: int, dt: float,
                          amp: float, res_freq: float, res_amp: float) -> Optional[np.ndarray]:
    """
    The waveform for one speed-independent noise component (White / Pink / Brown
    / Resonance), or None when `ctype` is a tonal component (Order / Sine) that
    the caller synthesizes itself.

    Split out of compose_vibration_signal so its linear if/continue chain of
    stochastic types stops sharing a body with the tonal envelope/modulation
    logic (audit 02, S11).
    """
    if ctype == "White Noise":
        return rng.normal(0.0, amp, n)
    if ctype == "Pink Noise":
        return _colored_noise(rng, n, dt, amp, 1.0)
    if ctype == "Brown Noise":
        return _colored_noise(rng, n, dt, amp, 2.0)
    if ctype == "Resonance":
        if res_freq > 0:
            return _resonance_noise(rng, n, dt, amp, res_freq, max(res_amp, 1.0))
        return np.zeros(n)
    return None


def compose_vibration_signal(t: np.ndarray, phase_rad: np.ndarray, components: list,
                             rpm_profile: np.ndarray,
                             rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """
    Synthesizes the core physical vibration waveform.

    `rng` draws every stochastic component (White / Pink / Brown Noise,
    Resonance). Pass a seeded generator to make the record reproducible: a
    synthetic file is this project's reference etalon (see
    tools/make_reference_signal.py), and an etalon that cannot be regenerated
    from its parameters is not an etalon. Passing one generator across several
    channels also keeps their noise independent, which sharing a seed per
    channel would not.

    Optional per-component keys beyond type/value/amplitude/res_freq/res_amp:
      amp_end    -- linear amplitude drift from `amplitude` to `amp_end` across
                    the record (a warm-up rise; this is how a first-order
                    unbalance actually behaves during a run).
      Chirp      -- `value` = start Hz, `res_freq` = end Hz (linear sweep over the
                    whole record; the resonance envelope does not apply to it).
      mod_order  -- amplitude-modulate the component at this order (Order) or
      mod_depth     this frequency in Hz (Sine), depth 0..1. Produces sidebands
                    at value +/- mod_order, the signature of a bearing fault.
    """
    if rng is None:
        rng = np.random.default_rng()

    dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
    vib = np.zeros_like(t)

    for comp in components:
        ctype = comp["type"]
        cval = comp["value"]
        amp = comp["amplitude"]
        amp_end = comp.get("amp_end", amp)
        res_freq = comp.get("res_freq", 0.0)
        res_amp = comp.get("res_amp", 0.0)
        mod_order = comp.get("mod_order", 0.0)
        mod_depth = comp.get("mod_depth", 0.0)

        stochastic = _stochastic_component(ctype, rng, len(t), dt, amp, res_freq, res_amp)
        if stochastic is not None:
            vib += stochastic
            continue

        if ctype == "Order":
            f_inst = cval * (rpm_profile / 60.0)
            current_phase = phase_rad * cval
        elif ctype == "Sine signal":
            f_inst = np.full_like(t, cval)
            current_phase = 2 * np.pi * cval * t
        elif ctype == "Chirp":
            # Linear sweep cval -> res_freq Hz across the record (fixed in time,
            # not tied to rpm): phase = 2*pi*(f0*t + (f1-f0)*t^2 / (2*T)).
            t_rel = t - t[0]
            span = t_rel[-1] if len(t) > 1 else 1.0
            current_phase = 2 * np.pi * (cval * t_rel + (res_freq - cval) * t_rel ** 2 / (2.0 * span))
        else:
            # A typo in the component "Type" cell used to be skipped silently,
            # leaving the whole channel at zero while the summary reported
            # success -- and this code path builds the reference etalon. Reject
            # it, the same way the DSP layer rejects an unknown mode string
            # (audit 02, S11/11.5; F7-A / normalize_dsp_choice).
            raise ValueError(f"unknown component type {ctype!r}")

        # Linear amplitude envelope across the record (warm-up drift).
        if amp_end != amp and len(t) > 1:
            env = np.linspace(amp, amp_end, len(t))
        else:
            env = np.full_like(t, amp)

        # Dynamic resonance envelope (SDOF) ONLY for tracking orders sweeping through fn.
        if ctype == "Order" and res_freq > 0 and res_amp > 1.0:
            zeta = 1.0 / (2.0 * res_amp)
            freq_ratio = f_inst / res_freq
            magnification = 1.0 / np.sqrt((1.0 - freq_ratio ** 2) ** 2 + (2.0 * zeta * freq_ratio) ** 2)
            env = env * magnification

        # Amplitude modulation -> sidebands at value +/- mod_order.
        if mod_order > 0 and mod_depth > 0:
            if ctype == "Order":
                modulator = 1.0 + mod_depth * np.sin(phase_rad * mod_order)
            else:
                modulator = 1.0 + mod_depth * np.sin(2 * np.pi * mod_order * t)
            env = env * modulator

        vib += env * np.sin(current_phase)

    return vib


def apply_tacho_noise(rpm_profile: np.ndarray, rng: np.random.Generator,
                      std_rpm: float = 0.0, region: str = "all", region_frac: float = 1.0,
                      dropout_rate: float = 0.0, dropout_gain: float = 0.5) -> np.ndarray:
    """
    Adds acquisition noise to an ideal RPM profile, returning the trace an
    instrument would have recorded rather than the analytic ramp.

    A real tacho derives speed from pulse timing, so its RPM channel is never as
    clean as the profile this generator produces. `std_rpm` is broadband
    Gaussian jitter; `region` ("all" / "start" / "end") limits it to a fraction
    `region_frac` of the record -- a loose probe or a trigger threshold that
    only misbehaves at low speed. `dropout_rate` is the per-sample probability
    of a missed pulse, which scales the reported speed by `dropout_gain` at that
    sample: the single-sample glitches an order tracker has to ride out.

    The vibration is still synthesized from the clean profile -- only the tacho
    *channel* written to file is degraded, which is exactly the situation this
    lets a test reproduce. Deterministic for a given `rng`; clipped at zero.
    """
    n = len(rpm_profile)
    if n == 0:
        return np.array(rpm_profile, dtype=np.float64)

    out = np.array(rpm_profile, dtype=np.float64)

    mask = np.zeros(n, dtype=bool)
    k = int(np.clip(region_frac, 0.0, 1.0) * n)
    if region == "start":
        mask[:k] = True
    elif region == "end":
        mask[n - k:] = True
    else:
        mask[:] = True

    if std_rpm > 0:
        out[mask] += rng.normal(0.0, std_rpm, int(mask.sum()))

    if dropout_rate > 0:
        hit = rng.random(n) < dropout_rate
        out[hit] *= dropout_gain

    return np.clip(out, 0.0, None)





