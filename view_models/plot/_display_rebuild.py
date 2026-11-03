"""
Re-scaling a finished ``PlotModel`` in memory -- display settings, RMS/Peak,
global units, X domain -- without disk I/O or DSP recomputation.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, List, Optional, Tuple

import numpy as np

from core.axis_projections import can_project, project_x
from core.block_kinds import KINDS

from ._block_values import BlockValues, resolve_block_values
from ._display_settings import DisplaySettings
from ._plot_model import PlotModel, Trace
from ._trace_display import (
    BaseCurve,
    resolve_base_curve,
    base_trace_index,
    linear_amplitude_display,
    resolve_ordinate,
    resolve_ordinate_quantity,
    build_trace_in_display_settings,
)


def _linear_values(tr: Trace, values: Optional[BlockValues],
                   settings: DisplaySettings) -> Tuple[np.ndarray, str]:
    """
    ``tr``'s (values, unit) before the global-unit conversion in ``settings`` --
    the values an added curve gets (``build_scaled_overlay_trace``): a canonical
    spectrum's Format x Amplitude from its block, an order cut's or an Overall
    Level's RMS/Peak from its block, anything else its own ``y_raw``.
    """
    if values is not None and values.rescaled:
        return values.values, values.unit
    spec = KINDS.get(getattr(tr.block, "kind", None))
    if spec is not None and spec.scales_with_rms_peak:
        return linear_amplitude_display(tr.block.values, tr.block.value_unit, settings.amplitude_mode)
    return tr.y_raw, tr.source_unit


def _shown_trace(tr: Trace, settings: DisplaySettings, against: Optional[BaseCurve]) -> Trace:
    """``tr`` rebuilt from its raw data in ``settings``, placed ``against`` the
    base curve (None: ``tr`` is the base curve)."""
    values = resolve_block_values(tr.block, settings.spectrum_format, settings.spectrum_amplitude_mode)
    y_lin, unit_lin = _linear_values(tr, values, settings)
    db_squared = values.db_is_squared if settings.decibel_scale and values is not None else None
    return build_trace_in_display_settings(
        tr, y_lin, unit_lin, settings.prefs, db_squared=db_squared, against=against)


def build_trace_with_block_numbers(model: PlotModel, trace: Trace, block, settings: DisplaySettings) -> Trace:
    """``trace``, held by ``model``, with the numbers of ``block`` shown in
    ``settings`` where it stands now: its pen, names and channel stay. What lets an
    Adopted curve show its result set's numbers when the set lands second (#921)."""
    axis = block.primary_axis
    x = axis.values
    domain = model.x_domain
    if domain and axis.quantity and domain != axis.quantity and can_project(
            axis.quantity, domain, trace.compute_spec or {}):
        x = project_x(axis.values, axis.quantity, domain, trace.compute_spec or {})
    renumbered = replace(trace, x=x, x_raw=axis.values, y_raw=block.values, source_unit=block.value_unit,
                         block=block, data_block=block)
    if trace.is_base:
        return _shown_trace(renumbered, settings, None)
    base = model.traces[base_trace_index(model)]
    return _shown_trace(renumbered, settings, resolve_base_curve(base, settings.prefs))


def _rebuild_traces(model: PlotModel, settings: DisplaySettings, *,
                    shown_as: Optional[Callable[[Trace], Trace]] = None,
                    base_index: Optional[int] = None) -> PlotModel:
    """
    The one pass over ``model``'s traces: every trace
    is rebuilt from its raw data in ``settings`` as a whole and shown by
    ``build_trace_in_display_settings`` -- dB for a spectrum only, with the formula its block names --
    the base curve (trace ``base_index``, by default the one flagged
    ``is_base``) first fixing what the others are placed against, wherever it
    sits in the list; the ordinate label follows. ``shown_as`` records on a
    trace the display settings it is now shown in.
    """
    if not model.traces:
        return model
    base_idx = base_trace_index(model) if base_index is None else base_index

    def shown(tr: Trace, against: Optional[BaseCurve]) -> Trace:
        return _shown_trace(tr if shown_as is None else shown_as(tr), settings, against)

    base = shown(model.traces[base_idx], None)
    against = resolve_base_curve(base, settings.prefs)
    new_traces = [base if i == base_idx else shown(tr, against) for i, tr in enumerate(model.traces)]
    y_label, y_unit = resolve_ordinate(base)
    return replace(model, traces=new_traces, view=replace(
        model.view, y_label=y_label, y_unit=y_unit, y_quantity=resolve_ordinate_quantity(base)))


def rebuild_with_base(model: PlotModel, base_index: int, settings: DisplaySettings) -> PlotModel:
    """
    ``model`` with trace ``base_index`` as its base curve -- for when the base
    curve left the graph (#693). Every trace is rebuilt from its raw data in
    ``settings`` (the ones the graph last applied), the new base first and
    every other trace placed against it, exactly as if they had been added in
    ``settings`` onto the new base. The ordinate label follows the new base.
    """
    return _rebuild_traces(model, settings, base_index=base_index)


def rebuild_spectrum_with_display_settings(model: PlotModel, settings: DisplaySettings) -> PlotModel:
    """
    Every trace of ``model`` again in ``settings`` after a spectrum Format,
    Amplitude or dB change; each trace and band RMS cursor records
    the new Format x Amplitude. Runs purely in-memory (< 1 ms), without disk
    I/O or DSP recomputation.
    """
    def shown_as(tr: Trace) -> Trace:
        return replace(tr, spectrum_format=settings.spectrum_format,
                       amplitude_mode=settings.spectrum_amplitude_mode)

    rebuilt = _rebuild_traces(model, settings, shown_as=shown_as)

    new_band_rms_cursors = []
    for c in model.band_rms_cursors:
        if c.kind == "band_rms":
            p = dict(c.processing or {})
            p["amplitude_mode"] = settings.spectrum_amplitude_mode
            p["spectrum_format"] = settings.spectrum_format
            new_band_rms_cursors.append(replace(c, processing=p))
        else:
            new_band_rms_cursors.append(c)
    return replace(rebuilt, band_rms_cursors=new_band_rms_cursors)


def rebuild_amplitude_mode_display(model: PlotModel, settings: DisplaySettings) -> PlotModel:
    """
    Every trace of ``model`` again in ``settings`` after an RMS/Peak change
   ; each trace records the new amplitude mode.
    Runs purely in-memory (< 1 ms), without disk I/O or DSP recomputation.

    Peak applies by each trace's own block kind, not the dock's
    ``analysis_kind``: a dock can carry both kinds at once (an Overall Level
    set loaded from the Result Pool into an order-tracking dock, or an
    order-cut set loaded into an Overall Level dock -- issue #128), and
    toggling Amplitude in either dock's View group must rescale every such
    trace. Any other trace keeps the values it was added with (§1.185).
    """
    def shown_as(tr: Trace) -> Trace:
        return replace(tr, amplitude_mode=settings.amplitude_mode)

    return _rebuild_traces(model, settings, shown_as=shown_as)


def rebuild_with_units(model: PlotModel, settings: DisplaySettings) -> PlotModel:
    """
    A fresh model with every trace rebuilt from its raw data in ``settings``
    after a global unit change -- no disk, no DSP. The base curve fixes the
    primary axis unit; a compatible overlay is re-reconciled onto it, an
    incompatible one keeps its own (secondary) unit. Legend text and the
    ordinate label follow; a spectrum in dB is re-derived from its new-unit
    linear value last.
    """
    return _rebuild_traces(model, settings)


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
