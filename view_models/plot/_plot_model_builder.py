"""
Raw arrays + a ``UnitPreferences`` in, a finished ``PlotModel`` out.

The conversion logic that ``graph_dock`` runs inline on every plot -- global
unit scaling, unit-string sanitising, legend text, the primary-vs-secondary
axis decision -- lives here as pure functions instead, so the renderer can be
handed a model it only has to draw. Lives in
``view_models/plot`` because a plot model is presentation state on Floor 3,
importing no Qt and no ``app_context``: the builders are exercised in a plain
unit test with no ``QApplication``. Re-scaling a finished model lives in
``_display_rebuild``; which traces are visible, in ``_visible_traces``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.block_kinds import (
    KIND_ORDER_CUT,
    KIND_OVERALL_LEVEL,
    KIND_SPECTRUM,
    KIND_TIME_RESPONSE,
    META_EFFECTIVE_F_START,
    META_EFFECTIVE_F_STOP,
    PARAM_ORDER,
    STEP_READ,
    spec_for,
)
from core.channel_types import CHANNEL_TYPE_GENERAL_DYNAMIC
from core.curve_recipe import resolve_curve_recipe
from core.units import (
    UnitPreferences,
    strip_channel_name_prefix,
)
from signal_processing.result_blocks import require_uniform_rpm_axis
from view_models.analysis_kinds import (
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTRUM,
    ANALYSIS_TIME,
)

from core.theme import GraphLook, graph_tokens
from ._block_values import resolve_block_values, to_decibels
from ._display_settings import DisplaySettings
from ._trace_display import (
    NO_BASE_CURVE,
    resolve_base_curve,
    base_trace_index,
    linear_amplitude_display,
    resolve_ordinate,
    resolve_ordinate_quantity,
    build_trace_in_display_settings,
)
from ._plot_model import (
    BandRmsCursor,
    Pen,
    PlotModel,
    SpectrogramModel,
    Trace,
    ViewSpec,
)

# The base pen a builder starts with; build_base_model and build_order_cuts_model
# repaint it in the graph's own base_curve_color.
_BASE_CURVE_COLOR = graph_tokens(GraphLook.DARK).base_curve

# result_blocks names a computed block after what it was computed from --
# f"1D Spectrum({name})", f"Waterfall({name})", f"Order {n} [{name}]",
# f"Overall Level({name})" -- so a
# Trace built from one carries that wrapper as its channel_name unless it is
# peeled back off here first. Left wrapped, cache_naming.
# split_channel_base_and_direction (which only understands a plain reader
# label) can't find the direction suffix buried inside the wrapper, and the
# Filter panel's Channel facet showed the whole string, e.g.
# "1D Spectrum(Time for Inverter_Cover:+Z)", as one unrecognised "channel".
_ORDER_CUT_NAME_RE = re.compile(r"^Order\s+[\d.]+\s+\[(.*)\]$")
_WRAPPED_BLOCK_NAME_PREFIXES = ("1D Spectrum(", "Waterfall(", "Overall Level(", "Residual(")


def _channel_identity_source(block_name: str) -> str:
    match = _ORDER_CUT_NAME_RE.match(block_name)
    if match:
        return match.group(1)
    for prefix in _WRAPPED_BLOCK_NAME_PREFIXES:
        if block_name.startswith(prefix) and block_name.endswith(")"):
            return block_name[len(prefix):-1]
    return block_name


def _legend_channel_name(name: str, block: Optional[Any]) -> str:
    """The channel name a curve's Trace carries for its legend: with a block the
    legend names the curve itself (build_legend_text) on the identity name;
    without one the full name is all the curve has, and a display rebuild reads
    it back off the trace -- the same as base curve, as overlay and after any
    rebuild (#755, #757)."""
    if block is None:
        return strip_channel_name_prefix(name)
    return strip_channel_name_prefix(_channel_identity_source(name))


def _channel_type(source_meta: Optional[Dict[str, Any]]) -> str:
    if source_meta:
        return source_meta.get("channel_type", CHANNEL_TYPE_GENERAL_DYNAMIC)
    return CHANNEL_TYPE_GENERAL_DYNAMIC


def _file_name(source_meta: Optional[Dict[str, Any]]) -> str:
    return source_meta.get("file_name", "") if source_meta else ""


def build_compute_spec(block) -> Dict[str, Any]:
    """
    ``Trace.compute_spec`` for a curve computed from ``block`` -- the one recipe
    a live and a stored curve share (#665 C19): the curve recipe the block was
    stamped with (``core.curve_recipe``), empty for a block computed without
    one, plus the order of an order cut, which its own facet and the rpm to
    frequency projection read. ``block.processing`` stays out: it is only for
    drawing (#814).

    Public (not `_compute_spec_for`) because `GraphDock.add_curve`
    needs the same derivation for a caller that hands over `block`/`data_block`
    without a `compute_spec` of its own (issue: Local Filter's Order/Analysis
    type/Parameter set facets going empty for an order-tracking curve added by
    drag-and-drop onto a dock that already has a base curve).
    """
    spec = resolve_curve_recipe(block) or {}
    order = block.provenance.params.get(PARAM_ORDER) if block.provenance else None
    if order is not None:
        spec[PARAM_ORDER] = order
    return spec


def _derive_from_block(block, compute_spec, x_quantity):
    """``compute_spec``/``x_quantity`` a caller did not supply, derived from
    ``block`` -- a time_response read has nothing to derive; every other kind
    has its processing or, as an Imported result, comes from a file."""
    if block is not None and (getattr(block, "processing", None) is not None
                              or block.provenance.step == STEP_READ and block.kind != KIND_TIME_RESPONSE):
        if compute_spec is None:
            compute_spec = build_compute_spec(block)
        if not x_quantity:
            x_quantity = block.primary_axis.quantity
    return compute_spec, x_quantity


def resolve_overlay_display_scaling(
    block,
    *,
    compute_spec: Optional[Dict[str, Any]],
    x_quantity: str,
    y_data: np.ndarray,
    incoming_unit: str,
    spectrum_format: str,
    spectrum_amplitude_mode: str,
    order_cut_amplitude_mode: str,
) -> Tuple[np.ndarray, str, Optional[Dict[str, Any]], str]:
    """
    What `GraphDock.add_curve` needs to know about `block` --
    a possibly-None block a caller (channel drop, order overlay, Result Pool
    load) hands over alongside its own raw `y_data`/`incoming_unit` -- before
    handing both off to `build_overlay_trace`: `compute_spec`/`x_quantity`
    derived from `block` (`build_compute_spec`) when the caller did not already supply
    its own (so Local Filter's Order/Analysis type/Parameter set facets gate
    on it like the dock's own base curve does), and the on-the-fly display
    scaling a canonical spectrum or order-cut block carries instead of
    pre-scaled values.

    The values stay linear, in the block's own unit: dB is applied only after
    the global-unit conversion (`build_scaled_overlay_trace`), so an overlay
    is referenced to the same unit as its base curve (issue #354).

    A block with no `processing` (a time_response read) has nothing to
    derive; `compute_spec`/`x_quantity` pass through unchanged, same as
    `y_data`/`incoming_unit` for a block that is neither a canonical
    spectrum nor an order cut.
    """
    compute_spec, x_quantity = _derive_from_block(block, compute_spec, x_quantity)
    shown = resolve_block_values(block, spectrum_format, spectrum_amplitude_mode)
    if shown is not None and shown.rescaled:
        y_data, incoming_unit = shown.values, shown.unit
    elif block is not None and block.kind == KIND_ORDER_CUT:
        if order_cut_amplitude_mode == "peak":
            y_data, incoming_unit = linear_amplitude_display(block.values, block.value_unit, "peak")
    return y_data, incoming_unit, compute_spec, x_quantity


def traces_kept_after_unload(traces: Sequence[Trace], ref_ids) -> List[Trace]:
    """
    Which of `traces` survive removing every curve read from `ref_ids`
    (result_content.unload_result_sets_from_dock) -- a curve with no
    `result_set_id` (a dropped channel, a live compute, a base curve off a
    measurement) is never touched. An Adopted curve stays as the user's own
    curve (no set, numbers and pen untouched, the channel still dropped), so
    unticking a set switches the set off, not the channel (§1.243).
    """
    ids = set(ref_ids)
    kept = []
    for t in traces:
        if t.result_set_id not in ids:
            kept.append(t)
        elif t.adopted:
            kept.append(replace(t, result_set_id="", adopted=False))
    return kept


def _set_curve_meta(meta: Optional[Dict[str, Any]], source_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The ``meta_ref`` of a curve read off a result set when it is built from its
    block, whose own meta says ``file_path``: the measurement goes under
    ``source_path``, because ``file_path`` is what says a channel is already
    plotted and would refuse the drop of that channel (§1.103)."""
    merged = {**(meta or {}), **(source_meta or {})}
    file_path = merged.pop("file_path", None)
    merged["source_path"] = merged.get("source_path") or file_path
    return merged


def _legend_meta_for_block(block, source_meta):
    """Keep an Imported result's order in the trace identity across display rebuilds."""
    if (block is not None and block.kind == KIND_ORDER_CUT
            and block.provenance.step == STEP_READ):
        return {**(source_meta or block.display_meta()),
                "imported_order": block.provenance.params.get(PARAM_ORDER)}
    return source_meta


def build_time_model(
    *,
    x: np.ndarray,
    y: np.ndarray,
    sensor_name: str,
    y_unit: str,
    source_meta: Optional[Dict[str, Any]] = None,
    prefs: Optional[UnitPreferences] = None,
    block: Optional[Any] = None,
    data_block: Optional[Any] = None,
    db_squared: Optional[bool] = None,
) -> PlotModel:
    """One base curve with no band RMS cursors -- a time record, or (with
    ``db_squared`` set) a spectrum shown in dB."""
    actual_block = data_block if data_block is not None else block
    source_meta = _legend_meta_for_block(actual_block, source_meta)
    clean_name = strip_channel_name_prefix(sensor_name)

    trace = build_trace_in_display_settings(
        Trace(
            x=x, y=y, y_raw=y, x_raw=x,
            channel_type=_channel_type(source_meta),
            file_name=_file_name(source_meta), channel_name=_legend_channel_name(sensor_name, actual_block),
            pen=Pen(color=_BASE_CURVE_COLOR, width=1.0),
            meta_ref=source_meta, block=actual_block, data_block=actual_block,
        ),
        y, y_unit, prefs or UnitPreferences(), db_squared=db_squared,
    )
    y_label, y_unit_label = resolve_ordinate(trace)
    view = ViewSpec(
        title=f"Sensor Record: {clean_name}",
        x_label="Time",
        x_unit="s",
        y_label=y_label,
        y_unit=y_unit_label,
        y_quantity=resolve_ordinate_quantity(trace),
    )

    return PlotModel(traces=[trace], view=view, band_rms_cursors=[], analysis_kind=ANALYSIS_TIME)


def build_spectrum_model(
    block,
    prefs: Optional[UnitPreferences] = None,
    spectrum_format: str = "linear",
    amplitude_mode: str = "rms",
    decibel_scale: bool = False,
) -> PlotModel:
    """
    The model behind ``GraphDock.plot_blocks`` for a spectrum block.

    Supports on-the-fly scaling of canonical spectral data and optional
    dB scale matching spectrograms.
    """
    shown = resolve_block_values(block, spectrum_format, amplitude_mode)
    y_values, display_unit = shown.values, shown.unit

    axis = block.primary_axis
    model = build_time_model(
        x=axis.values,
        y=y_values,
        sensor_name=block.name,
        y_unit=display_unit,
        source_meta=block.display_meta(),
        prefs=prefs,
        block=block, data_block=block,
        db_squared=shown.db_is_squared if decibel_scale else None,
    )

    clean_name = strip_channel_name_prefix(block.name)

    model.view.title = f"Spectrum: {clean_name}"
    model.view.x_label = "Frequency"
    model.view.x_unit = axis.unit
    if len(axis.values) > 0:
        model.view.x_range = (0.0, float(np.max(axis.values)))
    eff_amp, eff_fmt = shown.amplitude_mode, shown.spectrum_format

    model.traces[0] = replace(
        model.traces[0],
        x_raw=axis.values,
        x_quantity=axis.quantity,
        compute_spec=build_compute_spec(block),
        spectrum_format=eff_fmt, amplitude_mode=eff_amp,
        block=block, data_block=block,
    )
    model.x_domain = axis.quantity

    model.band_rms_cursors = [
        BandRmsCursor(
            kind="band_rms",
            enabled=False,
            band=None,
            processing={
                "amplitude_mode": eff_amp,
                "spectrum_format": eff_fmt,
                "acf": block.processing.acf if block.processing else 1.0,
                "ecf_linear": block.processing.ecf_linear if block.processing else 1.0,
                "fft_size": block.processing.fft_size if block.processing else None,
            },
        )
    ]
    model.analysis_kind = ANALYSIS_SPECTRUM
    return model


def build_order_cuts_model(
    blocks: Sequence,
    prefs: Optional[UnitPreferences] = None,
    amplitude_mode: str = "rms",
    *,
    x: Optional[np.ndarray] = None,
    y: Optional[np.ndarray] = None,
    source_label: str = "",
    incoming_unit: str = "",
    source_meta: Optional[Dict[str, Any]] = None,
    compute_spec: Optional[Dict[str, Any]] = None,
    x_quantity: str = "",
    title: Optional[str] = None,
    base_curve_color: str,
) -> PlotModel:
    """
    The model behind an order dock's landed cuts: the first cut is the
    base curve, every further cut is an overlay added by the same rule
    ``add_curve`` uses (carousel pen, secondary axis when the
    unit will not reconcile with the base).

    ``x`` .. ``title`` override the base curve as an ``add_curve`` caller
    hands it over; left out, each is read off the first cut.

    Applies sqrt(2) scaling when amplitude_mode == "peak".
    """
    first = blocks[0]
    x = first.primary_axis.values if x is None else x
    x_quantity = x_quantity or first.primary_axis.quantity
    base_y, base_unit = linear_amplitude_display(
        first.values if y is None else y, incoming_unit or first.value_unit, amplitude_mode)
    model = build_time_model(
        x=x, y=base_y, sensor_name=source_label or first.name, y_unit=base_unit,
        source_meta=source_meta or first.display_meta(), prefs=prefs, block=first,
    )
    model.traces[0].pen = replace(model.traces[0].pen, color=base_curve_color)
    model.view.x_label = "Speed"
    model.view.x_unit = first.primary_axis.unit
    model.view.title = title or f"Order Tracking: {first.source.file_name}"
    model.analysis_kind = ANALYSIS_ORDERS
    model.traces[0] = replace(
        model.traces[0], x_raw=x, x_quantity=x_quantity,
        compute_spec=compute_spec or build_compute_spec(first), block=first,
    )
    model.x_domain = x_quantity

    for overlay_index, block in enumerate(blocks[1:]):
        overlay_y, overlay_unit = linear_amplitude_display(block.values, block.value_unit, amplitude_mode)
        model.traces.append(
            build_overlay_trace(
                model,
                overlay_index=overlay_index,
                x=block.primary_axis.values,
                y=overlay_y,
                source_label=block.name,
                incoming_unit=overlay_unit,
                source_meta=block.display_meta(),
                prefs=prefs,
                compute_spec=build_compute_spec(block),
                x_quantity=block.primary_axis.quantity,
                block=block,
            )
        )
    return model


def overall_level_effective_band(block) -> Tuple[float, float]:
    """The (f_start, f_stop) actually integrated for `block`."""
    lo = block.metadata.get(META_EFFECTIVE_F_START)
    hi = block.metadata.get(META_EFFECTIVE_F_STOP)
    return (float(lo), float(hi))


def overall_level_band_differs_from_dock(model: PlotModel, block) -> bool:
    """
    True when `block`'s effective band differs from any Overall Level curve
    already on `model` -- the pure half of ADR §1.62 point 14 (the caller,
    the Overall Level lane of ``run_channel_drop``, decides whether and what to log
    from this). At the Full Bandwidth default (point 13) neither legend names
    a band, so two files at different sample rates would otherwise integrate
    different bands with no visible sign of it in the graph.
    """
    if block.provenance.step == STEP_READ:
        return False        # an Imported level carries no band
    new_band = overall_level_effective_band(block)
    for trace in model.traces:
        existing = trace.block
        if existing is None or getattr(existing, "kind", None) != KIND_OVERALL_LEVEL:
            continue
        if existing.provenance.step == STEP_READ:
            continue        # an Imported level carries no band to compare
        if overall_level_effective_band(existing) != new_band:
            return True
    return False


def _level_trace(block, amplitude_mode: str) -> Tuple[Trace, np.ndarray, str]:
    """
    An Overall Level or Residual block as the graph shows it, before it is
    placed: its identity as a ``Trace`` and its linear values with RMS/Peak
    applied -- the one preparation behind the base curve and every
    overlay, so the same data can never get two Peak scalings or two legends.
    The unit, axis and legend come from ``build_trace_in_display_settings``; the pen is the
    placing builder's.
    """
    axis = block.primary_axis
    source_meta = block.display_meta()
    display_y, display_unit = linear_amplitude_display(block.values, block.value_unit, amplitude_mode)
    trace = Trace(
        x=axis.values, y=display_y, y_raw=display_y, x_raw=axis.values,
        channel_type=_channel_type(source_meta), file_name=_file_name(source_meta),
        channel_name=strip_channel_name_prefix(_channel_identity_source(block.name)),
        meta_ref=source_meta, x_quantity=axis.quantity, compute_spec=build_compute_spec(block),
        amplitude_mode=amplitude_mode, block=block, data_block=block,
    )
    return trace, display_y, display_unit


def build_overall_level_overlay_trace(
    model: PlotModel, *, overlay_index: int, block, prefs: Optional[UnitPreferences] = None,
    amplitude_mode: str = "rms", result_set_id: str = "",
    source_meta: Optional[Dict[str, Any]] = None,
) -> Trace:
    """
    One Overall Level overlay curve (issue #125), dropped from a channel --
    possibly from a different file -- onto an already-open Overall Level dock,
    or read off a Result Pool set (``result_set_id`` non-empty, ADR §1.62 point
    22 / issue #128). Same legend rule as the base curve
    (``build_overall_level_model``) and the same primary/secondary axis split
    ``build_overlay_trace`` uses for every other analysis, so a unit that will
    not reconcile with the base curve still lands somewhere visible instead of
    being silently rescaled onto it. Amplitude RMS/Peak is a display setting,
    same sqrt(2) rule and unit convention (``core.units.format_order_unit``,
    applied only for Peak) as an order cut.
    """
    trace, display_y, display_unit = _level_trace(block, amplitude_mode)
    if result_set_id:
        trace = replace(trace, result_set_id=result_set_id, meta_ref=_set_curve_meta(trace.meta_ref, source_meta))
    return _place_overlay(model, trace, display_y, display_unit,
                          prefs or UnitPreferences(), overlay_index=overlay_index)


def build_overall_level_model(
    block, prefs: Optional[UnitPreferences] = None,
    amplitude_mode: str = "rms", result_set_id: str = "",
) -> PlotModel:
    """
    The model behind a landed Overall Level curve: one curve,
    speed (or time) on x, band RMS energy on y.

    The legend names the curve "OAL" after the channel, with the band only
    when it differs from the default (``build_legend_text``, ADR §1.181).

    Amplitude RMS/Peak is a display setting, not a recompute (ADR §1.60,
    §1.62 point 5) -- ``result_set_id`` lets a curve read off the Result Pool
    (``gui.handlers.result_content``) carry the same membership tag a
    dropped/loaded order cut does.
    """
    trace, display_y, display_unit = _level_trace(block, amplitude_mode)
    trace = build_trace_in_display_settings(
        replace(trace, pen=Pen(color=_BASE_CURVE_COLOR, width=1.0), result_set_id=result_set_id),
        display_y, display_unit, prefs or UnitPreferences(),
    )
    axis = block.primary_axis
    y_label, y_unit = resolve_ordinate(trace)
    view = ViewSpec(
        title=f"Overall Level: {trace.channel_name}",
        x_label="Speed" if axis.quantity == "rpm" else "Time", x_unit=axis.unit,
        y_label=y_label, y_unit=y_unit, y_quantity=resolve_ordinate_quantity(trace),
    )

    model = PlotModel(traces=[trace], view=view, band_rms_cursors=[], analysis_kind=ANALYSIS_OVERALL_LEVEL)
    model.x_domain = axis.quantity
    return model


def _spectrum_base(block, settings: DisplaySettings, **_curve) -> PlotModel:
    return build_spectrum_model(
        block, settings.prefs,
        spectrum_format=settings.spectrum_format,
        amplitude_mode=settings.spectrum_amplitude_mode,
        decibel_scale=settings.decibel_scale,
    )


def _overall_level_base(block, settings: DisplaySettings, **_curve) -> PlotModel:
    return build_overall_level_model(block, settings.prefs, amplitude_mode=settings.amplitude_mode)


def _order_cut_base(block, settings: DisplaySettings, *, x, y, source_label, incoming_unit,
                    source_meta, compute_spec, x_quantity) -> PlotModel:
    file_name = (source_meta or block.display_meta()).get("file_name", "")
    return build_order_cuts_model(
        [block], settings.prefs, amplitude_mode=settings.amplitude_mode,
        x=x, y=y, source_label=source_label, incoming_unit=incoming_unit, source_meta=source_meta,
        compute_spec=compute_spec, x_quantity=x_quantity,
        title=f"Order Compare: [{file_name}]" if file_name else None,
        base_curve_color=_BASE_CURVE_COLOR,
    )


def _time_base(block, settings: DisplaySettings, *, x, y, source_label, incoming_unit,
               source_meta, compute_spec, x_quantity) -> PlotModel:
    model = build_time_model(
        x=x, y=y, sensor_name=source_label, y_unit=incoming_unit, source_meta=source_meta,
        prefs=settings.prefs, block=block, data_block=block,
    )
    compute_spec, x_quantity = _derive_from_block(block, compute_spec, x_quantity)
    replacements = {}
    if compute_spec is not None:
        replacements["compute_spec"] = compute_spec
    if x_quantity:
        replacements.update(x_quantity=x_quantity, x_raw=x)
        model.x_domain = x_quantity
    if replacements:
        model.traces[0] = replace(model.traces[0], **replacements)
    return model


# Which builder an empty graph's base curve gets, by block kind; no block,
# or any other block kind, is a time record (_time_base).
_BASE_MODEL_BUILDERS = {
    KIND_SPECTRUM: _spectrum_base,
    KIND_ORDER_CUT: _order_cut_base,
    KIND_OVERALL_LEVEL: _overall_level_base,
}


def build_base_model(
    block,
    settings: DisplaySettings,
    *,
    x: np.ndarray,
    y: np.ndarray,
    source_label: str,
    incoming_unit: str,
    source_meta: Optional[Dict[str, Any]],
    compute_spec: Optional[Dict[str, Any]] = None,
    x_quantity: str = "",
    result_set_id: str = "",
    title: Optional[str] = None,
    base_curve_color: str,
) -> PlotModel:
    """
    The model of an empty graph, its one base curve built by the block kind of ``block``
    (``_BASE_MODEL_BUILDERS``). ``x`` .. ``x_quantity`` are the curve as the
    caller hands it over, already filled in from ``block``; a spectrum and an
    Overall Level are built from the block alone. ``title`` and
    ``result_set_id``, when given, are stamped on whatever the builder made.
    """
    build = _BASE_MODEL_BUILDERS.get(getattr(block, "kind", None), _time_base)
    model = build(
        block, settings, x=x, y=y, source_label=source_label, incoming_unit=incoming_unit,
        source_meta=source_meta, compute_spec=compute_spec, x_quantity=x_quantity,
    )
    model.traces[0].pen = replace(model.traces[0].pen, color=base_curve_color)
    if title:
        model.view.title = title
    if result_set_id:
        model.traces[0] = replace(model.traces[0], result_set_id=result_set_id,
                                  meta_ref=_set_curve_meta(model.traces[0].meta_ref, source_meta))
    return model


def _overlay_legend_source(source_label: str, source_meta: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """The file name and raw channel name an overlay's legend is built from."""
    # "[file] channel" only when it genuinely starts with the bracketed prefix;
    # splitting on the first "]" unconditionally broke a channel whose own name
    # contains "]" (audit 02 / 9.3).
    if source_label.startswith("[") and "]" in source_label:
        f_name, raw_ch_name = source_label.split("]", 1)
        return f_name.replace("[", "").strip(), raw_ch_name
    return _file_name(source_meta), source_label


def _place_overlay(model: PlotModel, trace: Trace, linear_y: np.ndarray, linear_unit: str,
                   prefs: UnitPreferences, *, overlay_index: int,
                   db_squared: Optional[bool] = None) -> Trace:
    """``trace`` as an overlay of ``model``: on the carousel pen of
    ``overlay_index`` (not ``len(model.traces)``, so the Nth overlay always gets
    the Nth look regardless of how the base curve is counted), shown by
    ``build_trace_in_display_settings`` against the model's base curve."""
    # A model without curves has no base to place against: the curve stands alone.
    against = (resolve_base_curve(model.traces[base_trace_index(model)], prefs)
               if model.traces else NO_BASE_CURVE)
    return build_trace_in_display_settings(
        replace(trace, pen=Pen(color="", width=1.0, slot=overlay_index)),
        linear_y, linear_unit, prefs, db_squared=db_squared, against=against,
    )


def build_overlay_trace(
    model: PlotModel,
    *,
    overlay_index: int,
    x: np.ndarray,
    y: np.ndarray,
    source_label: str,
    incoming_unit: str,
    source_meta: Optional[Dict[str, Any]] = None,
    prefs: Optional[UnitPreferences] = None,
    compute_spec: Optional[Dict[str, Any]] = None,
    x_quantity: str = "",
    result_set_id: str = "",
    block: Optional[Any] = None,
    db_squared: Optional[bool] = None,
) -> Trace:
    """
    One overlay curve for ``model``, without rebuilding the rest of it -- order
    cuts and an overlay drop both add curves one at a time in a loop.
    ``db_squared`` set shows the curve in dB (with the dB formula it names).

    ``overlay_index`` (not ``len(model.traces)``) is the pen's carousel slot.
    """
    source_meta = _legend_meta_for_block(block, source_meta)
    f_name, raw_ch_name = _overlay_legend_source(source_label, source_meta)
    trace = Trace(
        x=x, y=y, y_raw=y, x_raw=x, channel_type=_channel_type(source_meta),
        file_name=f_name, channel_name=_legend_channel_name(raw_ch_name, block), meta_ref=source_meta,
        compute_spec=compute_spec, x_quantity=x_quantity, result_set_id=result_set_id,
        block=block, data_block=block,
    )
    return _place_overlay(model, trace, y, incoming_unit, prefs or UnitPreferences(),
                          overlay_index=overlay_index, db_squared=db_squared)


def build_scaled_overlay_trace(
    model: PlotModel,
    *,
    overlay_index: int,
    x: np.ndarray,
    y: np.ndarray,
    source_label: str,
    incoming_unit: str,
    source_meta: Optional[Dict[str, Any]] = None,
    prefs: Optional[UnitPreferences] = None,
    compute_spec: Optional[Dict[str, Any]] = None,
    x_quantity: str = "",
    result_set_id: str = "",
    block: Optional[Any] = None,
    spectrum_format: str = "linear",
    spectrum_amplitude_mode: str = "rms",
    spectrum_decibel_scale: bool = False,
    amplitude_mode: str = "rms",
) -> Trace:
    """
    One overlay curve added to an already-open dock (channel drop, order
    overlay, Result Pool load, live compute) -- raw `x`/`y`/`incoming_unit`
    plus an optional `block`, with the dock's display settings applied.
    `amplitude_mode` is the dock's own View/Amplitude setting
    (`resolve_display_settings`), used for an order cut and an Overall Level.

    A caller handing over `block` always passes that block's own raw
    values/unit alongside it -- the display scaling is unconditional on that
    assumption, not guarded by an identity/unit sniff, which would silently
    mis-fire for a caller that broke it instead. A block with no
    compute_spec/x_quantity of the caller's own gets them derived here, so
    Local Filter's Order/Analysis type/Parameter set facets gate on it like
    the dock's base curve instead of dropping it into "(Empty)".
    """
    y, incoming_unit, compute_spec, x_quantity = resolve_overlay_display_scaling(
        block,
        compute_spec=compute_spec,
        x_quantity=x_quantity,
        y_data=y,
        incoming_unit=incoming_unit,
        spectrum_format=spectrum_format,
        spectrum_amplitude_mode=spectrum_amplitude_mode,
        order_cut_amplitude_mode=amplitude_mode,
    )
    if block is not None and spec_for(block.kind).is_level:
        # A level curve is built from the block itself, same as the dock's
        # own base curve (build_overall_level_model), rather than from
        # x/y/source_label (issue #125). Amplitude RMS/Peak applies the same way a
        # dropped/loaded order cut applies its own (§1.62 point 22, issue #128).
        return build_overall_level_overlay_trace(
            model, overlay_index=overlay_index, block=block, prefs=prefs,
            amplitude_mode=amplitude_mode, result_set_id=result_set_id, source_meta=source_meta,
        )
    shown = resolve_block_values(block, spectrum_format, spectrum_amplitude_mode)
    trace = build_overlay_trace(
        model,
        overlay_index=overlay_index,
        x=x,
        y=y,
        source_label=source_label,
        incoming_unit=incoming_unit,
        source_meta=source_meta,
        prefs=prefs,
        compute_spec=compute_spec,
        x_quantity=x_quantity,
        result_set_id=result_set_id,
        block=block,
        db_squared=shown.db_is_squared if spectrum_decibel_scale and shown is not None else None,
    )
    if shown is not None and shown.rescaled:
        # Recorded on the curve, not in its compute_spec: how it is shown is no part of its recipe.
        trace = replace(trace, spectrum_format=spectrum_format, amplitude_mode=spectrum_amplitude_mode)
    return trace


def build_spectrogram_model(
    block,
    color_scale: str = "Linear",
    spectrum_format: str = "linear",
    amplitude_mode: str = "rms",
    decibel_scale: Optional[bool] = None,
) -> SpectrogramModel:
    """
    The model ``GraphSpectrogram`` holds and ``SpectrogramDock`` draws.

    The dB conversion that ``plot_spectrogram_block`` did inline moves here so
    the renderer only ever draws ``image`` as given. ``color_scale`` is a
    display-only parameter (§1.21) -- passed in from ``app_context`` at build
    time, never stored on disk. The matrix is left in (frequency, z) order; the
    renderer transposes it for the ``ImageItem``.
    """
    # A saved result set reaches the image here too, not only a fresh compute.
    require_uniform_rpm_axis(block)
    frequency_axis, z_axis = block.axes

    shown = resolve_block_values(block, spectrum_format, amplitude_mode)
    matrix = np.asarray(shown.values, dtype=np.float64)

    is_db = (decibel_scale is True) or ("dB" in color_scale)
    if is_db:
        matrix = to_decibels(matrix, shown.db_is_squared)
        effective_color_scale = color_scale if "dB" in color_scale else "dB (Log)"
    else:
        effective_color_scale = color_scale

    clean_name = strip_channel_name_prefix(_channel_identity_source(block.name))
    mag_unit = "dB" if is_db else (shown.unit if shown else getattr(block, "value_unit", ""))
    return SpectrogramModel(
        value_unit=mag_unit,
        image=matrix,
        freqs=np.asarray(frequency_axis.values, dtype=np.float64),
        zvals=np.asarray(z_axis.values, dtype=np.float64),
        z_label=z_axis.label,
        z_unit=z_axis.unit,
        z_quantity=z_axis.quantity,
        color_scale=effective_color_scale,
        title=f"Vibration Spectrogram: {clean_name}",
        block=block,
        compute_spec=build_compute_spec(block),
    )
