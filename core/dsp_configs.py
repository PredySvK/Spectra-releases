# =====================================================================
# FILE: core/dsp_configs.py
# =====================================================================
"""
Data Transfer Objects (DTO) bridging the GUI Ribbon panels with the DSP core.
Isolates the mathematical computation engines from PySide6 UI components.
All internal documentation strings and variable labels are standardly written in English.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Optional

# Numeric algorithm version per result kind. io_modules.result_cache folds a
# kind's version into every saved result set's params, so a stale result computed
# by older math is never mistaken for a valid cache hit just because the
# FFT/tracking settings look the same. Bump a kind's entry whenever a change to
# that kind's DSP alters the numeric output for the same inputs (not for a
# docstring or refactor). Lives here in core/ so both the DSP layer and the cache
# I/O layer can read it without depending on each other.
#
# spectrum/spectrogram/time_response start at 2, not 1: identity_params()
# historically stamped every version-less node with the order-tracking version
# (== 2), so that is the value already baked into every saved spectral set's
# params_hash. Renumbering to 1 would turn all of them into cache misses for no
# benefit -- the point of decoupling them here is only that a future bump to one
# kind stops silently invalidating the others (audit 02 / 1.7, ADR §1.16, §1.21).
# A kind added after that has no saved params_hash to stay compatible with, so it
# starts at 1.
DSP_ALGORITHM_VERSIONS = MappingProxyType({
    "time_response": 2,
    "spectrum": 3,
    "spectrogram": 3,
    "order_cut": 3,
    "overall_level": 2,
    "order_residual": 1,
})

# The string-valued DSP modes live here, not in each engine, so the GUI layer
# (BlockParamForm renders every str field as a free-text QLineEdit with no
# validator) and every engine agree on the accepted spelling. spectral.py
# validated these from day one; waterfall.py, orders.py and tracking.py silently
# fell back to a default -- a different one each -- when handed an unknown string
# (audit 02 F7-A: amplitude_mode="RMS" gave peak numbers under a "g RMS" label).
VALID_AMPLITUDE_MODES = ("peak", "rms")
VALID_SPECTRUM_FORMATS = ("linear", "power", "psd")
VALID_AVERAGING_TYPES = ("linear", "peak_hold", "exponential")
VALID_TRACKING_MODES = ("rpm", "time")
VALID_SWEEP_DIRECTIONS = ("up", "down", "any")


def normalize_dsp_choice(value: str, valid: tuple, field_name: str) -> str:
    """Lower-case and strip a string-valued DSP mode, rejecting an unknown one.

    A silent fallback to a default writes a result set whose params_hash names
    one mode while the numbers are another's, with nothing in the plot, the unit
    label or the log to reveal it.
    """
    cleaned = str(value).strip().lower()
    if cleaned not in valid:
        raise ValueError(
            f"Unknown {field_name} {value!r}; expected one of {valid}."
        )
    return cleaned


@dataclass
class SpectrumConfig:
    fft_size: int = 4096
    window_type: str = "hann"
    amplitude_mode: str = "rms"
    spectrum_format: str = "linear"
    remove_dc: bool = True
    # How the blocks of one record are combined. "linear" is the classic block
    # average; "peak_hold" keeps the loudest value each bin ever reached (for
    # catching a transient a mean would wash out); "exponential" weights recent
    # blocks more, with exponential_alpha as the weight of each new block.
    averaging_type: str = "linear"
    exponential_alpha: float = 0.1
    decibel_scale: bool = False

@dataclass
class SpectrogramConfig:
    fft_size: int = 4096
    window_type: str = "hann"
    amplitude_mode: str = "rms"
    spectrum_format: str = "linear"
    tracking_mode: str = "rpm"
    step: float = 50.0
    direction: str = "up"
    hysteresis: float = 10.0
    remove_dc: bool = True
    color_scale: str = "Linear"

@dataclass
class OrderTrackingConfig:
    orders_to_extract: list = field(default_factory=lambda: [1.0])
    order_width: float = 0.2
    fft_size: int = 4096
    window_type: str = "hann"
    spectrum_format: str = "linear"
    amplitude_mode: str = "rms"
    step: float = 50.0
    direction: str = "up"
    hysteresis: float = 10.0
    remove_dc: bool = True

@dataclass
class OverallLevelConfig:
    # No spectrum_format: by Parseval the band RMS is the same for Linear, Power
    # and PSD, so the field would only split result-set identity (ADR §1.62 point 4).
    f_start: float = 10.0
    # None is Full Bandwidth -- up to each file's own Nyquist. An intent, not a
    # number, so files at different sampling rates share one identity (§1.62 point 11).
    f_stop: Optional[float] = None
    fft_size: int = 4096
    window_type: str = "hann"
    amplitude_mode: str = "rms"
    tracking_mode: str = "rpm"
    step: float = 50.0
    direction: str = "up"
    hysteresis: float = 10.0
    remove_dc: bool = True
