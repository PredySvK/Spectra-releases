"""
Raw arrays + a ``UnitPreferences`` in, a finished ``PlotModel`` out.

The conversion logic that ``graph_dock`` runs inline on every plot -- global
unit scaling, unit-string sanitising, legend text, the primary-vs-secondary
axis decision -- lives here as pure functions instead, so the renderer can be
handed a model it only has to draw (ARCHITECTURE_DECISIONS §1.7). Lives in
``view_models/plot`` because a plot model is presentation state on Floor 3,
importing no Qt and no ``app_context``: the builders are exercised in a plain
unit test with no ``QApplication``. Re-scaling a finished model lives in
``_display_rebuild``; which traces are visible, in ``_visible_traces``.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.block_kinds import (
    KIND_ORDER_CUT,
    LEVEL_CURVE_KINDS,
    KIND_ORDER_RESIDUAL,
    KIND_OVERALL_LEVEL,
    KIND_SPECTRUM,
    META_EFFECTIVE_F_START,
    META_EFFECTIVE_F_STOP,
    PARAM_F_START,
    PARAM_F_STOP,
    PARAM_ORDER,
    STEP_READ,
)
from core.units import (
    UnitPreferences,
    check_units_compatibility,
    convert_numeric_array,
    convert_signal_to_global_unit,
    format_order_unit,
    is_squared_format,
    sanitize_unit_string,
    strip_channel_name_prefix,
)
from signal_processing.result_blocks import require_uniform_rpm_axis
from view_models.analysis_kinds import (
    ANALYSIS_ORDERS,
    ANALYSIS_OVERALL_LEVEL,
    ANALYSIS_SPECTRUM,
    ANALYSIS_TIME,
)

from ._display_settings import DisplaySettings
from ._graph_colours import carousel_pen_spec
from ._legend_settings import build_legend_text, format_display_unit
from ._plot_model import (
    BandRmsCursor,
    Pen,
    PlotModel,
    SpectrogramModel,
    Trace,
    ViewSpec,
)

# Ordinate-axis title per channel type (core.units.determine_channel_type).
# "general_dynamic" and anything unmapped fall back to the neutral "Amplitude".
_AXIS_QUANTITY_LABELS = {
    "accelerometer": "Acceleration",
    "microphone": "Sound Pressure",
    "voltage": "Voltage",
    "tacho": "Speed",
}

_BASE_CURVE_COLOR = "#ffcc00"

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


def to_decibels(values: np.ndarray, is_squared: bool) -> np.ndarray:
    """
    The one dB conversion rule for a spectral quantity (ADR §1.60): a squared
    (power/PSD) format is already energy, so it only needs 10*log10; a linear
    (amplitude) format needs 20*log10 to land on the same dB scale. Callers
    work out ``is_squared`` themselves -- a canonical block asks the requested
    display format, a legacy pre-scaled one asks what it was already computed as.
    """
    safe = np.clip(values, 1e-12, None)
    return 10.0 * np.log10(safe) if is_squared else 20.0 * np.log10(safe)


def _channel_identity_source(block_name: str) -> str:
    match = _ORDER_CUT_NAME_RE.match(block_name)
    if match:
        return match.group(1)
    for prefix in _WRAPPED_BLOCK_NAME_PREFIXES:
        if block_name.startswith(prefix) and block_name.endswith(")"):
            return block_name[len(prefix):-1]
    return block_name


def _channel_type(source_meta: Optional[Dict[str, Any]]) -> str:
    if source_meta:
        return source_meta.get("channel_type", "general_dynamic")
    return "general_dynamic"


def _file_name(source_meta: Optional[Dict[str, Any]]) -> str:
    return source_meta.get("file_name", "") if source_meta else ""


def _y_axis_label(channel_type: str) -> str:
    return _AXIS_QUANTITY_LABELS.get(channel_type, "Amplitude")


def build_compute_spec(block) -> Dict[str, Any]:
    """
    ``Trace.compute_spec`` for a curve computed from ``block`` -- everything
    ``block.processing`` (SpectralProcessing) carries, plus the order number
    for an order cut or band parameters for an overall level, whose defining
    parameters live on provenance instead.

    Public (not `_compute_spec_for`) because `GraphDock.add_curve`
    needs the same derivation for a caller that hands over `block`/`data_block`
    without a `compute_spec` of its own (issue: Local Filter's Order/Analysis
    type/Parameter set facets going empty for an order-tracking curve added by
    drag-and-drop onto a dock that already has a base curve) -- the only other
    caller of this was already using the private name from the same module, so
    the rename costs nothing there.
    """
    spec = dataclasses.asdict(block.processing) if block.processing else {}
    params = block.provenance.params if block.provenance else {}
    for key in (PARAM_ORDER, PARAM_F_START, PARAM_F_STOP):
        if key in params:
            spec[key] = params[key]
    return spec


def _derive_from_processing(block, compute_spec, x_quantity):
    """``compute_spec``/``x_quantity`` a caller did not supply, derived from
    ``block.processing`` -- a block without one has nothing to derive."""
    if block is not None and (getattr(block, "processing", None) is not None
                              or block.kind == KIND_ORDER_CUT):
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
    derived from `block.processing` when the caller did not already supply
    its own (so Local Filter's Order/Analysis type/Parameter set facets gate
    on it like the dock's own base curve does), and the on-the-fly display
    scaling a canonical spectrum or order-cut block carries instead of
    pre-scaled values (ADR §1.60 / §1.62 point 22).

    The values stay linear, in the block's own unit: dB is applied only after
    the global-unit conversion (`build_scaled_overlay_trace`), so an overlay
    is referenced to the same unit as its base curve (issue #354).

    A block with no `processing` (a time_response read) has nothing to
    derive; `compute_spec`/`x_quantity` pass through unchanged, same as
    `y_data`/`incoming_unit` for a block that is neither a canonical
    spectrum nor an order cut.
    """
    compute_spec, x_quantity = _derive_from_processing(block, compute_spec, x_quantity)
    if block is not None and getattr(block, "is_canonical", False) and block.kind == KIND_SPECTRUM:
        y_data, incoming_unit = block.to_display_values(spectrum_format, spectrum_amplitude_mode)
        if compute_spec is not None:
            compute_spec = dict(compute_spec)
            compute_spec["spectrum_format"] = spectrum_format
            compute_spec["amplitude_mode"] = spectrum_amplitude_mode
    elif block is not None and block.kind == KIND_ORDER_CUT:
        if order_cut_amplitude_mode == "peak":
            y_data, incoming_unit = _linear_amplitude_display(block.values, block.value_unit, "peak", block=block)
    return y_data, incoming_unit, compute_spec, x_quantity


def traces_kept_after_unload(traces: Sequence[Trace], ref_ids) -> List[Trace]:
    """
    Which of `traces` survive removing every curve read from `ref_ids`
    (result_content.unload_result_sets_from_dock) -- a curve with no
    `result_set_id` (a dropped channel, a live compute, a base curve off a
    measurement) is never touched.
    """
    ids = set(ref_ids)
    return [t for t in traces if t.result_set_id not in ids]


def amplitude_mode_for_kind(
    analysis_kind: str,
    order_tracking_amplitude_mode: str,
    overall_level_amplitude_mode: str,
) -> str:
    """
    A dock's own View/Amplitude setting (ADR §1.62 point 22), keyed on the
    dock's own kind -- so an order cut dropped onto an Overall Level dock (or
    the reverse, issue #128) picks up whatever RMS/Peak that dock is already
    showing rather than the dropped curve's own ribbon tab.
    """
    return order_tracking_amplitude_mode if analysis_kind == ANALYSIS_ORDERS else overall_level_amplitude_mode


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
) -> PlotModel:
    """One time-record base curve, no band RMS cursors."""
    actual_block = data_block if data_block is not None else block
    source_meta = _legend_meta_for_block(actual_block, source_meta)
    prefs = prefs or UnitPreferences()
    clean_name = strip_channel_name_prefix(sensor_name)
    identity_name = strip_channel_name_prefix(_channel_identity_source(sensor_name))
    channel_type = _channel_type(source_meta)
    f_name = _file_name(source_meta)

    render_y, target_unit = convert_signal_to_global_unit(y, y_unit, channel_type, prefs)
    display_unit = sanitize_unit_string(target_unit)
    # identity_name, not clean_name: the legend must read the same after a
    # rebuild, which rebuilds it from the trace's channel_name.
    legend_text = build_legend_text(
        f_name, identity_name, display_unit, source_meta
    )

    trace = Trace(
        x=x,
        y=render_y,
        y_raw=y,
        x_raw=x,
        source_unit=y_unit,
        channel_type=channel_type,
        unit=display_unit,
        label=legend_text,
        file_name=f_name,
        channel_name=identity_name,
        axis="primary",
        is_base=True,
        pen=Pen(color=_BASE_CURVE_COLOR, width=1.0, style="solid"),
        meta_ref=source_meta,
        block=actual_block, data_block=actual_block,
    )

    view = ViewSpec(
        title=f"Sensor Record: {clean_name}",
        x_label="Time",
        x_unit="s",
        y_label=_y_axis_label(channel_type),
        y_unit=format_display_unit(display_unit),
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

    Supports on-the-fly scaling of canonical spectral data (ADR §1.60) and optional
    dB scale matching spectrograms.
    """
    if getattr(block, "is_canonical", False):
        y_values, display_unit = block.to_display_values(
            spectrum_format=spectrum_format, amplitude_mode=amplitude_mode
        )
    else:
        y_values = block.values
        display_unit = block.value_unit

    axis = block.primary_axis
    model = build_time_model(
        x=axis.values,
        y=y_values,
        sensor_name=block.name,
        y_unit=display_unit,
        source_meta=block.display_meta(),
        prefs=prefs,
        block=block, data_block=block,
    )

    clean_name = strip_channel_name_prefix(block.name)
    f_name = _file_name(block.display_meta())

    if decibel_scale:
        if getattr(block, "is_canonical", False):
            is_squared = is_squared_format(spectrum_format)
        else:
            is_squared = bool(block.processing and is_squared_format(block.processing.spectrum_format))
        y_db = to_decibels(model.traces[0].y, is_squared)
        legend_text = build_legend_text(
            f_name, model.traces[0].channel_name, "dB", block.display_meta()
        )
        model.traces[0] = replace(
            model.traces[0],
            y=y_db,
            unit="dB",
            label=legend_text,
            block=block, data_block=block,
        )
        model.view.y_label = "Amplitude"
        model.view.y_unit = "dB"

    model.view.title = f"Spectrum: {clean_name}"
    model.view.x_label = "Frequency"
    model.view.x_unit = axis.unit
    if len(axis.values) > 0:
        model.view.x_range = (0.0, float(np.max(axis.values)))
    eff_amp = amplitude_mode if getattr(block, "is_canonical", False) else (
        block.processing.amplitude_mode if block.processing else "rms"
    )
    eff_fmt = spectrum_format if getattr(block, "is_canonical", False) else (
        block.processing.spectrum_format if block.processing else "linear"
    )

    compute_spec = build_compute_spec(block)
    compute_spec["spectrum_format"] = eff_fmt
    compute_spec["amplitude_mode"] = eff_amp

    model.traces[0] = replace(
        model.traces[0],
        x_raw=axis.values,
        x_quantity=axis.quantity,
        compute_spec=compute_spec,
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
) -> PlotModel:
    """
    The model behind ``Workspace.plot_order_cuts``: the first cut is the
    base curve, every further cut is an overlay added by the same rule
    ``add_curve`` uses (carousel pen, secondary axis when the
    unit will not reconcile with the base).

    ``x`` .. ``title`` override the base curve as an ``add_curve`` caller
    hands it over; left out, each is read off the first cut.

    Applies sqrt(2) scaling when amplitude_mode == "peak" (ADR §1.60).
    """
    first = blocks[0]
    x = first.primary_axis.values if x is None else x
    x_quantity = x_quantity or first.primary_axis.quantity
    base_y, base_unit = _linear_amplitude_display(
        first.values if y is None else y, incoming_unit or first.value_unit, amplitude_mode, block=first)
    model = build_time_model(
        x=x, y=base_y, sensor_name=source_label or first.name, y_unit=base_unit,
        source_meta=source_meta or first.display_meta(), prefs=prefs, block=first,
    )
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
        overlay_y, overlay_unit = _linear_amplitude_display(block.values, block.value_unit, amplitude_mode, block=block)
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


def _level_legend_text(block, base_legend: str) -> str:
    """
    \"OAL\" plus the band, but only when it is not the Full Bandwidth default --
    shared by the base curve (``build_overall_level_model``) and every overlay
    curve (``build_overall_level_overlay_trace``) so the two can never drift
    into two slightly different band-naming rules (ADR §1.62 point 13). A
    Parameter Set's identity is the *requested* band (``provenance.params``),
    but a changed band is shown with the *effective* one (``metadata``) --
    what was actually integrated over this file after clipping to its
    Nyquist. A Residual rides the same builders and reads "Residual ..."
    (ADR §1.141): its band is always the default one.
    """
    if block.kind == KIND_ORDER_RESIDUAL:
        return f"Residual {base_legend}"
    params = block.provenance.params if block.provenance else {}
    f_start = params.get(PARAM_F_START)
    f_stop = params.get(PARAM_F_STOP)
    if f_start == 10.0 and f_stop is None:
        return f"OAL {base_legend}"
    eff_lo = block.metadata.get(META_EFFECTIVE_F_START)
    eff_hi = block.metadata.get(META_EFFECTIVE_F_STOP)
    return f"OAL {eff_lo:g}–{eff_hi:g} Hz {base_legend}"


def overall_level_effective_band(block) -> Tuple[float, float]:
    """The (f_start, f_stop) actually integrated for `block` (ADR §1.62 point 9)."""
    lo = block.metadata.get(META_EFFECTIVE_F_START)
    hi = block.metadata.get(META_EFFECTIVE_F_STOP)
    return (float(lo), float(hi))


def overall_level_band_differs_from_dock(model: PlotModel, block) -> bool:
    """
    True when `block`'s effective band differs from any Overall Level curve
    already on `model` -- the pure half of ADR §1.62 point 14 (the caller,
    the Overall Level drop renderer in ``channel_drop.py``, decides whether and what to log
    from this). At the Full Bandwidth default (point 13) neither legend names
    a band, so two files at different sample rates would otherwise integrate
    different bands with no visible sign of it in the graph.
    """
    new_band = overall_level_effective_band(block)
    for trace in model.traces:
        existing = trace.block
        if existing is None or getattr(existing, "kind", None) != KIND_OVERALL_LEVEL:
            continue
        if overall_level_effective_band(existing) != new_band:
            return True
    return False


def _linear_amplitude_display(values: np.ndarray, value_unit: str, amplitude_mode: str, *, block=None):
    """
    The shared RMS<->Peak display rule for an order cut or an Overall Level
    block (ADR §1.60, §1.62 point 5): Peak = sqrt(2) * RMS, unit suffixed via
    ``format_order_unit``. RMS passes ``values``/``value_unit`` through
    untouched -- the unit is whatever the block/trace already carries, not
    forced into a canonical \"unit RMS\" spelling, so a caller comparing against
    an un-suffixed stored unit (e.g. a legacy \"g\") does not see it change.
    An Imported result has no known RMS basis, so its amplitude stays as read.
    """
    if block is not None and block.processing is None and block.provenance.step == STEP_READ:
        return values, value_unit
    if amplitude_mode == "peak":
        return values * np.sqrt(2.0), format_order_unit(value_unit, "linear", amplitude_mode)
    return values, value_unit


def resolve_overlay_axis(
    base_unit: Optional[str],
    overlay_unit: str,
    *,
    base_is_db: bool = False,
    overlay_is_db: bool = False,
) -> str:
    """Decide whether an overlay trace belongs on the 'primary' or 'secondary' axis (#355).

    An overlay shares the primary axis when both the base and overlay curves are
    shown in dB, or when both are linear and their units are compatible
    (e.g. g RMS and m/s^2 RMS). In all other cases (different physical quantities
    or dB mixed with linear), the overlay is routed to the secondary axis.
    """
    if base_is_db and overlay_is_db:
        return "primary"
    if not base_is_db and not overlay_is_db and base_unit and check_units_compatibility(base_unit, overlay_unit):
        return "primary"
    return "secondary"


def build_overall_level_overlay_trace(
    model: PlotModel, *, overlay_index: int, block, prefs: Optional[UnitPreferences] = None,
    amplitude_mode: str = "rms", result_set_id: str = "",
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
    prefs = prefs or UnitPreferences()
    axis = block.primary_axis
    source_meta = block.display_meta()
    channel_type = _channel_type(source_meta)
    f_name = _file_name(source_meta)
    clean_name = strip_channel_name_prefix(_channel_identity_source(block.name))

    display_y, display_value_unit = _linear_amplitude_display(block.values, block.value_unit, amplitude_mode)
    render_y, target_unit = convert_signal_to_global_unit(
        display_y, display_value_unit, channel_type, prefs
    )
    incoming_unit = sanitize_unit_string(target_unit)
    base_legend = build_legend_text(
        f_name, clean_name, incoming_unit, source_meta
    )
    legend_text = _level_legend_text(block, base_legend)

    base_unit = model.traces[0].unit if model.traces else incoming_unit
    hex_color, style_name = carousel_pen_spec(overlay_index)
    pen = Pen(color=hex_color, width=1.0, style=style_name)
    compute_spec = build_compute_spec(block)
    compute_spec["amplitude_mode"] = amplitude_mode
    compute_spec["tracking_mode"] = axis.quantity

    if resolve_overlay_axis(base_unit, incoming_unit) == "primary":
        final_y = convert_numeric_array(render_y, from_unit=incoming_unit, to_unit=base_unit)
        return Trace(
            x=axis.values, y=final_y, y_raw=display_y, x_raw=axis.values,
            source_unit=display_value_unit, channel_type=channel_type,
            unit=base_unit, label=legend_text, file_name=f_name,
            channel_name=clean_name, axis="primary", is_base=False, pen=pen,
            meta_ref=source_meta, x_quantity=axis.quantity, compute_spec=compute_spec,
            result_set_id=result_set_id, block=block, data_block=block,
        )

    return Trace(
        x=axis.values, y=render_y, y_raw=display_y, x_raw=axis.values,
        source_unit=display_value_unit, channel_type=channel_type,
        unit=incoming_unit, label=legend_text, file_name=f_name,
        channel_name=clean_name, axis="secondary", is_base=False, pen=pen,
        meta_ref=source_meta, x_quantity=axis.quantity, compute_spec=compute_spec,
        result_set_id=result_set_id, block=block, data_block=block,
    )


def build_overall_level_model(
    block, prefs: Optional[UnitPreferences] = None,
    amplitude_mode: str = "rms", result_set_id: str = "",
) -> PlotModel:
    """
    The model behind ``Workspace.plot_overall_level_block``: one curve,
    speed (or time) on x, band RMS energy on y.

    The legend leads with \"OAL\", and only names the band when it differs from
    the default (F min 10 Hz, Full Bandwidth): a Parameter Set's identity is
    the *requested* band (``provenance.params``), but a changed band is shown
    with the *effective* one (``metadata``) -- what was actually integrated
    over this file after clipping to its Nyquist (ADR §1.62 point 13).

    Amplitude RMS/Peak is a display setting, not a recompute (ADR §1.60,
    §1.62 point 5) -- ``result_set_id`` lets a curve read off the Result Pool
    (``gui.handlers.result_content``) carry the same membership tag a
    dropped/loaded order cut does.
    """
    axis = block.primary_axis
    source_meta = block.display_meta()
    channel_type = _channel_type(source_meta)
    f_name = _file_name(source_meta)
    clean_name = strip_channel_name_prefix(_channel_identity_source(block.name))

    display_y, display_value_unit = _linear_amplitude_display(block.values, block.value_unit, amplitude_mode)
    render_y, target_unit = convert_signal_to_global_unit(
        display_y, display_value_unit, channel_type, prefs or UnitPreferences()
    )
    display_unit = sanitize_unit_string(target_unit)
    base_legend = build_legend_text(
        f_name, clean_name, display_unit, source_meta
    )
    legend_text = _level_legend_text(block, base_legend)

    compute_spec = build_compute_spec(block)
    compute_spec["amplitude_mode"] = amplitude_mode
    compute_spec["tracking_mode"] = axis.quantity

    trace = Trace(
        x=axis.values, y=render_y, y_raw=display_y, x_raw=axis.values,
        source_unit=display_value_unit, channel_type=channel_type,
        unit=display_unit, label=legend_text, file_name=f_name,
        channel_name=clean_name, axis="primary", is_base=True,
        pen=Pen(color=_BASE_CURVE_COLOR, width=1.0, style="solid"),
        meta_ref=source_meta, x_quantity=axis.quantity,
        compute_spec=compute_spec, result_set_id=result_set_id,
        block=block, data_block=block,
    )

    x_label = "Speed" if axis.quantity == "rpm" else "Time"
    view = ViewSpec(
        title=f"Overall Level: {clean_name}",
        x_label=x_label, x_unit=axis.unit,
        y_label=_y_axis_label(channel_type),
        y_unit=format_display_unit(display_unit),
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
    )


def _time_base(block, settings: DisplaySettings, *, x, y, source_label, incoming_unit,
               source_meta, compute_spec, x_quantity) -> PlotModel:
    model = build_time_model(
        x=x, y=y, sensor_name=source_label, y_unit=incoming_unit, source_meta=source_meta,
        prefs=settings.prefs, block=block, data_block=block,
    )
    compute_spec, x_quantity = _derive_from_processing(block, compute_spec, x_quantity)
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
    if title:
        model.view.title = title
    if result_set_id:
        model.traces[0] = replace(model.traces[0], result_set_id=result_set_id)
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
) -> Trace:
    """
    One overlay curve for ``model``, without rebuilding the rest of it -- order
    cuts and an overlay drop both add curves one at a time in a loop.

    ``overlay_index`` (not ``len(model.traces)``) drives the pen carousel, so
    the Nth overlay always gets the Nth colour regardless of how the base curve
    is counted.
    """
    prefs = prefs or UnitPreferences()

    source_meta = _legend_meta_for_block(block, source_meta)
    f_name, raw_ch_name = _overlay_legend_source(source_label, source_meta)
    clean_ch_name = strip_channel_name_prefix(raw_ch_name)
    identity_ch_name = strip_channel_name_prefix(_channel_identity_source(raw_ch_name))
    channel_type = _channel_type(source_meta)
    hex_color, style_name = carousel_pen_spec(overlay_index)

    render_y, converted_incoming_unit = convert_signal_to_global_unit(
        y, incoming_unit, channel_type, prefs
    )
    sanitized_incoming = sanitize_unit_string(converted_incoming_unit)
    base_unit = model.traces[0].unit if model.traces else sanitized_incoming

    pen = Pen(color=hex_color, width=1.0, style=style_name)

    if resolve_overlay_axis(base_unit, sanitized_incoming) == "primary":
        final_y = convert_numeric_array(render_y, from_unit=sanitized_incoming, to_unit=base_unit)
        legend_text = build_legend_text(
            f_name, clean_ch_name, base_unit, source_meta
        )
        return Trace(
            x=x, y=final_y, y_raw=y, x_raw=x, source_unit=incoming_unit, channel_type=channel_type,
            unit=base_unit, label=legend_text, file_name=f_name, channel_name=identity_ch_name,
            axis="primary", is_base=False, pen=pen, meta_ref=source_meta, compute_spec=compute_spec,
            x_quantity=x_quantity, result_set_id=result_set_id, block=block, data_block=block,
        )

    legend_text = build_legend_text(
        f_name, clean_ch_name, sanitized_incoming, source_meta
    )
    return Trace(
        x=x, y=render_y, y_raw=y, x_raw=x, source_unit=incoming_unit, channel_type=channel_type,
        unit=sanitized_incoming, label=legend_text, file_name=f_name, channel_name=identity_ch_name,
        axis="secondary", is_base=False, pen=pen, meta_ref=source_meta, compute_spec=compute_spec,
        x_quantity=x_quantity, result_set_id=result_set_id, block=block, data_block=block,
    )


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
    (`amplitude_mode_for_kind`), used for an order cut and an Overall Level.

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
    if block is not None and block.kind in LEVEL_CURVE_KINDS:
        # Overall Level's legend ("OAL ...", ADR §1.62 point 13) is not the
        # generic "[file] channel" build_overlay_trace produces -- built from
        # the block itself, same as the dock's own base curve
        # (build_overall_level_model), rather than from x/y/source_label
        # (issue #125). Amplitude RMS/Peak applies the same way a
        # dropped/loaded order cut applies its own (§1.62 point 22, issue #128).
        return build_overall_level_overlay_trace(
            model, overlay_index=overlay_index, block=block, prefs=prefs,
            amplitude_mode=amplitude_mode, result_set_id=result_set_id,
        )
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
    )
    if not (
        spectrum_decibel_scale and block is not None
        and getattr(block, "is_canonical", False) and block.kind == KIND_SPECTRUM
    ):
        return trace
    # dB last, from the global-unit values -- the order build_spectrum_model
    # and rebuild_spectrum_with_display_settings use for the base curve, so
    # both are referenced to the same unit (issue #354). y_raw/source_unit
    # stay the linear display values, same as the base curve's.
    base_unit = model.traces[0].unit if model.traces else "dB"
    return replace(
        trace,
        y=to_decibels(trace.y, is_squared_format(spectrum_format)),
        unit="dB",
        label=build_legend_text(*_overlay_legend_source(source_label, source_meta), "dB", source_meta),
        axis=resolve_overlay_axis(base_unit, "dB", base_is_db=(base_unit == "dB"), overlay_is_db=True),
    )


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

    if getattr(block, "is_canonical", False):
        matrix, _ = block.to_display_values(
            spectrum_format=spectrum_format, amplitude_mode=amplitude_mode
        )
        matrix = np.asarray(matrix, dtype=np.float64)
    else:
        matrix = np.asarray(block.values, dtype=np.float64)

    is_db = (decibel_scale is True) or ("dB" in color_scale)
    if is_db:
        if getattr(block, "is_canonical", False):
            is_squared = is_squared_format(spectrum_format)
        else:
            is_squared = bool(block.processing and is_squared_format(block.processing.spectrum_format))
        matrix = to_decibels(matrix, is_squared)
        effective_color_scale = color_scale if "dB" in color_scale else "dB (Log)"
    else:
        effective_color_scale = color_scale

    clean_name = strip_channel_name_prefix(_channel_identity_source(block.name))
    return SpectrogramModel(
        image=matrix,
        freqs=np.asarray(frequency_axis.values, dtype=np.float64),
        zvals=np.asarray(z_axis.values, dtype=np.float64),
        z_label=z_axis.label,
        z_unit=z_axis.unit,
        z_quantity=z_axis.quantity,
        color_scale=effective_color_scale,
        title=f"Vibration Spectrogram: {clean_name}",
        block=block,
    )


def _base_trace_index(model: PlotModel) -> int:
    """Index of the base curve in ``model``, falling back to 0 if none has is_base (#356)."""
    return next((i for i, t in enumerate(model.traces) if t.is_base), 0 if model.traces else -1)
