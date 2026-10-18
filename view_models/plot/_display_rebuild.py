"""
Re-scaling a finished ``PlotModel`` in memory -- display settings, RMS/Peak,
global units, X domain -- without disk I/O or DSP recomputation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from core.axis_projections import can_project, project_x
from core.block_kinds import LEVEL_CURVE_KINDS, RMS_PEAK_CURVE_KINDS
from core.units import (
    UnitPreferences,
    check_units_compatibility,
    convert_numeric_array,
    convert_signal_to_global_unit,
    is_squared_format,
    sanitize_unit_string,
)

from ._legend_settings import build_legend_text, format_display_unit
from ._plot_model import PlotModel, Trace
from ._plot_model_builder import (
    _base_trace_index,
    _linear_amplitude_display,
    _level_legend_text,
    _y_axis_label,
    resolve_overlay_axis,
    to_decibels,
)


@dataclass(frozen=True)
class _RebuildRules:
    """
    What differs between the three in-memory rebuilds of a finished model; the
    pass itself (``_rebuild_traces``) is the same for all of them.

    ``linear`` -> a trace's (values, unit) before the global-unit conversion.
    ``is_db`` / ``is_squared`` -> whether a trace ends in dB, and with which dB
    formula. ``legend`` -> its legend for a unit label. ``new_spec`` -> its new
    compute_spec, or None to leave it. ``writes_source``: the linear values
    become the trace's ``y_raw`` / ``source_unit``. ``align_in_db``: a dB
    overlay that shares the primary axis is first converted to the base unit
    (only the units rebuild does, ADR §1.89).
    """

    linear: Callable[[Trace], Tuple[np.ndarray, str]]
    is_db: Callable[[Trace], bool]
    is_squared: Callable[[Trace], bool]
    legend: Callable[[Trace, str], str]
    new_spec: Callable[[Trace], Optional[Dict[str, Any]]]
    writes_source: bool
    align_in_db: bool


def _rebuild_traces(model: PlotModel, prefs: UnitPreferences, rules: _RebuildRules) -> PlotModel:
    """
    The one pass over ``model``'s traces in the display units of ``prefs`` (ADR
    §1.60, §1.89): physical unit conversion first, dB from the converted values
    last. The base curve fixes the primary axis unit; a compatible overlay is
    re-aligned onto it, an incompatible one keeps its own on the secondary axis;
    legend and the ordinate label follow.
    """
    new_traces: List[Trace] = []
    base_unit: Optional[str] = None
    base_channel_type: Optional[str] = None
    base_is_db = False
    base_idx = _base_trace_index(model)

    for i, tr in enumerate(model.traces):
        y_lin, unit_lin = rules.linear(tr)
        render_y, target_unit = convert_signal_to_global_unit(y_lin, unit_lin, tr.channel_type, prefs)
        sanitized = sanitize_unit_string(target_unit)
        was_db = rules.is_db(tr)

        changes: Dict[str, Any] = {}
        if rules.writes_source:
            changes.update(y_raw=y_lin, source_unit=unit_lin)
        compute = rules.new_spec(tr)
        if compute is not None:
            changes["compute_spec"] = compute

        y, unit = render_y, sanitized
        if tr.is_base or i == base_idx:
            base_unit, base_channel_type, base_is_db = sanitized, tr.channel_type, was_db
            changes.update(is_base=True, axis="primary")
        else:
            axis = resolve_overlay_axis(base_unit, sanitized, base_is_db=base_is_db, overlay_is_db=was_db)
            if (axis == "primary" and base_unit and check_units_compatibility(base_unit, sanitized)
                    and (rules.align_in_db or not was_db)):
                y = convert_numeric_array(render_y, from_unit=sanitized, to_unit=base_unit)
                unit = base_unit
            changes["axis"] = axis
        if was_db:
            y, unit = to_decibels(y, rules.is_squared(tr)), "dB"
        new_traces.append(replace(tr, y=y, unit=unit, label=rules.legend(tr, unit), **changes))

    if base_unit is None:
        view = model.view
    elif base_is_db:
        view = replace(model.view, y_label="Amplitude", y_unit="dB")
    else:
        view = replace(model.view, y_label=_y_axis_label(base_channel_type or ""),
                       y_unit=format_display_unit(base_unit))
    return replace(model, traces=new_traces, view=view)


def _plain_legend(tr: Trace, unit: str) -> str:
    return build_legend_text(tr.file_name, tr.channel_name, unit, tr.meta_ref)


def _kind_legend(tr: Trace, unit: str) -> str:
    """The legend of ``tr`` for ``unit`` -- a level curve keeps its band text."""
    base_legend = _plain_legend(tr, unit)
    if tr.block is not None and getattr(tr.block, "kind", None) in LEVEL_CURVE_KINDS:
        return _level_legend_text(tr.block, base_legend)
    return base_legend


def rebuild_with_base(model: PlotModel, base_index: int) -> PlotModel:
    """
    ``model`` with trace ``base_index`` as its base curve and every other trace
    re-routed onto the primary or secondary axis against it (#693) -- for when
    the base curve left the graph. Works on the units the traces are already
    shown in (no unit preferences, no raw data): a trace sharing the new
    primary axis in a compatible unit spelled differently is converted onto
    the base unit; values, dB state and pens are otherwise left as they are.
    The ordinate label follows the new base.
    """
    base = model.traces[base_index]
    base_unit = base.unit
    base_is_db = base_unit == "dB"
    new_traces: List[Trace] = []
    for i, tr in enumerate(model.traces):
        if i == base_index:
            new_traces.append(replace(tr, is_base=True, axis="primary"))
            continue
        is_db = tr.unit == "dB"
        axis = resolve_overlay_axis(base_unit, tr.unit, base_is_db=base_is_db, overlay_is_db=is_db)
        changes: Dict[str, Any] = dict(is_base=False, axis=axis)
        if axis == "primary" and not is_db and tr.unit != base_unit:
            changes.update(y=convert_numeric_array(tr.y, from_unit=tr.unit, to_unit=base_unit),
                           unit=base_unit, label=_kind_legend(tr, base_unit))
        new_traces.append(replace(tr, **changes))

    if base_is_db:
        view = replace(model.view, y_label="Amplitude", y_unit="dB")
    else:
        view = replace(model.view, y_label=_y_axis_label(base.channel_type or ""),
                       y_unit=format_display_unit(base_unit))
    return replace(model, traces=new_traces, view=view)


def _is_canonical(tr: Trace) -> bool:
    return tr.block is not None and getattr(tr.block, "is_canonical", False)


def rebuild_spectrum_with_display_settings(
    model: PlotModel,
    *,
    spectrum_format: str = "linear",
    amplitude_mode: str = "rms",
    decibel_scale: bool = False,
    prefs: Optional[UnitPreferences] = None,
) -> PlotModel:
    """
    Re-scales a spectrum PlotModel on the fly from its canonical blocks.
    Runs purely in-memory (< 1 ms), without disk I/O or DSP recomputation.
    """
    def linear(tr: Trace):
        if _is_canonical(tr):
            return tr.block.to_display_values(spectrum_format=spectrum_format, amplitude_mode=amplitude_mode)
        return tr.y_raw, tr.source_unit

    def is_squared(tr: Trace) -> bool:
        if _is_canonical(tr):
            return is_squared_format(spectrum_format)
        return bool(tr.compute_spec and is_squared_format(tr.compute_spec.get("spectrum_format")))

    def new_spec(tr: Trace) -> Dict[str, Any]:
        updated = dict(tr.compute_spec or {})
        updated["spectrum_format"] = spectrum_format
        updated["amplitude_mode"] = amplitude_mode
        return updated

    rebuilt = _rebuild_traces(model, prefs or UnitPreferences(), _RebuildRules(
        linear=linear,
        is_db=lambda tr: decibel_scale,
        is_squared=is_squared,
        legend=_plain_legend,
        new_spec=new_spec,
        writes_source=True,
        align_in_db=False,
    ))

    new_band_rms_cursors = []
    for c in model.band_rms_cursors:
        if c.kind == "band_rms":
            p = dict(c.processing or {})
            p["amplitude_mode"] = amplitude_mode
            p["spectrum_format"] = spectrum_format
            new_band_rms_cursors.append(replace(c, processing=p))
        else:
            new_band_rms_cursors.append(c)
    return replace(rebuilt, band_rms_cursors=new_band_rms_cursors)


def rebuild_amplitude_mode_display(
    model: PlotModel,
    *,
    amplitude_mode: str = "rms",
    prefs: Optional[UnitPreferences] = None,
) -> PlotModel:
    """
    Re-scales every order-cut or Overall Level trace in ``model`` between RMS
    and Peak. Runs purely in-memory (< 1 ms),
    without disk I/O or DSP recomputation.

    Keyed on each trace's own block kind, not the dock's ``analysis_kind``: a
    dock can carry both kinds at once (an Overall Level set loaded from the
    Result Pool into an order-tracking dock, or an order-cut set loaded into
    an Overall Level dock -- issue #128), and toggling Amplitude in either
    dock's View group must rescale every such trace, not just the ones
    matching this dock's own kind. Any other trace rescales from its own
    ``y_raw``/``source_unit``.
    """
    def linear(tr: Trace):
        block = tr.block
        kind = getattr(block, "kind", None) if block is not None else None
        if kind in RMS_PEAK_CURVE_KINDS:
            raw, raw_unit = block.values, block.value_unit
        else:
            raw, raw_unit = tr.y_raw, tr.source_unit
        return _linear_amplitude_display(raw, raw_unit, amplitude_mode)

    def new_spec(tr: Trace) -> Dict[str, Any]:
        updated = dict(tr.compute_spec or {})
        updated["amplitude_mode"] = amplitude_mode
        return updated

    return _rebuild_traces(model, prefs or UnitPreferences(), _RebuildRules(
        linear=linear,
        is_db=lambda tr: False,
        is_squared=lambda tr: False,
        legend=_kind_legend,
        new_spec=new_spec,
        writes_source=True,
        align_in_db=False,
    ))


def rebuild_with_units(model: PlotModel, prefs: UnitPreferences) -> PlotModel:
    """
    A fresh model with every trace re-scaled from its untouched ``y_raw`` for the
    new global units -- no disk, no DSP. The base curve fixes the primary axis
    unit; a compatible overlay is re-reconciled onto it, an incompatible one
    keeps its own (secondary) unit. Legend text and the ordinate label follow.

    A trace already shown in dB stays in dB, re-derived from its new-unit
    linear value last, off its own pre-rebuild ``unit`` and its
    ``compute_spec["spectrum_format"]``.
    """
    return _rebuild_traces(model, prefs, _RebuildRules(
        linear=lambda tr: (tr.y_raw, tr.source_unit),
        is_db=lambda tr: tr.unit == "dB",
        is_squared=lambda tr: is_squared_format((tr.compute_spec or {}).get("spectrum_format")),
        legend=_plain_legend,
        new_spec=lambda tr: None,
        writes_source=False,
        align_in_db=True,
    ))


def rebuild_with_domain(model: PlotModel, to_quantity: str) -> PlotModel:
    """
    A fresh model with ``x_domain`` set to ``to_quantity`` and every
    projectable trace's ``x`` recomputed from its untouched ``x_raw`` --
    the X-axis counterpart of ``rebuild_with_units``, and for the same reason
   : changing what domain the dock shows is a
    model rebuild, not something ``_draw_all()`` recomputes on every paint.

    A trace whose own quantity cannot be projected onto ``to_quantity`` is
    left exactly as it was -- ``_draw_all()`` is what decides such a trace can no
    longer be drawn, not this function, so its ``x`` is never left dangling in
    a domain nothing points at.
    """
    new_traces: List[Trace] = []
    for tr in model.traces:
        if not tr.x_quantity or tr.x_raw is None or tr.x_quantity == to_quantity:
            new_traces.append(tr)
            continue
        params = tr.compute_spec or {}
        if can_project(tr.x_quantity, to_quantity, params):
            new_traces.append(replace(tr, x=project_x(tr.x_raw, tr.x_quantity, to_quantity, params)))
        else:
            new_traces.append(tr)

    return replace(model, traces=new_traces, x_domain=to_quantity)
