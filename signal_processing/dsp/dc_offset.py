"""
Removing the DC offset from a time-domain signal before it is analysed.

Kept separate from `preconditions.py`: this transforms a signal, that one only
refuses one. The old `dsp/utils.py` held both under a name that described
neither.
"""

import numpy as np

from core.channel_types import CHANNEL_TYPE_ACCELEROMETER, CHANNEL_TYPE_TACHO


def remove_dc_offset(y_data: np.ndarray, channel_type: str = CHANNEL_TYPE_ACCELEROMETER) -> np.ndarray:
    """
    Removes the zero-frequency (DC) offset by subtracting the block mean.
    Strictly bypasses sensors like Tacho or RPM where the absolute mean value is critical.
    The mean is taken over the finite samples only: one invalid (NaN) sample
    must not turn every other sample into NaN (#673).

    Parameters:
        y_data (np.ndarray): 1D array of the time domain signal.
        channel_type (str): Hardware string classification of the sensor.

    Returns:
        np.ndarray: Detrended (or untouched) 1D signal.
    """
    if y_data is None or len(y_data) == 0:
        return y_data

    # Do NOT remove DC from tachometers, static strain, or explicit RPM tracks
    if CHANNEL_TYPE_TACHO in channel_type.lower() or "rpm" in channel_type.lower():
        return y_data

    # Subtract the arithmetic mean (AC coupling emulation)
    finite = np.isfinite(y_data)
    if finite.all():
        return y_data - np.mean(y_data)
    if not finite.any():
        return y_data
    return y_data - np.mean(y_data[finite])
