"""
Re-scaling a finished ``PlotModel`` in memory -- display settings, RMS/Peak,
global units, X domain -- without disk I/O or DSP recomputation (ADR §1.60).
"""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional

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


def rebuild_spectrum_with_display_settings(
    model: PlotModel,
    *,
    spectrum_format: str = "linear",
    amplitude_mode: str = "rms",
    decibel_scale: bool = False,
    prefs: Optional[UnitPreferences] = None,
) -> PlotModel:
    """
    Re-scales a spectrum PlotModel on the fly from its canonical blocks (ADR §1.60).
    Runs purely in-memory (< 1 ms), without disk I/O or DSP recomputation.
    """
    prefs = prefs or UnitPreferences()
    new_traces: List[Trace] = []
    base_unit: Optional[str] = None
    base_channel_type: Optional[str] = None
    base_idx = _base_trace_index(model)

    for i, tr in enumerate(model.traces):
        if tr.block is not None and getattr(tr.block, "is_canonical", False):
            y_disp, unit_disp = tr.block.to_display_values(
                spectrum_format=spectrum_format, amplitude_mode=amplitude_mode
            )
        else:
            y_disp, unit_disp = tr.y_raw, tr.source_unit

        render_y, target_unit = convert_signal_to_global_unit(
            y_disp, unit_disp, tr.channel_type, prefs
        )
        sanitized = sanitize_unit_string(target_unit)

        if decibel_scale:
            if tr.block is not None and getattr(tr.block, "is_canonical", False):
                is_squared = is_squared_format(spectrum_format)
            else:
                is_squared = bool(tr.compute_spec and is_squared_format(tr.compute_spec.get("spectrum_format")))
            final_y = to_decibels(render_y, is_squared)
            final_unit = "dB"
            legend_text = build_legend_text(
                tr.file_name, tr.channel_name, "dB", tr.meta_ref
            )
        else:
            final_y = render_y
            final_unit = sanitized
            legend_text = build_legend_text(
                tr.file_name, tr.channel_name, sanitized, tr.meta_ref
            )

        updated_compute = dict(tr.compute_spec or {})
        updated_compute["spectrum_format"] = spectrum_format
        updated_compute["amplitude_mode"] = amplitude_mode

        is_base = tr.is_base or (i == base_idx)
        if is_base:
            base_unit = final_unit
            base_channel_type = tr.channel_type
            new_traces.append(replace(
                tr,
                y=final_y,
                y_raw=y_disp,
                source_unit=unit_disp,
                unit=final_unit,
                label=legend_text,
                compute_spec=updated_compute,
                is_base=True,
                axis="primary",
            ))
            continue

        axis = resolve_overlay_axis(
            base_unit,
            sanitized,
            base_is_db=decibel_scale,
            overlay_is_db=decibel_scale,
        )
        if axis == "primary" and not decibel_scale:
            aligned_y = convert_numeric_array(render_y, from_unit=sanitized, to_unit=base_unit)
            legend_text = build_legend_text(
                tr.file_name, tr.channel_name, base_unit, tr.meta_ref
            )
            new_traces.append(replace(
                tr,
                y=aligned_y,
                y_raw=y_disp,
                source_unit=unit_disp,
                unit=base_unit,
                label=legend_text,
                compute_spec=updated_compute,
                axis="primary",
            ))
        else:
            new_traces.append(replace(
                tr,
                y=final_y,
                y_raw=y_disp,
                source_unit=unit_disp,
                unit=final_unit,
                label=legend_text,
                compute_spec=updated_compute,
                axis=axis,
            ))

    if base_unit is not None:
        if decibel_scale:
            view = replace(model.view, y_label="Amplitude", y_unit="dB")
        else:
            view = replace(
                model.view,
                y_label=_y_axis_label(base_channel_type or ""),
                y_unit=format_display_unit(base_unit),
            )
    else:
        view = model.view

    new_band_rms_cursors = []
    for c in model.band_rms_cursors:
        if c.kind == "band_rms":
            p = dict(c.processing or {})
            p["amplitude_mode"] = amplitude_mode
            p["spectrum_format"] = spectrum_format
            new_band_rms_cursors.append(replace(c, processing=p))
        else:
            new_band_rms_cursors.append(c)

    return replace(model, traces=new_traces, view=view, band_rms_cursors=new_band_rms_cursors)


def rebuild_amplitude_mode_display(
    model: PlotModel,
    *,
    amplitude_mode: str = "rms",
    prefs: Optional[UnitPreferences] = None,
) -> PlotModel:
    """
    Re-scales every order-cut or Overall Level trace in ``model`` between RMS
    and Peak (ADR §1.60, §1.62 point 22). Runs purely in-memory (< 1 ms),
    without disk I/O or DSP recomputation.

    Keyed on each trace's own block kind, not the dock's ``analysis_kind``: a
    dock can carry both kinds at once (an Overall Level set loaded from the
    Result Pool into an order-tracking dock, or an order-cut set loaded into
    an Overall Level dock -- issue #128), and toggling Amplitude in either
    dock's View group must rescale every such trace, not just the ones
    matching this dock's own kind. A trace with no block (older callers that
    never attached one) falls back to its own ``y_raw``/``source_unit``,
    which for these two kinds is already the untouched Linear RMS value.
    """
    prefs = prefs or UnitPreferences()
    new_traces: List[Trace] = []
    base_unit: Optional[str] = None
    base_channel_type: Optional[str] = None
    base_idx = _base_trace_index(model)

    for i, tr in enumerate(model.traces):
        block = tr.block
        kind = getattr(block, "kind", None) if block is not None else None
        is_level_curve = kind in LEVEL_CURVE_KINDS

        if kind in RMS_PEAK_CURVE_KINDS:
            raw_unscaled = block.values
            raw_unscaled_unit = block.value_unit
        else:
            raw_unscaled = tr.y_raw
            raw_unscaled_unit = tr.source_unit

        scaled_y, order_unit = _linear_amplitude_display(raw_unscaled, raw_unscaled_unit, amplitude_mode, block=block)

        render_y, target_unit = convert_signal_to_global_unit(
            scaled_y, order_unit, tr.channel_type, prefs
        )
        sanitized = sanitize_unit_string(target_unit)

        updated_compute = dict(tr.compute_spec or {})
        updated_compute["amplitude_mode"] = amplitude_mode

        def _legend(unit_value: str) -> str:
            base_legend = build_legend_text(
                tr.file_name, tr.channel_name, unit_value, tr.meta_ref
            )
            return _level_legend_text(block, base_legend) if is_level_curve else base_legend

        is_base = tr.is_base or (i == base_idx)
        if is_base:
            base_unit = sanitized
            base_channel_type = tr.channel_type
            new_traces.append(replace(
                tr,
                y=render_y,
                y_raw=scaled_y,
                source_unit=order_unit,
                unit=sanitized,
                label=_legend(sanitized),
                compute_spec=updated_compute,
                is_base=True,
                axis="primary",
            ))
            continue

        axis = resolve_overlay_axis(base_unit, sanitized)
        if axis == "primary":
            aligned_y = convert_numeric_array(render_y, from_unit=sanitized, to_unit=base_unit)
            new_traces.append(replace(
                tr,
                y=aligned_y,
                y_raw=scaled_y,
                source_unit=order_unit,
                unit=base_unit,
                label=_legend(base_unit),
                compute_spec=updated_compute,
                axis="primary",
            ))
        else:
            new_traces.append(replace(
                tr,
                y=render_y,
                y_raw=scaled_y,
                source_unit=order_unit,
                unit=sanitized,
                label=_legend(sanitized),
                compute_spec=updated_compute,
                axis=axis,
            ))

    if base_unit is not None:
        view = replace(
            model.view,
            y_label=_y_axis_label(base_channel_type or ""),
            y_unit=format_display_unit(base_unit),
        )
    else:
        view = model.view

    return replace(model, traces=new_traces, view=view)


def rebuild_with_units(model: PlotModel, prefs: UnitPreferences) -> PlotModel:
    """
    A fresh model with every trace re-scaled from its untouched ``y_raw`` for the
    new global units -- no disk, no DSP. The base curve fixes the primary axis
    unit; a compatible overlay is re-reconciled onto it, an incompatible one
    keeps its own (secondary) unit. Legend text and the ordinate label follow.

    A trace already shown in dB stays in dB, re-derived from its new-unit
    linear value last, off its own pre-rebuild ``unit`` and its
    ``compute_spec["spectrum_format"]`` (ADR §1.89).
    """
    new_traces: List[Trace] = []
    base_unit: Optional[str] = None
    base_channel_type: Optional[str] = None
    base_is_db = False

    def _to_db_if_needed(y: np.ndarray, unit: str, was_db: bool, is_squared: bool):
        if not was_db:
            return y, unit
        return to_decibels(y, is_squared), "dB"

    base_idx = _base_trace_index(model)

    for i, tr in enumerate(model.traces):
        render_y, target_unit = convert_signal_to_global_unit(
            tr.y_raw, tr.source_unit, tr.channel_type, prefs
        )
        sanitized = sanitize_unit_string(target_unit)
        was_db = tr.unit == "dB"
        is_squared = is_squared_format((tr.compute_spec or {}).get("spectrum_format"))

        is_base = tr.is_base or (i == base_idx)
        if is_base:
            base_unit = sanitized
            base_channel_type = tr.channel_type
            base_is_db = was_db
            final_y, final_unit = _to_db_if_needed(render_y, sanitized, was_db, is_squared)
            legend = build_legend_text(
                tr.file_name, tr.channel_name, final_unit, tr.meta_ref
            )
            new_traces.append(replace(
                tr,
                y=final_y,
                unit=final_unit,
                label=legend,
                is_base=True,
                axis="primary",
            ))
            continue

        axis = resolve_overlay_axis(
            base_unit,
            sanitized,
            base_is_db=base_is_db,
            overlay_is_db=was_db,
        )
        if axis == "primary" and base_unit and check_units_compatibility(base_unit, sanitized):
            aligned_y = convert_numeric_array(render_y, from_unit=sanitized, to_unit=base_unit)
            final_y, final_unit = _to_db_if_needed(aligned_y, base_unit, was_db, is_squared)
            legend = build_legend_text(
                tr.file_name, tr.channel_name, final_unit, tr.meta_ref
            )
            new_traces.append(replace(tr, y=final_y, unit=final_unit, label=legend, axis="primary"))
        else:
            final_y, final_unit = _to_db_if_needed(render_y, sanitized, was_db, is_squared)
            legend = build_legend_text(
                tr.file_name, tr.channel_name, final_unit, tr.meta_ref
            )
            new_traces.append(replace(
                tr,
                y=final_y,
                unit=final_unit,
                label=legend,
                axis=axis,
            ))

    if base_unit is not None:
        if base_is_db:
            view = replace(model.view, y_label="Amplitude", y_unit="dB")
        else:
            view = replace(
                model.view,
                y_label=_y_axis_label(base_channel_type or ""),
                y_unit=format_display_unit(base_unit),
            )
    else:
        view = model.view

    return replace(model, traces=new_traces, view=view)


def rebuild_with_domain(model: PlotModel, to_quantity: str) -> PlotModel:
    """
    A fresh model with ``x_domain`` set to ``to_quantity`` and every
    projectable trace's ``x`` recomputed from its untouched ``x_raw`` --
    the X-axis counterpart of ``rebuild_with_units``, and for the same reason
    (ARCHITECTURE_DECISIONS §1.30): changing what domain the dock shows is a
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
