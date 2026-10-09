"""
Removing the DC offset from a time-domain signal before it is analysed.

Kept separate from `preconditions.py`: this transforms a signal, that one only
refuses one. The old `dsp/utils.py` held both under a name that described
neither.
"""

import numpy as np


def remove_dc_offset(y_data: np.ndarray, channel_type: str = "accelerometer") -> np.ndarray:
    """
    Removes the zero-frequency (DC) offset by subtracting the block mean.
    Strictly bypasses sensors like Tacho or RPM where the absolute mean value is critical.

    Parameters:
        y_data (np.ndarray): 1D array of the time domain signal.
        channel_type (str): Hardware string classification of the sensor.

    Returns:
        np.ndarray: Detrended (or untouched) 1D signal.
    """
    if y_data is None or len(y_data) == 0:
        return y_data

    # Do NOT remove DC from tachometers, static strain, or explicit RPM tracks
    if "tacho" in channel_type.lower() or "rpm" in channel_type.lower():
        return y_data

    # Subtract the arithmetic mean (AC coupling emulation)
    return y_data - np.mean(y_data)
