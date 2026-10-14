# =====================================================================
# FILE: core/source_amplitude.py
# =====================================================================
"""
Source amplitude: what the amplitude in an Imported result file means.

A MASTA workbook, a processed measurement or an ANSYS response arrives as a
ready-made amplitude and the file does not say whether it is RMS or Peak. The
user states it once when the file is added to the Data Pool; the program then
converts to RMS exactly once, when the channel is read, so every Imported result
is RMS like a computed order cut and the Peak/RMS display switch works as before.
This module is that single conversion -- not the Amplitude mode, which is how a
curve is displayed.
"""

import math

SOURCE_AMPLITUDE_RMS = "rms"
SOURCE_AMPLITUDE_PEAK = "peak"
VALID_SOURCE_AMPLITUDES = (SOURCE_AMPLITUDE_RMS, SOURCE_AMPLITUDE_PEAK)


def resolve_rms_factor(source_amplitude: str) -> float:
    """The factor that turns a file's amplitude into RMS: RMS = Peak / sqrt(2)."""
    if source_amplitude == SOURCE_AMPLITUDE_RMS:
        return 1.0
    if source_amplitude == SOURCE_AMPLITUDE_PEAK:
        return 1.0 / math.sqrt(2.0)
    raise ValueError(
        f"Unknown source amplitude {source_amplitude!r}; expected one of {VALID_SOURCE_AMPLITUDES}.")
