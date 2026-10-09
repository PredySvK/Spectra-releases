"""The display settings a graph is built and rebuilt in, as one value."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.units import UnitPreferences


@dataclass(frozen=True)
class DisplaySettings:
    """How a graph shows its curves: unit preferences, a spectrum's Format /
    Amplitude / dB, and the RMS/Peak amplitude of an order cut or an Overall
    Level (the dock's own View/Amplitude, ADR §1.62 point 22). The one place
    these defaults live."""

    prefs: UnitPreferences = field(default_factory=UnitPreferences)
    spectrum_format: str = "linear"
    spectrum_amplitude_mode: str = "rms"
    decibel_scale: bool = False
    amplitude_mode: str = "rms"
