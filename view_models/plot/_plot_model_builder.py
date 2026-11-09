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
    KIND_ORDER_RESIDUAL,
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
    convert_signal_to_global_unit,
    resolve_db_reference,
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
from ._block_values import build_trace_shown_as, resolve_block_values, resolve_curve_values, to_decibels
from ._display_settings import DisplaySettings
from ._trace_display import (
    NO_BASE_CURVE,
    resolve_base_curve,
    base_trace_index,
    resolve_ordinate,
    resolve_ordinate_quantity,
    build_trace_in_display_settings,
)
from ._plot_model import (
    Pen,
    PlotModel,
    SpectrogramModel,
    Trace,
    ViewSpec,
)

# The base pen a builder starts with; build_base_model
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
    needs the same derivation for a caller that hands over `block`
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


def _curve_trace(*, x: np.ndarray, y: np.ndarray, source_label: str,
                 source_meta: Optional[Dict[str, Any]], block: Optional[Any]) -> Trace:
    """
    The identity of a curve -- file, channel, channel type, meta, block -- with
    its raw ``x`` / ``y``, before it is shown: the one rule behind the base
    curve and every overlay (#891), so a channel has the same legend and Local
    Filter channel wherever it lands. A ``source_label`` of a channel drop,
    "[file] channel", names the file and the channel apart.
    """
    source_meta = _legend_meta_for_block(block, source_meta)
    f_name, raw_ch_name = _legend_source(source_label, source_meta)
    return Trace(
        x=x, y=y, y_raw=y, x_raw=x, channel_type=_channel_type(source_meta),
        file_name=f_name, channel_name=_legend_channel_name(raw_ch_name, block), meta_ref=source_meta,
        block=block,
    )


def build_time_model(
    *,
    x: np.ndarray,
    y: np.ndarray,
    sensor_name: str,
    y_unit: str,
    source_meta: Optional[Dict[str, Any]] = None,
    prefs: Optional[UnitPreferences] = None,
    block: Optional[Any] = None,
    db_squared: Optional[bool] = None,
) -> PlotModel:
    """One base curve with no band RMS cursors -- a time record, or (with
    ``db_squared`` set) a spectrum shown in dB."""
    clean_name = strip_channel_name_prefix(sensor_name)

    trace = build_trace_in_display_settings(
        replace(_curve_trace(x=x, y=y, source_label=sensor_name, source_meta=source_meta, block=block),
                pen=Pen(color=_BASE_CURVE_COLOR, width=1.0)),
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

    return PlotModel(traces=[trace], view=view, analysis_kind=ANALYSIS_TIME)


def build_spectrum_model(block, settings: DisplaySettings = DisplaySettings()) -> PlotModel:
    """
    The model of a graph whose first curve is a spectrum block, shown in
    ``settings``: a canonical spectrum scaled on the fly, in dB
    when ``settings`` say so, as a spectrogram is.
    """
    values = resolve_curve_values(block, settings, block.values, block.value_unit)

    axis = block.primary_axis
    model = build_time_model(
        x=axis.values,
        y=values.values,
        sensor_name=block.name,
        y_unit=values.unit,
        source_meta=block.display_meta(),
        prefs=settings.prefs,
        block=block,
        db_squared=values.db_squared,
    )

    clean_name = strip_channel_name_prefix(block.name)

    model.view.title = f"Spectrum: {clean_name}"
    model.view.x_label = "Frequency"
    model.view.x_unit = axis.unit
    if len(axis.values) > 0:
        model.view.x_range = (0.0, float(np.max(axis.values)))
    model.traces[0] = replace(
        build_trace_shown_as(model.traces[0], values),
        x_raw=axis.values,
        x_quantity=axis.quantity,
        compute_spec=build_compute_spec(block),
        block=block,
    )
    model.x_domain = axis.quantity

    model.analysis_kind = ANALYSIS_SPECTRUM
    return model


def build_order_cut_model(
    block,
    settings: DisplaySettings = DisplaySettings(),
    *,
    x: Optional[np.ndarray] = None,
    y: Optional[np.ndarray] = None,
    source_label: str = "",
    incoming_unit: str = "",
    source_meta: Optional[Dict[str, Any]] = None,
    compute_spec: Optional[Dict[str, Any]] = None,
    x_quantity: str = "",
) -> PlotModel:
    """
    The model of a graph whose first curve is an order cut -- or a Residual,
    which an Order tracking graph draws as it draws a cut: speed
    on x, RMS/Peak a display setting.

    ``x`` .. ``x_quantity`` are the curve as an ``add_curve`` caller hands it
    over; left out, each is read off ``block``.
    """
    x = block.primary_axis.values if x is None else x
    x_quantity = x_quantity or block.primary_axis.quantity
    values = resolve_curve_values(block, settings, block.values if y is None else y,
                                  incoming_unit or block.value_unit)
    model = build_time_model(
        x=x, y=values.values, sensor_name=source_label or block.name, y_unit=values.unit,
        source_meta=source_meta or block.display_meta(), prefs=settings.prefs, block=block,
    )
    model.view.x_label = "Speed"
    model.view.x_unit = block.primary_axis.unit
    model.view.title = f"Order Tracking: {block.source.file_name}"
    model.analysis_kind = ANALYSIS_ORDERS
    model.traces[0] = replace(
        build_trace_shown_as(model.traces[0], values), x_raw=x, x_quantity=x_quantity,
        compute_spec=compute_spec or build_compute_spec(block), block=block,
    )
    model.x_domain = x_quantity
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


def _level_trace(block, settings: DisplaySettings) -> Tuple[Trace, np.ndarray, str]:
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
    values = resolve_curve_values(block, settings, block.values, block.value_unit)
    trace = build_trace_shown_as(Trace(
        x=axis.values, y=values.values, y_raw=values.values, x_raw=axis.values,
        channel_type=_channel_type(source_meta), file_name=_file_name(source_meta),
        channel_name=strip_channel_name_prefix(_channel_identity_source(block.name)),
        meta_ref=source_meta, x_quantity=axis.quantity, compute_spec=build_compute_spec(block),
        block=block,
    ), values)
    return trace, values.values, values.unit


def build_overall_level_overlay_trace(
    model: PlotModel, *, overlay_index: int, block, settings: DisplaySettings = DisplaySettings(),
    result_set_id: str = "", source_meta: Optional[Dict[str, Any]] = None,
) -> Trace:
    """
    One Overall Level overlay curve (issue #125), dropped from a channel --
    possibly from a different file -- onto an already-open Overall Level dock,
    or read off a Result Pool set (``result_set_id`` non-empty, ADR §1.62 point
    22 / issue #128). Same legend rule as the base curve
    (``build_overall_level_model``) and the same primary/secondary axis split
    every other overlay takes, so a unit that will
    not reconcile with the base curve still lands somewhere visible instead of
    being silently rescaled onto it. Amplitude RMS/Peak is a display setting,
    same sqrt(2) rule and unit convention (``core.units.format_order_unit``,
    applied only for Peak) as an order cut.
    """
    trace, display_y, display_unit = _level_trace(block, settings)
    if result_set_id:
        trace = replace(trace, result_set_id=result_set_id, meta_ref=_set_curve_meta(trace.meta_ref, source_meta))
    return _place_overlay(model, trace, display_y, display_unit,
                          settings.prefs, overlay_index=overlay_index)


def build_overall_level_model(block, settings: DisplaySettings = DisplaySettings(),
                              result_set_id: str = "") -> PlotModel:
    """
    The model behind a landed Overall Level curve: one curve,
    speed (or time) on x, band RMS energy on y.

    The legend names the curve "OAL" after the channel, with the band only
    when it differs from the default (``build_legend_text``, plot §1.296).

    Amplitude RMS/Peak is a display setting, not a recompute (ADR §1.60,
    §1.62 point 5) -- ``result_set_id`` lets a curve read off the Result Pool
    (``gui.handlers.result_content``) carry the same membership tag a
    dropped/loaded order cut does.
    """
    trace, display_y, display_unit = _level_trace(block, settings)
    trace = build_trace_in_display_settings(
        replace(trace, pen=Pen(color=_BASE_CURVE_COLOR, width=1.0), result_set_id=result_set_id),
        display_y, display_unit, settings.prefs,
    )
    axis = block.primary_axis
    y_label, y_unit = resolve_ordinate(trace)
    view = ViewSpec(
        title=f"Overall Level: {trace.channel_name}",
        x_label="Speed" if axis.quantity == "rpm" else "Time", x_unit=axis.unit,
        y_label=y_label, y_unit=y_unit, y_quantity=resolve_ordinate_quantity(trace),
    )

    model = PlotModel(traces=[trace], view=view, analysis_kind=ANALYSIS_OVERALL_LEVEL)
    model.x_domain = axis.quantity
    return model


def _spectrum_base(block, settings: DisplaySettings, **_curve) -> PlotModel:
    return build_spectrum_model(block, settings)


def _overall_level_base(block, settings: DisplaySettings, **_curve) -> PlotModel:
    return build_overall_level_model(block, settings)


def _time_base(block, settings: DisplaySettings, *, x, y, source_label, incoming_unit,
               source_meta, compute_spec, x_quantity) -> PlotModel:
    model = build_time_model(
        x=x, y=y, sensor_name=source_label, y_unit=incoming_unit, source_meta=source_meta,
        prefs=settings.prefs, block=block,
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


# Which builder an empty graph's base curve gets, by block kind -- the one
# place a kind's view (title, X axis) and analysis kind are chosen, whichever way
# the curve reaches the graph (#891). A Residual is drawn as an order cut is
#; no block, or any other block kind, is a time record (_time_base).
_BASE_MODEL_BUILDERS = {
    KIND_SPECTRUM: _spectrum_base,
    KIND_ORDER_CUT: build_order_cut_model,
    KIND_ORDER_RESIDUAL: build_order_cut_model,
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


def _legend_source(source_label: str, source_meta: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """The file name and raw channel name a curve's legend is built from."""
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
        legend_config=model.legend_config,
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
    trace = replace(_curve_trace(x=x, y=y, source_label=source_label, source_meta=source_meta, block=block),
                    compute_spec=compute_spec, x_quantity=x_quantity, result_set_id=result_set_id)
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
    compute_spec: Optional[Dict[str, Any]] = None,
    x_quantity: str = "",
    result_set_id: str = "",
    block: Optional[Any] = None,
    settings: DisplaySettings = DisplaySettings(),
) -> Trace:
    """
    One overlay curve added to an already-open dock (channel drop, order
    overlay, Result Pool load, live compute) -- raw `x`/`y`/`incoming_unit`
    plus an optional `block`, shown in the dock's display `settings` by the
    one rule a curve of its block kind is shown by (`resolve_curve_values`).

    A caller handing over `block` always passes that block's own raw
    values/unit alongside it -- the display scaling is unconditional on that
    assumption, not guarded by an identity/unit sniff, which would silently
    mis-fire for a caller that broke it instead. A block with no
    compute_spec/x_quantity of the caller's own gets them derived here
    (`build_compute_spec`), so Local Filter's Order/Analysis type/Parameter
    set facets gate on it like the dock's base curve instead of dropping it
    into "(Empty)".
    """
    if block is not None and spec_for(block.kind).is_level:
        # A level curve is built from the block itself, same as the dock's
        # own base curve (build_overall_level_model), rather than from
        # x/y/source_label (issue #125). Amplitude RMS/Peak applies the same way a
        # dropped/loaded order cut applies its own (§1.62 point 22, issue #128).
        return build_overall_level_overlay_trace(
            model, overlay_index=overlay_index, block=block, settings=settings,
            result_set_id=result_set_id, source_meta=source_meta,
        )
    compute_spec, x_quantity = _derive_from_block(block, compute_spec, x_quantity)
    values = resolve_curve_values(block, settings, y, incoming_unit)
    trace = build_overlay_trace(
        model,
        overlay_index=overlay_index,
        x=x,
        y=values.values,
        source_label=source_label,
        incoming_unit=values.unit,
        source_meta=source_meta,
        prefs=settings.prefs,
        compute_spec=compute_spec,
        x_quantity=x_quantity,
        result_set_id=result_set_id,
        block=block,
        db_squared=values.db_squared,
    )
    # Recorded on the curve, not in its compute_spec: how it is shown is no part of its recipe.
    return build_trace_shown_as(trace, values)


def build_spectrogram_model(
    block,
    color_scale: str = "Linear",
    spectrum_format: str = "linear",
    amplitude_mode: str = "rms",
    decibel_scale: Optional[bool] = None,
    prefs: Optional[UnitPreferences] = None,
) -> SpectrogramModel:
    """
    The model ``GraphSpectrogram`` holds and ``SpectrogramDock`` draws.

    The colour values are shown in the global Display unit of ``prefs``, as a
    curve's values are (§1.89, #947), and dB applies after that conversion,
    against the dB reference of ``prefs``.

    The dB conversion that ``plot_spectrogram_block`` did inline moves here so
    the renderer only ever draws ``z`` as given. ``color_scale`` is a
    display-only parameter (§1.21) -- passed in from ``app_context`` at build
    time, never stored on disk. The matrix is left in (frequency, tracking)
    order -- (y, x); the renderer transposes it for the ``ImageItem``.
    """
    # A saved result set reaches the image here too, not only a fresh compute.
    require_uniform_rpm_axis(block)
    frequency_axis, tracking_axis = block.axes

    shown = resolve_block_values(block, spectrum_format, amplitude_mode)
    matrix, shown_unit = convert_signal_to_global_unit(
        np.asarray(shown.values, dtype=np.float64), shown.unit,
        getattr(block, "channel_type", CHANNEL_TYPE_GENERAL_DYNAMIC), prefs or UnitPreferences(),
    )
    matrix = np.asarray(matrix, dtype=np.float64)

    is_db = (decibel_scale is True) or ("dB" in color_scale)
    if is_db:
        reference = resolve_db_reference(
            shown_unit, getattr(block, "channel_type", CHANNEL_TYPE_GENERAL_DYNAMIC), prefs)
        matrix = to_decibels(matrix, shown.db_is_squared, reference)
        effective_color_scale = color_scale if "dB" in color_scale else "dB (Log)"
    else:
        effective_color_scale = color_scale

    clean_name = strip_channel_name_prefix(_channel_identity_source(block.name))
    mag_unit = "dB" if is_db else shown_unit
    return SpectrogramModel(
        z_unit=mag_unit,
        z=matrix,
        y=np.asarray(frequency_axis.values, dtype=np.float64),
        x=np.asarray(tracking_axis.values, dtype=np.float64),
        x_label=tracking_axis.label,
        x_unit=tracking_axis.unit,
        x_quantity=tracking_axis.quantity,
        color_scale=effective_color_scale,
        title=f"Vibration Spectrogram: {clean_name}",
        block=block,
        compute_spec=build_compute_spec(block),
    )
