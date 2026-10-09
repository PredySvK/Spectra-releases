"""
The graph as data: what a dock is showing, with no drawing in it.

Presentation state on the view-models floor: data shaped for drawing,
without importing Qt or gui/. Can be built and asserted on in plain unit tests,
and later serialised to a figure spec for offline rendering (ARCHITECTURE_DECISIONS §1.7).

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

from view_models.analysis_kinds import ANALYSIS_TIME


@dataclass
class Pen:
    """Line appearance for a trace, Qt-free.

    ``style`` is a plain string ("solid", "dash", "dot", ...) rather than a
    ``Qt.PenStyle`` so the model stays importable without Qt; the renderer maps
    it when it draws.
    """

    color: str = "#ffcc00"
    width: float = 1.0
    style: str = "solid"


@dataclass
class Trace:
    """One curve on the graph.

    ``y`` is in the display unit (``unit``); ``y_raw`` is the untouched source
    array in ``source_unit``. Keeping both means a global-unit change is
    ``rebuild_with_units(model, prefs)`` with no I/O. ``channel_type`` drives
    the ordinate label and the display-unit choice.
    """

    x: np.ndarray
    y: np.ndarray
    y_raw: np.ndarray
    x_raw: Optional[np.ndarray] = None
    # "time"|"frequency"|"rpm"|... (core.data_block.Axis.quantity) or "" for
    # "undeclared" -- a curve built before axis_projections existed, or one no
    # builder has been taught to stamp yet. Undeclared draws unconditionally
    # regardless of the dock's x_domain (ARCHITECTURE_DECISIONS §1.30): the
    # alternative default -- hide unless it matches -- would blank out every
    # existing dock that doesn't set it, the same class of mistake as §1.29's
    # "Global branch offered an empty Channel facet".
    x_quantity: str = ""
    source_unit: str = ""
    channel_type: str = "general_dynamic"
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
    # trace that carries its id (gui.handlers.result_content.
    # unload_result_sets_from_dock); a "" curve is never touched that way.
    # Typed field rather than a meta_ref key: meta_ref flows into drop
    # descriptors and overlay persistence, this must not (ARCHITECTURE_DECISIONS
    # §1.31).
    result_set_id: str = ""
    meta_ref: Optional[Dict[str, Any]] = None
    # FFT/window/etc. this curve was computed with -- None for a raw time
    # trace, where no DSP ran. Mirrors block.processing (SpectralProcessing)
    # rather than the full DSP config DTO (no remove_dc: that is applied
    # before the block exists and never lands on processing). Two jobs:
    # a legend "Settings" column (ideas/session_persistence/PLAN.md §4 F) and
    # the source a dropped comparison curve can inherit instead of the
    # ribbon's current config (§4 R1) -- see channel_drop.py.
    compute_spec: Optional[Dict[str, Any]] = None
    # Underlying NVHDataBlock (canonical FFT or order cut) if available.
    # Enables instant on-the-fly re-scaling (Linear/Power/PSD, RMS/Peak, dB)
    # without re-running FFT or background jobs (ADR §1.60).
    block: Optional[Any] = None
    data_block: Optional[Any] = None


@dataclass
class ViewSpec:
    """Axes, title and background -- everything about the frame around the curves."""

    title: str = ""
    x_label: str = ""
    x_unit: str = ""
    y_label: str = ""
    y_unit: str = ""
    y_scale: str = "linear"  # "linear" | "log"
    bg: str = "default"
    x_range: Optional[Tuple[float, float]] = None


@dataclass
class BandRmsCursor:
    """A Band RMS cursor over the graph.

    Only ``kind="band_rms"`` exists today. ``band`` is the (lo, hi)
    frequency span the user dragged; ``processing`` carries the window
    corrections the Band RMS calculation needs (amplitude mode, spectrum
    format, ACF, linear ECF), which are known only for a frequency-domain plot.
    """

    kind: str = "band_rms"
    enabled: bool = False
    band: Optional[Tuple[float, float]] = None
    processing: Optional[Dict[str, Any]] = None


@dataclass
class Annotation:
    """User-authored mark on the graph.

    Real type, empty slot: nothing writes annotations from the UI yet
    (ARCHITECTURE_DECISIONS §1.8), but the model carries the list so the
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
    band_rms_cursors: List[BandRmsCursor] = field(default_factory=list)
    annotations: List[Annotation] = field(default_factory=list)
    analysis_kind: str = ANALYSIS_TIME  # a view_models.analysis_kinds name
    # The dock's one X quantity (core.axis_projections). "" means "not
    # decided" -- every trace draws regardless of its own x_quantity, which is
    # also what an empty model defaults to before its first trace lands.
    x_domain: str = ""


@dataclass
class SpectrogramModel:
    """The state of a spectrogram dock.

    A spectrogram is one ``ImageItem`` plus a LUT -- no curves, no overlays, no
    legend -- so it gets its own model rather than being forced into
    ``PlotModel.traces`` (ARCHITECTURE_DECISIONS §1.7, rejected alternative).
    ``image`` is the magnitude matrix as the renderer needs it; ``color_scale``
    is a display-only parameter (§1.21) read from ``app_context`` at build time.
    """

    image: np.ndarray
    freqs: np.ndarray
    zvals: np.ndarray  # bottom-axis values: time (s) or rpm, per z_label/z_unit
    z_label: str = "Time"
    z_unit: str = "s"
    # The bottom axis's quantity ("time" or "rpm"), so the global X axis unit
    # (issue #459) knows whether it rescales; the left axis is always frequency.
    z_quantity: str = "time"
    color_scale: str = "linear"
    title: str = ""
    block: Optional[Any] = None
    data_block: Optional[Any] = None
