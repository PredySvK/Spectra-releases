"""
view_models.plot -- The curves a graph holds, the plot models they are drawn from,
legend formatting and palette configuration.

Architecture:
- View-model floor (Floor 3): How should a plot/spectrogram/curve be shown, without Qt?
- Graph curves: GraphCurves owns which curves one graph holds and is the one way
  a graph is built: it picks the plot model from a block's kind (show_blocks),
  adds curves (add_curve), owns the result-set lifecycle (request_result_sets,
  land_result_set, abandon_result_sets, unload_result_sets), rebuilds them
  (rebuild_units, rebuild_domain, rebuild_*_display) and reports every change
  (CurvesReplaced, CurveAppended, CurvesCleared) to the dock that draws them.
  PendingRestore / NOTHING_PENDING: what a graph gets back once its next base curve lands.
- Display settings: DisplaySettings is the one value a graph or a spectrogram is
  built and rebuilt in (unit prefs, spectrum format / amplitude / dB, colour scale,
  order & Overall Level amplitude); resolve_display_settings reads it from the ribbon
  tabs' configs for a dock's Analysis kind (#833), its own RMS/Peak included (ADR §1.62
  point 22).
- Plot models (PlotModel, SpectrogramModel, Trace, Pen, ViewSpec, BandRmsCursor, Annotation):
  the snapshot a dock draws. Mask, HiddenReason and AcceptOutcome describe
  what GraphCurves decided is visible.
- Graph spectrogram: GraphSpectrogram owns the spectrogram one graph holds --
  GraphCurves' counterpart for a 2D map: it builds the model from a block
  (show_block), rebuilds it in other display settings (rebuild_display) and
  hands every new model to the dock that draws it (#301).
- Questions the GUI asks about curves it holds: overall_level_band_differs_from_dock,
  traces_kept_after_unload, build_trace_descriptor.
- Spectrogram image geometry: resolve_image_axis_extent gives the span of one image axis
  (half a bin past each end, +-0.5 for a single bin); the dock draws the image over it
  and the Cursor reads the cell under the mouse from it (#665 C28).
- Presentation styling & legend text: base_display_unit, format_display_unit, resolve_carousel_colour.
- resolve_ordinate_quantity: "rpm" for a speed curve's Y values, so the Display prefix
  puts a Hz ordinate on the Speed row.
- Rendering mode & curve look: resolve_rendering_mode picks OpenGL or raster
  from the drawn curves (LARGE_CURVE_POINTS); resolve_curve_look turns a Pen's carousel
  slot into a CurveLook (colour + one of LINE_STYLES) for that mode.
- Clipping & downsampling: resolve_curve_decimation turns a curve's point count and the
  Graph Rendering preferences into a CurveDecimation (clip / auto / factor); small curves
  are never decimated, preferences can only switch it off (#665 C27).

The builders behind GraphCurves and GraphSpectrogram are private: which one a
block gets is their decision, not the caller's (#297, #301).

What does NOT belong here: Qt widgets or drawing calls (gui/), deciding what
runs (orchestration/), what project is currently open (session/), which
curves are relevant (selection/), or signal processing computation (signal_processing/).
"""

from ._curve_decimation import (
    CurveDecimation,
    resolve_curve_decimation,
)
from ._curve_identity import (
    resolve_curve_channel_key,
    resolve_order_curve_identity,
)
from ._display_settings import (
    DisplaySettings,
    resolve_display_settings,
)
from ._graph_colours import (
    LARGE_CURVE_POINTS,
    LINE_STYLES,
    resolve_carousel_colour,
    CurveLook,
    HeldPens,
    RenderingMode,
    resolve_curve_look,
    resolve_rendering_mode,
)
from ._graph_curves import (
    CurveAppended,
    CurvesChange,
    CurvesCleared,
    CurvesReplaced,
    GraphCurves,
    NOTHING_PENDING,
    PendingRestore,
    build_trace_descriptor,
)
from ._graph_spectrogram import (
    GraphSpectrogram,
)
from ._image_extent import (
    resolve_image_axis_extent,
)
from ._legend_settings import (
    base_display_unit,
    format_display_unit,
)
from ._plot_model import (
    Annotation,
    BandRmsCursor,
    Pen,
    PlotModel,
    SpectrogramModel,
    Trace,
    ViewSpec,
)
from ._plot_model_builder import (
    build_compute_spec,
    overall_level_band_differs_from_dock,
    traces_kept_after_unload,
)
from ._trace_display import (
    resolve_ordinate_quantity,
)
from ._visible_traces import (
    AcceptOutcome,
    HiddenReason,
    Mask,
)

__all__ = [
    # Graph curves -- the one owner of a graph's curves
    "CurveAppended",
    "CurvesChange",
    "CurvesCleared",
    "CurvesReplaced",
    "GraphCurves",
    "NOTHING_PENDING",
    "PendingRestore",
    "build_trace_descriptor",
    # Order-curve identity -- (file, channel index, order), one composition
    "resolve_curve_channel_key",
    "resolve_order_curve_identity",
    # Graph spectrogram -- the one owner of a graph's spectrogram
    "GraphSpectrogram",
    # Display settings -- how a graph shows its curves
    "DisplaySettings",
    "resolve_display_settings",
    # Plot models
    "Annotation",
    "BandRmsCursor",
    "Pen",
    "PlotModel",
    "SpectrogramModel",
    "Trace",
    "ViewSpec",
    # The one block -> Trace.compute_spec recipe
    "build_compute_spec",
    # Visibility
    "AcceptOutcome",
    "HiddenReason",
    "Mask",
    # Questions about held curves
    "overall_level_band_differs_from_dock",
    "traces_kept_after_unload",
    # Spectrogram image geometry -- the span of one image axis
    "resolve_image_axis_extent",
    # Legend & palette
    "base_display_unit",
    "resolve_carousel_colour",
    "HeldPens",
    "format_display_unit",
    # The quantity of a curve's Y values (Display prefix row for a Hz ordinate)
    "resolve_ordinate_quantity",
    # Rendering mode & curve look
    "CurveLook",
    "LARGE_CURVE_POINTS",
    "CurveDecimation",
    "resolve_curve_decimation",
    "LINE_STYLES",
    "RenderingMode",
    "resolve_curve_look",
    "resolve_rendering_mode",
]
