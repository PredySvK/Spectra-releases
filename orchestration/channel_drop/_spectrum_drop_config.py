"""Which FFT settings a channel dropped onto a Spectrum dock is computed with."""

import dataclasses
from typing import Any, Mapping, Optional

from core.dsp_configs import SpectrumConfig

# The settings a base trace's compute spec records and a drop takes over.
_FROM_COMPUTE_SPEC = ("fft_size", "window_type", "averaging_type", "exponential_alpha")


def resolve_spectrum_drop_config(ribbon_config: SpectrumConfig, *, config_from_trace: bool,
                                 base_compute_spec: Optional[Mapping[str, Any]],
                                 base_spectrum_format: str = "",
                                 base_amplitude_mode: str = "") -> SpectrumConfig:
    """
    The config a newly dropped comparison curve is computed with (R1,
    ideas/session_persistence/PLAN.md §4).

    Default is ``ribbon_config``. With ``config_from_trace`` on ("new curve
    takes the trace's settings") and a base trace whose ``compute_spec`` is
    recorded, the drop takes that curve's settings, so a comparison lands on
    the same FFT/window/format as what is already on screen: the FFT and
    window from its compute spec, the format and amplitude it is shown in
    (``base_spectrum_format``/``base_amplitude_mode``, "" when it says
    neither). ``remove_dc`` always comes from the ribbon.
    """
    if not config_from_trace or not base_compute_spec:
        return ribbon_config
    taken = {name: base_compute_spec.get(name, getattr(ribbon_config, name)) for name in _FROM_COMPUTE_SPEC}
    if base_spectrum_format:
        taken["spectrum_format"] = base_spectrum_format
    if base_amplitude_mode:
        taken["amplitude_mode"] = base_amplitude_mode
    return dataclasses.replace(ribbon_config, **taken)
