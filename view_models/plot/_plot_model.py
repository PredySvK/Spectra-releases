"""
The graph as data: what a dock is showing, with no drawing in it.

Presentation state on the view-models floor: data shaped for drawing,
without importing Qt or gui/. Can be built and asserted on in plain unit tests,
and later serialised to a figure spec for offline rendering.

Unit conversion does not happen here. ``_plot_model_builder`` takes the raw
arrays plus a ``UnitPreferences`` and returns a model whose ``Trace.y`` is
already in the display unit; a later global-unit change rebuilds the model from
``y_raw`` + ``source_unit`` without touching disk. The renderer draws exactly
what the model says.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.channel_types import CHANNEL_TYPE_GENERAL_DYNAMIC
from core.legend_config import LegendConfig

from view_models.analysis_kinds import ANALYSIS_TIME


@dataclass
class Pen:
    """Line appearance for a trace, Qt-free.

    A carousel curve holds its carousel ``slot`` and an empty ``color``: its
    colour and line style depend on the graph's rendering mode, which can
    change after the curve was built, and are resolved when drawing
    (``resolve_curve_look``, ADR §1.163). A curve with no slot (the base
    curve) is drawn in ``color``, solid.
    """

    color: str = "#ffcc00"
    width: float = 1.0
    slot: Optional[int] = None


@dataclass
class Trace:
    """One curve on the graph.

    ``y`` is in the display unit (``unit``); ``y_raw`` is the untouched source
    array in ``source_unit``. Keeping both means a global-unit change is
    ``rebuild_with_units(model, settings)`` with no I/O. ``channel_type`` drives
    the ordinate label and the display-unit choice.
    """

    x: np.ndarray
    y: np.ndarray
    y_raw: np.ndarray
    x_raw: Optional[np.ndarray] = None
    # "time"|"frequency"|"rpm"|... (core.data_block.Axis.quantity) or "" for
    # "undeclared" -- a curve built before axis_projections existed, or one no
    # builder has been taught to stamp yet. Undeclared draws unconditionally
    # regardless of the dock's x_domain: the
    # alternative default -- hide unless it matches -- would blank out every
    # existing dock that doesn't set it, the same class of mistake as §1.29's
    # "Global branch offered an empty Channel facet".
    x_quantity: str = ""
    source_unit: str = ""
    channel_type: str = CHANNEL_TYPE_GENERAL_DYNAMIC
    unit: str = ""
    label: str = ""  # rendered legend text, regenerated on a unit change
    # Kept apart from ``label`` so the legend text and the drop/capture
    # descriptor can both be rebuilt after a global-unit change without
    # re-parsing them out of the legend string.
    file_name: str = ""
    channel_name: str = ""  # prefix-stripped sensor name
    axis: str = "primary"  # "primary" | "secondary"
    is_base: bool = False
    pen: Pen = field(default_factory=Pen)
    # Id of the h5 result set this curve was read from, or "" for a curve with
    # no result-set origin -- a dropped channel, a live compute, a base curve
    # off a measurement. The Result Pool panel unchecks a set by dropping every
    # trace only it holds (gui.handlers.result_content.
    # unload_result_sets_from_dock); a "" curve is never touched that way.
    # Typed field rather than a meta_ref key: meta_ref flows into drop
    # descriptors and overlay persistence, this must not (ARCHITECTURE_DECISIONS
    # §1.31).
    result_set_id: str = ""
    # An Adopted curve (CONTEXT.md): the result set holds it, and the channel is
    # still the user's. Stamped by the adoption and nothing else.
    adopted: bool = False
    meta_ref: Optional[Dict[str, Any]] = None
    # The Curve recipe this curve was computed with, plus an order cut's
    # order (build_compute_spec) -- None for a raw time trace, where no DSP
    # ran. Only what changes the numbers: how the curve is shown lives in
    # spectrum_format/amplitude_mode below, so the Parameter Set, adoption and
    # a saved tab read the recipe alone.
    compute_spec: Optional[Dict[str, Any]] = None
    # The Spectrum format and Amplitude the curve's values are shown in
    # -- "" for what it is not in; recorded only by
    # build_trace_shown_as, whichever way the curve arrived (§1.258). A cursor
    # readout names the amplitude, a dropped spectrum can take both over
    # (channel_drop).
    spectrum_format: str = ""
    amplitude_mode: str = ""
    # Underlying NVHDataBlock (canonical FFT or order cut) if available.
    # Enables instant on-the-fly re-scaling (Linear/Power/PSD, RMS/Peak, dB)
    # without re-running FFT or background jobs.
    block: Optional[Any] = None

    @property
    def is_set_only(self) -> bool:
        """Whether only a result set holds this curve: no channel of the user's."""
        return bool(self.result_set_id) and not self.adopted

    @property
    def is_dropped_channel(self) -> bool:
        """Whether this is an overlay whose channel the user dropped, an Adopted
        curve too: what Refresh recomputes and a Save writes (§1.241)."""
        return not self.is_base and not self.is_set_only


@dataclass
class ViewSpec:
    """Axes, title and background -- everything about the frame around the curves."""

    title: str = ""
    x_label: str = ""
    x_unit: str = ""
    y_label: str = ""
    y_unit: str = ""
    # The ordinate's quantity ("rpm" for a speed channel, else ""): it puts a
    # Hz ordinate on the Speed row of the Display prefix (resolve_ordinate_quantity).
    y_quantity: str = ""
    y_scale: str = "linear"  # "linear" | "log"
    bg: str = "default"
    x_range: Optional[Tuple[float, float]] = None


@dataclass
class Annotation:
    """User-authored mark on the graph.

    Real type, empty slot: nothing writes annotations from the UI yet
   , but the model carries the list so the
    renderer and a future editor have one shape to target.
    """

    kind: str = "text"
    text: str = ""
    xy: Tuple[float, float] = (0.0, 0.0)


@dataclass
class PlotModel:
    """The full state of a curve-based dock."""

    traces: List[Trace] = field(default_factory=list)
    view: ViewSpec = field(default_factory=ViewSpec)
    annotations: List[Annotation] = field(default_factory=list)
    analysis_kind: str = ANALYSIS_TIME  # a view_models.analysis_kinds name
    # The dock's one X quantity (core.axis_projections). "" means "not
    # decided" -- every trace draws regardless of its own x_quantity, which is
    # also what an empty model defaults to before its first trace lands.
    x_domain: str = ""
    # Which parts every trace's Curve name (Trace.label) is made of; GraphCurves
    # stamps its graph's own on every model it holds (plot §1.296).
    legend_config: LegendConfig = LegendConfig()


@dataclass
class SpectrogramModel:
    """The state of a spectrogram dock.

    A spectrogram is one ``ImageItem`` plus a LUT -- no curves, no overlays, no
    legend -- so it gets its own model rather than being forced into
    ``PlotModel.traces``.
    Axis letters follow CONTEXT.md "Spectrogram axes": ``x`` is the bottom
    (tracking) axis, ``y`` the frequency, ``z`` the colour matrix in
    ``(y, x)`` order with its unit ``z_unit``. Values stay native; the drawn
    form is ``build_drawn_spectrogram``'s (§1.130, #893). ``color_scale`` is a
    display-only parameter (§1.21) read from ``app_context`` at build time.
    """

    x: np.ndarray  # bottom-axis values: time (s) or rpm, per x_label/x_unit
    y: np.ndarray  # frequency (Hz)
    z: np.ndarray  # colour values, (y, x)
    x_label: str = "Time"
    x_unit: str = "s"
    # The bottom axis's quantity ("time" or "rpm"), so the global X axis unit
    # (issue #459) knows whether it rescales; the left axis is always frequency.
    x_quantity: str = "time"
    color_scale: str = "linear"
    title: str = ""
    z_unit: str = ""
    block: Optional[Any] = None
    # The recipe the waterfall was computed and shown with -- what a saved tab
    # recomputes it with, as ``Trace.compute_spec`` is for a curve.
    compute_spec: Optional[Dict[str, Any]] = None
