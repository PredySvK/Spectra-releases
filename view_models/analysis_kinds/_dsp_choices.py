"""The register of DSP parameter choices per Analysis kind -- see the component facade."""

import dataclasses
from typing import Any, Dict, Optional, Tuple

from core.dsp_configs import (
    OrderTrackingConfig,
    OverallLevelConfig,
    SpectrogramConfig,
    SpectrumConfig,
)

from ._analysis_kind import (
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTROGRAM,
    ANALYSIS_SPECTRUM,
)

Choice = Tuple[str, Any]


@dataclasses.dataclass(frozen=True)
class ParameterChoices:
    """
    One DSP parameter's closed list: (label shown, value the DSP engine accepts) pairs
    in the one order every editor shows them, and the default value.

    `name` is the DSP config DTO field, or for a display-only parameter that is not
    a DTO field (Order Tracking "Overall level") a name of its own.
    """
    name: str
    choices: Tuple[Choice, ...]
    default: Any

    @property
    def labels(self) -> Tuple[str, ...]:
        return tuple(label for label, _ in self.choices)

    @property
    def values(self) -> Tuple[Any, ...]:
        return tuple(value for _, value in self.choices)

    @property
    def default_label(self) -> str:
        return self.resolve_label(self.default)

    def resolve_value(self, label: str) -> Any:
        """The value behind `label`, or None when the list does not offer it."""
        for choice_label, value in self.choices:
            if choice_label == label:
                return value
        return None

    def resolve_label(self, value: Any) -> Optional[str]:
        """The label shown for `value`, or None when the list does not offer it."""
        for label, choice_value in self.choices:
            # True == 1, so a bool list only matches a bool (and an int list never one).
            if isinstance(choice_value, bool) != isinstance(value, bool):
                continue
            if choice_value == value:
                return label
        return None


@dataclasses.dataclass(frozen=True)
class StepRule:
    """Limits of the tracking step for one tracking mode: [minimum, maximum] at `decimals`."""
    minimum: float
    maximum: float
    decimals: int
    default: float

    def clamp(self, step: float) -> float:
        """`step` brought into [minimum, maximum]."""
        return min(max(float(step), self.minimum), self.maximum)


@dataclasses.dataclass(frozen=True)
class DspChoices:
    """Every DSP parameter's choices and the step rules of one DSP Analysis kind."""
    analysis_kind: str
    config_cls: type
    parameters: Tuple[ParameterChoices, ...]
    step_rules: Tuple[Tuple[str, StepRule], ...] = ()

    def parameter(self, name: str) -> ParameterChoices:
        """The choices of DSP parameter `name`, or ValueError naming what the kind offers."""
        for parameter in self.parameters:
            if parameter.name == name:
                return parameter
        raise ValueError(
            f"{self.analysis_kind!r} has no DSP parameter {name!r} with choices; "
            f"offered: {', '.join(p.name for p in self.parameters)}"
        )

    def step_rule(self, tracking_mode: str) -> StepRule:
        """The step limits for `tracking_mode`, or ValueError when the kind does not track so."""
        for mode, rule in self.step_rules:
            if mode == tracking_mode:
                return rule
        raise ValueError(
            f"{self.analysis_kind!r} does not track by {tracking_mode!r}; "
            f"tracks by: {', '.join(mode for mode, _ in self.step_rules) or 'nothing'}"
        )


def _dto_default(config_cls: type, name: str) -> Any:
    """The DTO field default -- the one source of DSP defaults."""
    return getattr(config_cls(), name)


def _from_dto(config_cls: type, name: str, choices: Tuple[Choice, ...]) -> ParameterChoices:
    return ParameterChoices(name=name, choices=choices, default=_dto_default(config_cls, name))


_FFT_SIZES: Tuple[Choice, ...] = tuple(
    (str(n), n) for n in (256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536))
_WINDOWS: Tuple[Choice, ...] = (
    ("Hanning", "hann"), ("Hamming", "hamming"), ("Blackman", "blackman"),
    ("Flat-top", "flattop"), ("Rectangular", "boxcar"),
)
_AMPLITUDES: Tuple[Choice, ...] = (("RMS", "rms"), ("Peak", "peak"))
_FORMATS: Tuple[Choice, ...] = (("Linear", "linear"), ("Power", "power"), ("PSD", "psd"))
# In Testlab's order.
_AVERAGING: Tuple[Choice, ...] = (
    ("Energy average", "energy"), ("Linear average", "linear"),
    ("Energy exponential average", "energy_exponential"),
    ("Minimum value", "minimum"), ("Maximum value", "maximum"))
_TRACKING_MODES: Tuple[Choice, ...] = (("RPM Tracked", "rpm"), ("Free Run (Time)", "time"))
_DIRECTIONS: Tuple[Choice, ...] = (("Up (Run-Up)", "up"), ("Down (Run-Down)", "down"))


def _spectral_parameters(config_cls: type) -> Tuple[ParameterChoices, ...]:
    return (
        _from_dto(config_cls, "fft_size", _FFT_SIZES),
        _from_dto(config_cls, "window_type", _WINDOWS),
        _from_dto(config_cls, "amplitude_mode", _AMPLITUDES),
    )


def _rpm_step(config_cls: type) -> StepRule:
    return StepRule(minimum=0.1, maximum=5000.0, decimals=1,
                    default=_dto_default(config_cls, "step"))


# The time step is not a DTO default: the DTO's `step` is the RPM one.
_TIME_STEP = StepRule(minimum=0.001, maximum=5000.0, decimals=3, default=0.05)


_REGISTER: Tuple[DspChoices, ...] = (
    DspChoices(
        analysis_kind=ANALYSIS_SPECTRUM, config_cls=SpectrumConfig,
        parameters=_spectral_parameters(SpectrumConfig) + (
            _from_dto(SpectrumConfig, "spectrum_format", _FORMATS),
            _from_dto(SpectrumConfig, "averaging_type", _AVERAGING),
            _from_dto(SpectrumConfig, "decibel_scale", (("Linear", False), ("dB", True))),
        ),
    ),
    DspChoices(
        analysis_kind=ANALYSIS_SPECTROGRAM, config_cls=SpectrogramConfig,
        parameters=_spectral_parameters(SpectrogramConfig) + (
            _from_dto(SpectrogramConfig, "spectrum_format", _FORMATS),
            _from_dto(SpectrogramConfig, "tracking_mode", _TRACKING_MODES),
            _from_dto(SpectrogramConfig, "direction", _DIRECTIONS),
            _from_dto(SpectrogramConfig, "color_scale",
                      (("Linear", "Linear"), ("dB (Log)", "dB (Log)"))),
        ),
        step_rules=(("rpm", _rpm_step(SpectrogramConfig)), ("time", _TIME_STEP)),
    ),
    DspChoices(
        analysis_kind=ANALYSIS_ORDERS, config_cls=OrderTrackingConfig,
        parameters=_spectral_parameters(OrderTrackingConfig) + (
            _from_dto(OrderTrackingConfig, "direction", _DIRECTIONS),
            # Not an OrderTrackingConfig field, so its default lives here.
            ParameterChoices(name="overall_level", choices=(("Off", False), ("On", True)),
                           default=False),
        ),
        step_rules=(("rpm", _rpm_step(OrderTrackingConfig)),),
    ),
    DspChoices(
        analysis_kind=ANALYSIS_OVERALL_LEVEL, config_cls=OverallLevelConfig,
        parameters=_spectral_parameters(OverallLevelConfig) + (
            _from_dto(OverallLevelConfig, "tracking_mode", _TRACKING_MODES),
            _from_dto(OverallLevelConfig, "direction", _DIRECTIONS),
        ),
        step_rules=(("rpm", _rpm_step(OverallLevelConfig)), ("time", _TIME_STEP)),
    ),
)

_BY_KIND: Dict[str, DspChoices] = {entry.analysis_kind: entry for entry in _REGISTER}
_BY_CONFIG: Dict[type, DspChoices] = {entry.config_cls: entry for entry in _REGISTER}


def resolve_dsp_choices(analysis_kind: str) -> DspChoices:
    """The DSP parameter choices of `analysis_kind`, or ValueError naming the DSP kinds."""
    try:
        return _BY_KIND[analysis_kind]
    except KeyError:
        raise ValueError(
            f"analysis kind {analysis_kind!r} has no DSP parameters; "
            f"registered: {', '.join(_BY_KIND)}"
        ) from None


def resolve_dsp_choices_of_config(config_cls: type) -> Optional[DspChoices]:
    """The DSP parameter choices computed into `config_cls`, or None for any other class."""
    return _BY_CONFIG.get(config_cls)
