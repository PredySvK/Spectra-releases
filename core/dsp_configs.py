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
from typing import Any, Dict, Mapping, Optional, Tuple

from core.tacho_cleaning import (
    DEFAULT_TACHO_CLEANING, DEFAULT_TACHO_SMOOTHING_MS, TACHO_CLEANING_PARAMS, TachoCleaning,
    resolve_tacho_cleaning, resolve_tacho_cleaning_params,
)

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
    "spectrogram": 5,
    "order_cut": 4,
    "overall_level": 4,
    "order_residual": 2,
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
VALID_SWEEP_DIRECTIONS = ("up", "down")

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
    # Tracking range (#805): the span of the sweep that counts, in positive rpm.
    # None is auto -- 0 rpm and the record's top speed -- an intent rather than
    # a number, so one setting is one identity over every measurement.
    rpm_min: Optional[float] = None
    rpm_max: Optional[float] = None
    # Tracking range in time mode (#807): Start / End [s] in the time of the
    # time axis, None is the whole record. Kept apart from the rpm pair, so a
    # speed is never read as seconds.
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    remove_dc: bool = True
    color_scale: str = "Linear"
    tacho_smoothing_ms: float = DEFAULT_TACHO_SMOOTHING_MS

@dataclass
class OrderTrackingConfig:
    orders_to_extract: list = field(default_factory=lambda: [1.0])
    order_width: float = 0.2
    fft_size: int = 4096
    window_type: str = "hann"
    amplitude_mode: str = "rms"
    step: float = 50.0
    direction: str = "up"
    rpm_min: Optional[float] = None    # Tracking range, as in SpectrogramConfig
    rpm_max: Optional[float] = None
    remove_dc: bool = True
    tacho_smoothing_ms: float = DEFAULT_TACHO_SMOOTHING_MS

@dataclass
class OverallLevelConfig:
    # No spectrum_format: by Parseval the band RMS is the same for Linear, Power
    # and PSD, so the field would only split result-set identity.
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
    rpm_min: Optional[float] = None    # Tracking range, as in SpectrogramConfig
    rpm_max: Optional[float] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    remove_dc: bool = True
    tacho_smoothing_ms: float = DEFAULT_TACHO_SMOOTHING_MS


# The Tracking range fields of a tracked config, per tracking mode. Only the
# pair of the config's own mode counts; the other one is auto.
_TRACKING_RANGE_FIELDS = {"rpm": ("rpm_min", "rpm_max"), "time": ("time_start", "time_end")}


def _resolve_tracking_mode(value: Any) -> str:
    # Spelled as normalize_dsp_choice spells it, without its refusal: an
    # unknown mode is the computation's to report, not the identity's.
    return str(value).strip().lower()


@dataclass(frozen=True)
class TrackingSweep:
    """
    Everything a TrackingPlan is built from, apart from the tacho: the
    tracking mode, step, direction and the Tracking range of that mode. One
    value, so the shared plan's scratch key, the scratch bag's identity and the
    plan itself cannot each follow another subset of the settings (#805, #807).

    Only the range of `mode` is kept; the other pair is always None (auto).
    A workflow block shows both pairs whatever its mode, and a filled-in pair
    of the other mode must not make the same computation another result.
    The Tacho cleaning is the same: time mode cleans no tacho, so it holds the
    default there.
    """

    mode: str = "rpm"
    step: float = 50.0
    direction: str = "up"
    rpm_min: Optional[float] = None
    rpm_max: Optional[float] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    tacho_cleaning: TachoCleaning = DEFAULT_TACHO_CLEANING

    @property
    def bounds(self) -> Tuple[Optional[float], ...]:
        """(rpm_min, rpm_max, time_start, time_end)."""
        return self.rpm_min, self.rpm_max, self.time_start, self.time_end


def resolve_tracking_sweep(config: Any) -> TrackingSweep:
    """The TrackingSweep of a Spectrogram, Order Tracking or Overall Level config;
    Order Tracking is always rpm-tracked and has no time range."""
    params = resolve_active_tracking_params({
        "tracking_mode": getattr(config, "tracking_mode", "rpm"),
        "rpm_min": config.rpm_min, "rpm_max": config.rpm_max,
        "time_start": getattr(config, "time_start", None),
        "time_end": getattr(config, "time_end", None),
    })
    mode = _resolve_tracking_mode(params["tracking_mode"])
    return TrackingSweep(
        mode=mode,
        step=config.step, direction=_resolve_tracking_mode(config.direction),
        rpm_min=params["rpm_min"], rpm_max=params["rpm_max"],
        time_start=params["time_start"], time_end=params["time_end"],
        tacho_cleaning=resolve_tacho_cleaning({
            "tracking_mode": mode,
            **{name: getattr(config, name) for name in TACHO_CLEANING_PARAMS if hasattr(config, name)},
        }),
    )


def resolve_active_tracking_params(params: Mapping[str, Any]) -> Dict[str, Any]:
    """
    `params` (a flat `asdict` of a DSP config, or a workflow block's params)
    with the Tracking range of the inactive tracking mode set to None (auto).
    A config without a tracking mode is rpm-tracked; one without range fields
    comes back unchanged. The curve recipe goes through here, so a result's
    identity holds only the range that shaped it, however the config was made.

    The Tacho cleaning values are dropped unless they shaped the result and
    are not the default (`resolve_tacho_cleaning_params`), so a default keeps
    the identity every older result was saved with.
    """
    mode = _resolve_tracking_mode(params.get("tracking_mode", "rpm"))
    out = resolve_tacho_cleaning_params(params)
    for other_mode, names in _TRACKING_RANGE_FIELDS.items():
        if other_mode != mode:
            for name in names:
                if name in out:
                    out[name] = None
    return out
