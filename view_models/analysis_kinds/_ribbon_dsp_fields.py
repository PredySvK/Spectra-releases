"""The saved controls of each DSP ribbon tab -- see the component facade."""

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
from ._dsp_choices import ParameterChoices, resolve_dsp_choices

FIELD_CHOICE = "choice"
FIELD_FLAG = "flag"
FIELD_NUMBER = "number"
FIELD_TEXT = "text"


@dataclasses.dataclass(frozen=True)
class RibbonDspField:
    """
    One saved control of a DSP ribbon tab: the parameter it shows, the QSettings
    key it is saved under and its default in the form QSettings keeps.

    `kind` is FIELD_CHOICE (a closed list; QSettings keeps the label, ADR §1.186
    point 6), FIELD_FLAG (bool), FIELD_NUMBER (float) or FIELD_TEXT (str). A choice
    field carries its register entry, the one source of its labels and default.
    """
    name: str
    key: str
    kind: str
    default: Any
    choices: Optional[ParameterChoices] = None

    def resolve_saved(self, saved: Any) -> Optional[Any]:
        """
        What the control shows for the value QSettings returned (a label, bool,
        float or str), or None when that value is not one the control can show --
        the caller then falls back to the default.
        """
        if self.kind == FIELD_CHOICE:
            return saved if saved in self.choices.labels else None
        if self.kind == FIELD_FLAG:
            if isinstance(saved, bool):
                return saved
            return {"true": True, "false": False}.get(str(saved).strip().lower())
        if self.kind == FIELD_NUMBER:
            if isinstance(saved, bool):
                return None
            try:
                return float(saved)
            except (TypeError, ValueError):
                return None
        return str(saved)


def _choice(choices, name: str, key: str) -> RibbonDspField:
    parameter = choices.parameter(name)
    return RibbonDspField(name=name, key=key, kind=FIELD_CHOICE,
                          default=parameter.default_label, choices=parameter)


def _flag(name: str, key: str, default: bool) -> RibbonDspField:
    return RibbonDspField(name=name, key=key, kind=FIELD_FLAG, default=bool(default))


def _number(name: str, key: str, default: float) -> RibbonDspField:
    return RibbonDspField(name=name, key=key, kind=FIELD_NUMBER, default=float(default))


def _spectral(choices, prefix: str) -> Tuple[RibbonDspField, ...]:
    return (
        _choice(choices, "fft_size", f"{prefix}_fft_size"),
        _choice(choices, "window_type", f"{prefix}_window"),
        _choice(choices, "amplitude_mode", f"{prefix}_amplitude"),
    )


def _spectrum_fields() -> Tuple[RibbonDspField, ...]:
    choices = resolve_dsp_choices(ANALYSIS_SPECTRUM)
    dto = SpectrumConfig()
    return _spectral(choices, "spec1d") + (
        _choice(choices, "spectrum_format", "spec1d_format"),
        _choice(choices, "decibel_scale", "spec1d_scale"),
        _choice(choices, "averaging_type", "spec1d_averaging"),
        # Saved as the control shows it, in percent; the DTO keeps the fraction (#956).
        _number("exponential_parameter", "spec1d_exp_parameter", 100.0 * dto.exponential_parameter),
        _flag("remove_dc", "spec1d_remove_dc", dto.remove_dc),
        # Not DSP config fields: they go to AppContext, but reset returns them too.
        _flag("new_curve_from_trace", "spec1d_new_curve_from_trace", False),
        _flag("band_rms_cursors", "spec1d_band_rms_cursors", False),
    )


def _spectrogram_fields() -> Tuple[RibbonDspField, ...]:
    choices = resolve_dsp_choices(ANALYSIS_SPECTROGRAM)
    return _spectral(choices, "spec2d") + (
        _choice(choices, "spectrum_format", "spec2d_format"),
        _choice(choices, "color_scale", "spec2d_color_scale"),
        _flag("remove_dc", "spec2d_remove_dc", SpectrogramConfig().remove_dc),
    )


def _order_tracking_fields() -> Tuple[RibbonDspField, ...]:
    choices = resolve_dsp_choices(ANALYSIS_ORDERS)
    dto = OrderTrackingConfig()
    return _spectral(choices, "order") + (
        RibbonDspField(name="orders_to_extract", key="order_targets", kind=FIELD_TEXT,
                       default=", ".join(f"{order:g}" for order in dto.orders_to_extract)),
        _number("order_width", "order_width", dto.order_width),
        _flag("overall_level", "order_overall_level", choices.parameter("overall_level").default),
        _flag("remove_dc", "order_remove_dc", dto.remove_dc),
    )


def _overall_level_fields() -> Tuple[RibbonDspField, ...]:
    choices = resolve_dsp_choices(ANALYSIS_OVERALL_LEVEL)
    dto = OverallLevelConfig()
    return _spectral(choices, "oal") + (
        _number("f_start", "oal_f_min", dto.f_start),
        # f_stop=None is Full Bandwidth; the two controls make up that one field.
        _flag("full_bandwidth", "oal_full_bandwidth", dto.f_stop is None),
        # F max has no DTO default (the DTO's is None), so its default lives here.
        _number("f_stop", "oal_f_max", 1000.0),
        _flag("remove_dc", "oal_remove_dc", dto.remove_dc),
    )


_BY_KIND: Dict[str, Tuple[RibbonDspField, ...]] = {
    ANALYSIS_SPECTRUM: _spectrum_fields(),
    ANALYSIS_SPECTROGRAM: _spectrogram_fields(),
    ANALYSIS_ORDERS: _order_tracking_fields(),
    ANALYSIS_OVERALL_LEVEL: _overall_level_fields(),
}


def resolve_ribbon_dsp_fields(analysis_kind: str) -> Tuple[RibbonDspField, ...]:
    """The saved controls of `analysis_kind`'s ribbon tab, or ValueError naming the DSP kinds."""
    try:
        return _BY_KIND[analysis_kind]
    except KeyError:
        raise ValueError(
            f"analysis kind {analysis_kind!r} has no DSP ribbon tab; "
            f"registered: {', '.join(_BY_KIND)}"
        ) from None
