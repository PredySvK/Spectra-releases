# =====================================================================
# FILE: core/dsp_configs.py
# =====================================================================
"""
Data Transfer Objects (DTO) bridging the GUI Ribbon panels with the DSP core.
Isolates the mathematical computation engines from PySide6 UI components.
All internal documentation strings and variable labels are standardly written in English.
"""

from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple

from core.tacho_cleaning import (
    DEFAULT_TACHO_CLEANING, DEFAULT_TACHO_HAMPEL_FILTER, DEFAULT_TACHO_HAMPEL_SIGMA,
    DEFAULT_TACHO_SMOOTHING_MS, TACHO_CLEANING_PARAMS, TachoCleaning, resolve_tacho_cleaning,
    resolve_tacho_cleaning_params,
)

# Numeric algorithm version per result kind. io_modules.result_cache folds a
# kind's version into every saved result set's params, so a stale result computed
# by older math is never mistaken for a valid cache hit just because the
# FFT/tracking settings look the same. Bump a kind's entry when a change to
# that kind's DSP alters the numeric output for the same inputs (not for a
# docstring or refactor) -- once per release: compare with the last tag, and an
# entry already above it stays (docs/agents/release.md). Lives here in core/ so both the DSP layer and the cache
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
    "spectrum": 4,
    "spectrogram": 6,
    "order_cut": 5,
    "overall_level": 5,
    "order_residual": 3,
})

# The string-valued DSP modes live here, not in each engine, so the GUI layer
# (BlockParamForm renders every str field as a free-text QLineEdit with no
# validator) and every engine agree on the accepted spelling. spectral.py
# validated these from day one; waterfall.py, orders.py and tracking.py silently
# fell back to a default -- a different one each -- when handed an unknown string
# (audit 02 F7-A: amplitude_mode="RMS" gave peak numbers under a "g RMS" label).
VALID_AMPLITUDE_MODES = ("peak", "rms")
VALID_SPECTRUM_FORMATS = ("linear", "power", "psd")
VALID_AVERAGING_TYPES = ("energy", "linear", "energy_exponential", "minimum", "maximum")
# The spectrum formats a spectrum averaged by a mode may be shown in, for the
# modes that do not allow every one. Linear average is a mean amplitude: its
# square is not the mean power Testlab shows as Power, and a PSD of it is no
# density -- on noise it reads 1.05 dB low (§1.283). Every other mode combines
# power and shows every format.
AVERAGING_FORMATS = MappingProxyType({"linear": ("linear",)})

VALID_TRACKING_MODES = ("rpm", "time")
VALID_SWEEP_DIRECTIONS = ("up", "down")

def allows_format(averaging_type: Optional[str], spectrum_format: str) -> bool:
    """Whether a spectrum averaged by `averaging_type` may be shown in
    `spectrum_format`; None (no averaging, e.g. a spectrogram) shows every one."""
    formats = AVERAGING_FORMATS.get(averaging_type)
    return formats is None or spectrum_format in formats


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
    # How the frames of one record are combined, named as in Simcenter Testlab
    # (#951, #1003). "energy" is the mean power of every frame; "linear" the mean
    # amplitude (Linear format only, §1.283); "energy_exponential" weights recent frames
    # more, with exponential_parameter as the weight of the old average, 0-1, as
    # Testlab's Exponential parameter in % (#956); "minimum" /
    # "maximum" keep the lowest / loudest power each bin reached (a maximum
    # catches a transient a mean would wash out).
    averaging_type: str = "energy"
    exponential_parameter: float = 0.5
    decibel_scale: bool = False

@dataclass
class TrackingSweepFields:
    """
    The Tracking sweep fields every tracked config has, Order Tracking (always
    rpm-tracked) included -- declared once, so a new sweep setting is one field
    here. A config inherits them as plain fields: its `asdict` stays flat, the
    keys the curve recipe, a workflow block's params and the ribbon share.
    `resolve_tracking_sweep` reads them into one TrackingSweep.
    """

    step: float = 50.0
    direction: str = "up"
    # Tracking range (#805): the span of the sweep that counts, in positive rpm.
    # None is auto -- 0 rpm and the record's top speed -- an intent rather than
    # a number, so one setting is one identity over every measurement.
    rpm_min: Optional[float] = None
    rpm_max: Optional[float] = None
    # Tacho cleaning, one field per TACHO_CLEANING_PARAMS
    # name; Settings stamps them in, the ribbon and a workflow block never show them.
    tacho_hampel_filter: bool = DEFAULT_TACHO_HAMPEL_FILTER
    tacho_hampel_sigma: float = DEFAULT_TACHO_HAMPEL_SIGMA
    tacho_smoothing_ms: float = DEFAULT_TACHO_SMOOTHING_MS


# A config that tracks against rpm or time adds these two groups. Three
# groups rather than two because a dataclass lists inherited fields first, base
# by base: a config declared `(TimeRangeFields, TrackingSweepFields,
# TrackingModeField)` lists mode, step, direction, rpm range, time range -- the
# order a workflow block's form shows its rows in.
@dataclass
class TrackingModeField:
    tracking_mode: str = "rpm"


@dataclass
class TimeRangeFields:
    # Tracking range in time mode (#807): Start / End [s] in the time of the
    # time axis, None is the whole record. Kept apart from the rpm pair, so a
    # speed is never read as seconds.
    time_start: Optional[float] = None
    time_end: Optional[float] = None


def resolve_tracking_sweep_fields(config: TrackingSweepFields) -> Dict[str, Any]:
    """`config`'s TrackingSweepFields by name, to hand one config's sweep to another."""
    return {f.name: getattr(config, f.name) for f in fields(TrackingSweepFields)}


@dataclass
class SpectrogramConfig(TimeRangeFields, TrackingSweepFields, TrackingModeField):
    fft_size: int = 4096
    window_type: str = "hann"
    amplitude_mode: str = "rms"
    spectrum_format: str = "linear"
    remove_dc: bool = True
    color_scale: str = "Linear"

@dataclass
class OrderTrackingConfig(TrackingSweepFields):
    orders_to_extract: list = field(default_factory=lambda: [1.0])
    order_width: float = 0.2
    fft_size: int = 4096
    window_type: str = "hann"
    amplitude_mode: str = "rms"
    remove_dc: bool = True

@dataclass
class OverallLevelConfig(TimeRangeFields, TrackingSweepFields, TrackingModeField):
    # No spectrum_format: by Parseval the band RMS is the same for Linear, Power
    # and PSD, so the field would only split result-set identity.
    f_start: float = 10.0
    # None is Full Bandwidth -- up to each file's own Nyquist. An intent, not a
    # number, so files at different sampling rates share one identity (§1.62 point 11).
    f_stop: Optional[float] = None
    fft_size: int = 4096
    window_type: str = "hann"
    amplitude_mode: str = "rms"
    remove_dc: bool = True


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
    The direction is the same: time mode has none, so it is None there. The
    Tacho cleaning too: time mode cleans no tacho, so it holds the default
    there.
    """

    mode: str = "rpm"
    step: float = 50.0
    direction: Optional[str] = "up"
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
        "direction": config.direction,
        "rpm_min": config.rpm_min, "rpm_max": config.rpm_max,
        "time_start": getattr(config, "time_start", None),
        "time_end": getattr(config, "time_end", None),
    })
    mode = _resolve_tracking_mode(params["tracking_mode"])
    return TrackingSweep(
        mode=mode,
        step=config.step,
        direction=None if params["direction"] is None else _resolve_tracking_mode(params["direction"]),
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
    with the Tracking range of the inactive tracking mode set to None (auto),
    and in time mode the direction set to None too: a time-tracked result has
    no direction, whatever the Ramp combo was left on. A config without a
    tracking mode is rpm-tracked; one without range fields comes back
    unchanged. The curve recipe goes through here, so a result's
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
    if mode == "time" and "direction" in out:
        out["direction"] = None
    return out
