"""The display settings a graph is built and rebuilt in, as one value."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.dsp_configs import OrderTrackingConfig, OverallLevelConfig, SpectrogramConfig, SpectrumConfig
from core.units import UnitPreferences
from view_models.analysis_kinds import ANALYSIS_ORDERS, ANALYSIS_SPECTROGRAM


@dataclass(frozen=True)
class DisplaySettings:
    """How a graph shows its curves: unit preferences, a spectrum's Format /
    Amplitude / dB, the colour scale of a spectrogram, and the RMS/Peak
    amplitude of an order cut or an Overall Level (the dock's own
    View/Amplitude, ADR §1.62 point 22). The one place these defaults live.

    On a spectrogram dock ``spectrum_format`` / ``spectrum_amplitude_mode`` are
    the spectrogram tab's own Format and Amplitude."""

    prefs: UnitPreferences = field(default_factory=UnitPreferences)
    spectrum_format: str = "linear"
    spectrum_amplitude_mode: str = "rms"
    decibel_scale: bool = False
    amplitude_mode: str = "rms"
    color_scale: str = "Linear"


def resolve_display_settings(
    analysis_kind: str,
    *,
    prefs: UnitPreferences,
    spectrum: Optional[SpectrumConfig] = None,
    spectrogram: Optional[SpectrogramConfig] = None,
    order_tracking: Optional[OrderTrackingConfig] = None,
    overall_level: Optional[OverallLevelConfig] = None,
) -> DisplaySettings:
    """The settings a dock of ``analysis_kind`` is shown in, read from the
    ribbon tabs' configs (#833). A config that is not there leaves the
    DisplaySettings default.

    The RMS/Peak of an order cut or an Overall Level is the dock's own
    View/Amplitude, keyed on the dock's kind -- so an
    order cut dropped onto an Overall Level dock (or the reverse, issue #128)
    picks up whatever RMS/Peak that dock is already showing."""
    d = DisplaySettings()
    amplitude_source = order_tracking if analysis_kind == ANALYSIS_ORDERS else overall_level
    if analysis_kind == ANALYSIS_SPECTROGRAM:
        return DisplaySettings(
            prefs=prefs,
            spectrum_format=spectrogram.spectrum_format if spectrogram else d.spectrum_format,
            spectrum_amplitude_mode=(spectrogram.amplitude_mode if spectrogram
                                     else d.spectrum_amplitude_mode),
            color_scale=spectrogram.color_scale if spectrogram else d.color_scale,
        )
    return DisplaySettings(
        prefs=prefs,
        spectrum_format=spectrum.spectrum_format if spectrum else d.spectrum_format,
        spectrum_amplitude_mode=spectrum.amplitude_mode if spectrum else d.spectrum_amplitude_mode,
        decibel_scale=spectrum.decibel_scale if spectrum else d.decibel_scale,
        amplitude_mode=amplitude_source.amplitude_mode if amplitude_source else d.amplitude_mode,
    )
