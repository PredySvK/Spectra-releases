"""
Tacho cleaning: what an RPM Tracked computation does to
the tacho before it places the triggers, as far as Settings › Computation › DSP
decides it.

`TachoCleaning` holds those values. Each one is named the same as the Settings
key it is applied from, the tracked DSP config field and the curve recipe key
that carry it, so a new value is a field here, a setting and a config field;
the rules below then cover it:

- `resolve_tacho_cleaning`: the values a computation runs with -- time mode
  cleans no tacho, and a missing value is the default every result computed
  before it was configurable used;
- `resolve_tacho_cleaning_params`: what of them enters a result's identity --
  only what shaped it (`TachoCleaning.shaping_params`) and is not the default,
  so older results keep theirs;
- `is_tacho_cleaned`: whether a result kind shows them at all.
"""

from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Mapping

from core.block_kinds import KIND_ORDER_CUT, KIND_ORDER_RESIDUAL, KIND_OVERALL_LEVEL, KIND_SPECTROGRAM

# Whether the Hampel filter replaces the tacho's spikes; off leaves only NaN/inf filled.
DEFAULT_TACHO_HAMPEL_FILTER = True
# How far off its neighbourhood median a sample must lie, in sigmas of the
# tacho's own noise, to count as a spike. 8 keeps pure noise from ever being
# flagged: on the 25.6 kHz test-rig tacho no sample is, at 6 none either.
DEFAULT_TACHO_HAMPEL_SIGMA = 8.0
# The moving-average window, in ms, the tacho is smoothed with; 0 is none.
DEFAULT_TACHO_SMOOTHING_MS = 50.0

# Kinds cut against the tacho whatever their params, and kinds cut against it
# only in rpm mode.
_ALWAYS_TACHO_KINDS = (KIND_ORDER_CUT, KIND_ORDER_RESIDUAL)
_RPM_MODE_TACHO_KINDS = (KIND_OVERALL_LEVEL, KIND_SPECTROGRAM)


@dataclass(frozen=True)
class TachoCleaning:
    """The Tacho cleaning values one computation runs with, in the order they act."""

    tacho_hampel_filter: bool = DEFAULT_TACHO_HAMPEL_FILTER
    tacho_hampel_sigma: float = DEFAULT_TACHO_HAMPEL_SIGMA
    tacho_smoothing_ms: float = DEFAULT_TACHO_SMOOTHING_MS

    @property
    def params(self) -> Dict[str, Any]:
        """The values as config fields / curve recipe keys."""
        return asdict(self)

    @property
    def shaping_params(self) -> Dict[str, Any]:
        """`params` without a value that did not act: the threshold of a switched-off Hampel filter."""
        out = self.params
        if not self.tacho_hampel_filter:
            del out["tacho_hampel_sigma"]
        return out


DEFAULT_TACHO_CLEANING = TachoCleaning()

# Config fields the Settings window owns rather than the ribbon or a workflow
# block: stamped in before every calculation, never edited per analysis. A
# workflow block's form hides them.
TACHO_CLEANING_PARAMS = tuple(f.name for f in fields(TachoCleaning))


def _cleans_tacho(params: Mapping[str, Any]) -> bool:
    # A config without a tracking mode (Order Tracking) is rpm-tracked; spelled
    # as core.dsp_configs spells a tracking mode.
    return str(params.get("tracking_mode", "rpm")).strip().lower() == "rpm"


def _resolve_flag(value: Any) -> bool:
    # A recipe gives a bool back; text is spelled out, since bool("false") is True.
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    return bool(value)


def _resolve_value(name: str, value: Any) -> Any:
    if isinstance(getattr(DEFAULT_TACHO_CLEANING, name), bool):
        return _resolve_flag(value)
    return float(value)


def resolve_tacho_cleaning(params: Mapping[str, Any]) -> TachoCleaning:
    """
    The Tacho cleaning a computation with `params` runs, or ran, with:
    `params` is anything that names the values by their keys -- the applied
    Settings, a DSP config's fields, a curve recipe, a result set's params.
    A missing or None value is the default; in time mode every value is the
    default, since no tacho is cleaned there.
    """
    if not _cleans_tacho(params):
        return DEFAULT_TACHO_CLEANING
    return TachoCleaning(**{
        name: _resolve_value(name, params[name]) for name in TACHO_CLEANING_PARAMS
        if params.get(name) is not None
    })


def resolve_tacho_cleaning_params(params: Mapping[str, Any]) -> Dict[str, Any]:
    """
    `params` (a flat `asdict` of a DSP config, a curve recipe or a result set's
    params) without the Tacho cleaning values that did not shape the result
    or are the default: time mode cleans no tacho, a switched-off Hampel filter
    no threshold, and every result computed before a value was configurable
    used its default. A live request's whole config and a saved recipe compare
    equal through here, whatever values either carries.
    """
    out = dict(params)
    kept = resolve_tacho_cleaning(params).shaping_params
    for name, default in DEFAULT_TACHO_CLEANING.params.items():
        if name in out and kept.get(name, default) == default:
            del out[name]
    return out


def is_tacho_cleaned(kind: str, params: Mapping[str, Any]) -> bool:
    """Whether a `kind` result with `params` was cut against a cleaned tacho:
    an order kind always is, a kind with a tracking mode only in rpm mode."""
    if kind in _ALWAYS_TACHO_KINDS:
        return True
    return kind in _RPM_MODE_TACHO_KINDS and _cleans_tacho(params)
