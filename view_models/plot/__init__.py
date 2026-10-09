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
- Display settings: DisplaySettings is the one value a graph is built and
  rebuilt in (unit prefs, spectrum format / amplitude / dB, order & Overall Level amplitude).
- Plot models (PlotModel, SpectrogramModel, Trace, Pen, ViewSpec, BandRmsCursor, Annotation):
  the snapshot a dock draws. Mask, HiddenReason and AcceptOutcome describe
  what GraphCurves decided is visible.
- Graph spectrogram: GraphSpectrogram owns the spectrogram one graph holds --
  GraphCurves' counterpart for a 2D map: it builds the model from a block
  (show_block), rebuilds it in other display settings (rebuild_display) and
  hands every new model to the dock that draws it (#301).
- Live channel drops: LiveChannelDrops keeps the channels dropped live onto a graph
  (claimed, pending) beside its curves.
- Questions the GUI asks about curves it holds: amplitude_mode_for_kind,
  overall_level_band_differs_from_dock, traces_kept_after_unload, build_trace_descriptor.
- Presentation styling & legend text: base_display_unit, format_display_unit, carousel_pen_spec.

The builders behind GraphCurves and GraphSpectrogram are private: which one a
block gets is their decision, not the caller's (#297, #301).

What does NOT belong here: Qt widgets or drawing calls (gui/), deciding what
runs (orchestration/), what project is currently open (session/), which
curves are relevant (selection/), or signal processing computation (signal_processing/).
"""

from ._display_settings import (
    DisplaySettings,
)
from ._graph_colours import (
    carousel_pen_spec,
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
from ._legend_settings import (
    base_display_unit,
    format_display_unit,
)
from ._live_channel_drops import (
    LiveChannelDrops,
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
    amplitude_mode_for_kind,
    overall_level_band_differs_from_dock,
    traces_kept_after_unload,
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
    # Live channel drops -- what a graph claimed and still waits for
    "LiveChannelDrops",
    # Graph spectrogram -- the one owner of a graph's spectrogram
    "GraphSpectrogram",
    # Display settings -- how a graph shows its curves
    "DisplaySettings",
    # Plot models
    "Annotation",
    "BandRmsCursor",
    "Pen",
    "PlotModel",
    "SpectrogramModel",
    "Trace",
    "ViewSpec",
    # Visibility
    "AcceptOutcome",
    "HiddenReason",
    "Mask",
    # Questions about held curves
    "amplitude_mode_for_kind",
    "overall_level_band_differs_from_dock",
    "traces_kept_after_unload",
    # Legend & palette
    "base_display_unit",
    "carousel_pen_spec",
    "format_display_unit",
]
