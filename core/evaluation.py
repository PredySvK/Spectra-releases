# =====================================================================
# FILE: core/evaluation.py
# =====================================================================
"""
Evaluation's data model (ADR §1.64): Single value, Evaluation table and
Evaluation config. Pure data -- no Qt, no I/O, no knowledge of a dock. A dock
is only one adapter that can produce the (block, identity) pairs an
Evaluation runs over (signal_processing/evaluation/runner.py); a future
workflow runner is meant to be able to produce the same pairs without this
module changing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

from core.data_block import NVHDataBlock
from core.units import UnitPreferences, convert_signal_to_global_unit


@dataclass(frozen=True)
class CurveIdentity:
    """
    Which curve a Single value came from, in Evaluation table column terms
    (CONTEXT.md Evaluation): channel, direction, measurement, source (a
    result set's label, or "Live"), the dock-local Parameter Set label
    (io_modules.parameter_sets), and a display string for the order or band
    the curve was computed with. Built by the dock adapter
    (gui/workspace/evaluation_adapter.py) from the same identity machinery
    the Filter panel uses -- not re-derived here.
    """
    channel: str
    direction: str
    measurement: str
    source: str
    parameter_set: str
    order_or_band: str
    metadata: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class SingleValue:
    """
    One number an Evaluation extracted from one curve, together with where on
    the curve it sits (ADR §1.64 point 4/6).

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
        """The Single value in the requested Format x Amplitude view. The
        position of the maximum does not move between views (ADR §1.64 point
        4: they are monotonic rescales of the same canonical number), so
        `sample_index` stays valid however this is called."""
        if self.is_empty:
            empty_unit = self.block.value_unit
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
    place what produced its rows."""
    evaluation_name: str
    params: Dict[str, Any]
    rows: Tuple[SingleValue, ...]


@dataclass(frozen=True)
class EvaluationConfig:
    """
    Which Evaluation a dock has selected and with what parameters, as data
    with a JSON round trip (ADR §1.64 point 1).
    """
    evaluation_name: str = "max"
    params: Dict[str, Any] = field(default_factory=dict)
    respect_trace_filter: bool = True
    metadata_columns: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_name": self.evaluation_name,
            "params": dict(self.params),
            "respect_trace_filter": self.respect_trace_filter,
            "metadata_columns": list(self.metadata_columns),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvaluationConfig":
        if not isinstance(data, (dict, Mapping)):
            return cls()
        raw_name = data.get("evaluation_name")
        eval_name = str(raw_name) if raw_name is not None else "max"
        raw_params = data.get("params")
        params = dict(raw_params) if isinstance(raw_params, dict) else {}
        raw_respect = data.get("respect_trace_filter")
        respect = bool(raw_respect) if raw_respect is not None else True
        raw_cols = data.get("metadata_columns")
        meta_cols = tuple(str(c) for c in raw_cols) if isinstance(raw_cols, (list, tuple)) else ()
        return cls(
            evaluation_name=eval_name,
            params=params,
            respect_trace_filter=respect,
            metadata_columns=meta_cols,
        )
