# =====================================================================
# FILE: core/evaluation.py
# =====================================================================
"""
Evaluation's data model: Single value, Evaluation table and
Evaluation config. Pure data -- no Qt, no I/O, no knowledge of a dock. A dock
is only one adapter that can produce the (block, identity) pairs an
Evaluation runs over (signal_processing/evaluation/runner.py); a future
workflow runner is meant to be able to produce the same pairs without this
module changing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Tuple, Union

from core.data_block import NVHDataBlock
from core.units import UnitPreferences, convert_signal_to_global_unit


@dataclass(frozen=True)
class CurveOrder:
    """The order a curve was cut at, and the order width of the cut when the
    Evaluation chose it (Typed / Dominant orders); a dock's own Order cut
    leaves `width` None, as its legend does."""
    order: float
    width: Optional[float] = None


@dataclass(frozen=True)
class CurveBand:
    """The frequency band of an Overall Level curve, in Hz. `f_stop` None is
    Full Bandwidth (CONTEXT.md)."""
    f_start: float
    f_stop: Optional[float] = None


@dataclass(frozen=True)
class CurveResidual:
    """A Residual curve. Its band is always the Overall Level default
   , so it carries no numbers of its own."""


OrderOrBand = Union[CurveOrder, CurveBand, CurveResidual, None]


@dataclass(frozen=True)
class CurveIdentity:
    """
    Which curve a Single value came from, in Evaluation table column terms
    (CONTEXT.md Evaluation): channel, direction, measurement, source (a
    result set's label, or "Live"), the dock-local Parameter Set label
    (io_modules.parameter_sets), the order or band the curve was computed
    with as numbers (`order_or_band`, None for a curve with neither), plus its
    typed Curve metadata record (`curve_metadata`, ADR §1.184). Its text and
    sort key are made in one place, view_models.evaluation -- never parsed
    back from a string (#793). Built by the dock adapter
    (gui/workspace/evaluation_adapter.py) from the same identity machinery
    the Filter panel uses -- not re-derived here.
    """
    channel: str
    direction: str
    measurement: str
    source: str
    parameter_set: str
    order_or_band: OrderOrBand
    curve_metadata: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class SingleValue:
    """
    One number an Evaluation extracted from one curve, together with where on
    the curve it sits.

    Holds the source block and the sample index into it rather than a scaled
    number: the block already carries everything a later Format/Amplitude
    switch needs (`NVHDataBlock.to_display_values`, ADR §1.60/§1.61), so
    `display_value()` re-derives the shown number on demand instead of a
    second copy of the scaling table. `sample_index` is None for a curve with
    no finite sample -- the empty Single value ("--" in the table), never a
    dropped row.
    """
    identity: CurveIdentity
    block: NVHDataBlock
    sample_index: Optional[int]
    is_edge: bool = False

    @property
    def is_empty(self) -> bool:
        return self.sample_index is None

    def display_value(
        self,
        spectrum_format: str = "linear",
        amplitude_mode: str = "rms",
        prefs: Optional[UnitPreferences] = None,
    ) -> Tuple[Optional[float], str]:
        """The Single value in the requested Format x Amplitude view. Format
        and lin/dB never move a maximum, Amplitude can: read a
        row from `EvaluationTable.rows_in` of the same `amplitude_mode`."""
        if self.is_empty:
            # The unit a valued row of this curve would carry, Amplitude and
            # Format included: a curve without a value still has a unit.
            _, empty_unit = self.block.to_display_values(spectrum_format, amplitude_mode)
            if prefs is not None:
                _, empty_unit = convert_signal_to_global_unit(
                    None, empty_unit, self.block.channel_type, prefs
                )
            if empty_unit.endswith(" PEAK"):
                empty_unit = empty_unit[:-5] + " Peak"
            return None, empty_unit

        values, unit = self.block.to_display_values(spectrum_format, amplitude_mode)
        if prefs is not None:
            values, unit = convert_signal_to_global_unit(
                values, unit, self.block.channel_type, prefs
            )
        if unit.endswith(" PEAK"):
            unit = unit[:-5] + " Peak"
        return float(values[self.sample_index]), unit

    @property
    def x_value(self) -> Optional[float]:
        if self.is_empty:
            return None
        return float(self.block.primary_axis.values[self.sample_index])

    @property
    def x_unit(self) -> str:
        return self.block.primary_axis.unit

    @property
    def x_quantity(self) -> str:
        return self.block.primary_axis.quantity


@dataclass(frozen=True)
class EvaluationTable:
    """All the Single values one Evaluation produced over a dock's curves,
    plus which Evaluation and with what parameters (CONTEXT.md Evaluation
    table) -- so a pivot or trend view downstream never has to ask a second
    place what produced its rows.

    `rows` are the maxima of the RMS view, `peak_rows` those of the Peak view
   : a spectrum's DC and Nyquist bins are not doubled for Peak,
    so its maxima -- positions, order, even which ones there are -- can differ
    between the two. None means the Evaluation's rows do not depend on
    Amplitude and `rows` serve both."""
    evaluation_name: str
    params: Dict[str, Any]
    rows: Tuple[SingleValue, ...]
    peak_rows: Optional[Tuple[SingleValue, ...]] = None

    def rows_in(self, amplitude_mode: str) -> Tuple[SingleValue, ...]:
        """The rows to show when the table's Amplitude switch is `amplitude_mode`."""
        if amplitude_mode == "peak" and self.peak_rows is not None:
            return self.peak_rows
        return self.rows


@dataclass(frozen=True)
class EvaluationConfig:
    """
    Which Evaluation a dock has selected, the parameters of every Evaluation
    the dock has had, and the table's own settings, as data with a JSON round
    trip.

    `params_by_evaluation` keeps an Evaluation's parameters after the dock
    moves to another one, so going back finds them again; an Evaluation with
    no entry runs on its defaults. An unknown Evaluation's entry is kept too.
    """
    evaluation_name: str = "max"
    params_by_evaluation: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    respect_trace_filter: bool = True
    metadata_columns: Tuple[str, ...] = ()

    @property
    def params(self) -> Dict[str, Any]:
        """The selected Evaluation's parameters; empty means its defaults."""
        return self.params_for(self.evaluation_name)

    def params_for(self, evaluation_name: str) -> Dict[str, Any]:
        """`evaluation_name`'s remembered parameters; empty means its defaults."""
        return dict(self.params_by_evaluation.get(evaluation_name, {}))

    def with_params(self, params: Mapping[str, Any]) -> "EvaluationConfig":
        """This config with the selected Evaluation's parameters replaced,
        every other Evaluation's left as they were."""
        remembered = dict(self.params_by_evaluation)
        remembered[self.evaluation_name] = dict(params)
        return replace(self, params_by_evaluation=remembered)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_name": self.evaluation_name,
            "params_by_evaluation": {
                name: dict(params) for name, params in self.params_by_evaluation.items()
            },
            "respect_trace_filter": self.respect_trace_filter,
            "metadata_columns": list(self.metadata_columns),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvaluationConfig":
        # A project saved before §1.259 has a single `params`; it is not read
        # (no backward compatibility, §1.259 point 7).
        if not isinstance(data, (dict, Mapping)):
            return cls()
        raw_name = data.get("evaluation_name")
        eval_name = str(raw_name) if raw_name is not None else "max"
        raw_params = data.get("params_by_evaluation")
        params_by_evaluation = {
            str(name): dict(params)
            for name, params in (raw_params.items() if isinstance(raw_params, dict) else ())
            if isinstance(params, dict)
        }
        raw_respect = data.get("respect_trace_filter")
        respect = bool(raw_respect) if raw_respect is not None else True
        raw_cols = data.get("metadata_columns")
        meta_cols = tuple(str(c) for c in raw_cols) if isinstance(raw_cols, (list, tuple)) else ()
        return cls(
            evaluation_name=eval_name,
            params_by_evaluation=params_by_evaluation,
            respect_trace_filter=respect,
            metadata_columns=meta_cols,
        )
