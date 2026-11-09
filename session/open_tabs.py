# =====================================================================
# FILE: session/open_tabs.py
# =====================================================================
"""
The recipe for one open analytical dock and its session persistence data.

Deliberately not a serialised ``PlotModel``: ``Trace.y``/``y_raw`` are numpy
arrays computed from disk. ``TabSpec`` carries what a fresh drop already
carries -- which source and channel each curve came from, and the
``compute_spec`` it should be recomputed with -- plus the name of the curve's
Tab cache file, where the arrays themselves live. The recipe is
the fallback when that file is missing or unreadable.

Lives in ``session`` (R01: what is currently open and how it changes over time).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, Union

from core.evaluation import EvaluationConfig
from core.legend_config import LegendConfig
from core.models import ChannelMetadata, MeasurementRunIndex
from session.data_pool import DeadLink, ResolvedTrace, build_source_lookup, resolve_trace


@dataclass
class TraceSpec:
    """
    One curve's identity + recipe -- enough for ``BaseCurveCompute.start`` (S4) to
    recompute it, not enough to draw it. ``source_id`` is the resolver key
    (S3: ``canonical_path(file_path)``), not a path to read directly --
    same rule ``canonical_path`` itself carries.
    """

    source_id: str
    channel_name: str
    compute_spec: Optional[Dict[str, Any]] = None
    is_base: bool = False
    # The curve's Tab cache file, relative to the project's `cache/tabs/`
    #. None -- also a project saved before the Tab cache --
    # means no file: a restore computes the curve from `compute_spec`.
    tab_cache_file: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "source_id": self.source_id,
            "channel_name": self.channel_name,
            "compute_spec": self.compute_spec,
            "is_base": self.is_base,
        }
        if self.tab_cache_file:
            data["tab_cache_file"] = self.tab_cache_file
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceSpec":
        return cls(
            source_id=str(data.get("source_id", "")),
            channel_name=str(data.get("channel_name", "")),
            compute_spec=data.get("compute_spec"),
            is_base=bool(data.get("is_base", False)),
            tab_cache_file=(str(data["tab_cache_file"]) if data.get("tab_cache_file") else None),
        )


@dataclass
class TabSpec:
    """
    One open dock's recipe. ``build_shell(spec)`` (S4) turns this into an
    empty dock with the right title; ``BaseCurveCompute.start`` turns it into
    a computed one, on the same background path a fresh drop already uses.

    ``analysis_kind`` matches the dock's own ``analysis_kind`` ("time" |
    "spectrum" | "orders" | "overall_level" | "spectrogram"). A
    ``SpectrogramDock`` has no traces -- ``traces`` holds just
    its one vibration channel. No separate tacho ``TraceSpec``: S6 restores a
    spectrogram through the same ``build_shell``+``BaseCurveCompute.start`` pair a
    live open uses, and ``run_live_compute`` already auto-links a tacho onto a
    freshly built dock (no tacho bound yet) the same way regardless
    of whether the dock is new or restored -- recording which tacho channel
    had been bound would only shadow that existing, already-deterministic
    lookup.
    """

    analysis_kind: str = "time"
    # The base curve first, then every curve dragged onto the dock afterwards
    # -- one identity for both, resolved the same way on reopen
    #.
    traces: List[TraceSpec] = field(default_factory=list)
    # The dock's own id, handed back to the rebuilt dock on reopen so a custom
    # Local filter card's `owner_dock_id` still names it (ARCHITECTURE_DECISIONS
    # §1.94, issue #65). None for a duplicate `build_restore_plan` refuses -- the dock then gets a
    # fresh id, and any card still naming the old one is pruned as orphaned.
    dock_id: Optional[str] = None
    # This dock's own Local-scope filter content, one entry per profile id
    # that has ever been checked against it (session.trace_filter.
    # FilterSelectionStore.export_local_selections_for_dock/import_local_selections_for_dock) --
    # keyed by profile id, not dock id: the recipe and its local filter travel
    # together on the same TabSpec, and a project saved before `dock_id`
    # persisted still carries its local filter this way
    # (the filter-mask plan T5). Global
    # selections and profile identities persist separately, under
    # gui.handlers.filter_routing.FILTER_STATE_KEY.
    filter_selections: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Result-set ids read onto this dock via `gui.handlers.result_content.
    # ResultContentHandler.load_into_dock` --
    # `GraphCurves.loaded_result_set_ids`, captured so a dock's h5 content
    # survives a save/reopen the same way its dropped channels already do.
    # Just ids, not the curves themselves: same "recipe, not a cache" rule
    # this file's own docstring states for `traces`, and re-reading is the
    # one path `ResultContentHandler.load_into_dock` already has.
    loaded_result_set_ids: List[str] = field(default_factory=list)
    # This dock's evaluation configuration:
    # evaluation algorithm name, parameters, and whether to respect the trace filter.
    # Single values are not persisted; they are recomputed on demand.
    evaluation_config: EvaluationConfig = field(default_factory=EvaluationConfig)
    custom_label: Optional[str] = None
    # This graph's Legend Settings (plot §1.296): None -- no saved choice, a
    # spectrogram -- means the Default the app keeps for every new graph.
    legend_config: Optional[LegendConfig] = None

    def __post_init__(self) -> None:
        if isinstance(self.evaluation_config, dict):
            self.evaluation_config = EvaluationConfig.from_dict(self.evaluation_config)
        elif not isinstance(self.evaluation_config, EvaluationConfig):
            self.evaluation_config = EvaluationConfig()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_kind": self.analysis_kind,
            "traces": [t.to_dict() for t in self.traces],
            "dock_id": self.dock_id,
            "filter_selections": {k: dict(v) for k, v in self.filter_selections.items()},
            "loaded_result_set_ids": list(self.loaded_result_set_ids),
            "evaluation_config": self.evaluation_config.to_dict(),
            "custom_label": self.custom_label,
            "legend_config": self.legend_config.to_dict() if self.legend_config is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TabSpec":
        return cls(
            analysis_kind=str(data.get("analysis_kind", "time")),
            traces=[TraceSpec.from_dict(t) for t in data.get("traces", [])],
            dock_id=str(data["dock_id"]) if data.get("dock_id") else None,
            filter_selections={k: dict(v) for k, v in data.get("filter_selections", {}).items()},
            loaded_result_set_ids=[str(rid) for rid in data.get("loaded_result_set_ids", [])],
            # Normalised once, by __post_init__.
            evaluation_config=data.get("evaluation_config"),
            custom_label=data.get("custom_label"),
            legend_config=(LegendConfig.from_dict(data["legend_config"])
                           if isinstance(data.get("legend_config"), Mapping) else None),
        )


@dataclass(frozen=True)
class RestoredOverlay:
    """A saved overlay resolved to its live pool entries, with the recipe it
    was saved with -- what its re-drop computes with -- and its Tab cache
    file, which the re-drop reads first."""

    run_index: MeasurementRunIndex
    channel_meta: ChannelMetadata
    compute_spec: Optional[Dict[str, Any]] = None
    tab_cache_file: Optional[str] = None


@dataclass(frozen=True)
class RestoreTab:
    """One parsed tab recipe and its current Data Pool resolution."""

    spec: TabSpec
    resolved: Union[ResolvedTrace, DeadLink]
    evaluation_config: EvaluationConfig
    overlays: Tuple[RestoredOverlay, ...] = ()


@dataclass(frozen=True)
class RestorePlan:
    """Pure restore result: valid tab recipes plus non-fatal notices."""

    tabs: Tuple[RestoreTab, ...] = ()
    notices: Tuple[str, ...] = ()


def _default_evaluation() -> EvaluationConfig:
    return EvaluationConfig()


def _evaluation_config_for(raw: Mapping[str, Any], spec: TabSpec) -> Tuple[EvaluationConfig, Optional[str]]:
    """Return a safe EvaluationConfig and a notice for malformed saved data.

    `spec.evaluation_config` is already normalised by `TabSpec`; `raw` is read
    only to tell a missing value from a corrupt one for the notice.
    """
    raw_eval = raw.get("evaluation_config")
    if raw_eval is None:
        return _default_evaluation(), None
    if not isinstance(raw_eval, (dict, EvaluationConfig)):
        return _default_evaluation(), "Corrupted evaluation settings in tab state, resetting to default."

    cfg = spec.evaluation_config
    from signal_processing.evaluation.registry import EVALUATIONS

    if cfg.evaluation_name not in EVALUATIONS:
        # Kept, not replaced by Max: saving must not drop it unnoticed; the
        # Evaluation card says this version cannot run it (§1.259 point 3).
        return cfg, (
            f"Unknown evaluation type '{cfg.evaluation_name}' in tab state; "
            "the Evaluation card cannot run it in this version."
        )

    return cfg, None


def _resolve_overlays(spec: TabSpec, source_lookup: Dict[str, Any], index: int,
                      notices: List[str]) -> Tuple[RestoredOverlay, ...]:
    resolved_overlays: List[RestoredOverlay] = []
    for overlay in spec.traces[1:]:
        resolved = resolve_trace(overlay.source_id, overlay.channel_name, source_lookup)
        if isinstance(resolved, DeadLink):
            notices.append(
                f"Overlay '{overlay.channel_name}' of open-tab record at index {index} "
                f"could not be restored ({resolved.reason})."
            )
            continue
        resolved_overlays.append(
            RestoredOverlay(resolved.run_index, resolved.channel_meta, overlay.compute_spec,
                            overlay.tab_cache_file))
    return tuple(resolved_overlays)


def build_restore_plan(raw_specs: Any, loaded_runs: List[Any]) -> RestorePlan:
    """Parse and resolve saved open-tab recipes without Qt or side effects.

    Invalid records are skipped independently, while unresolved traces remain
    as ``DeadLink`` entries so the GUI can show a recoverable placeholder.
    A ``dock_id`` an earlier record already claimed is cleared, so two
    rebuilt docks never share one id.
    """
    source_lookup = build_source_lookup(loaded_runs)
    tabs: List[RestoreTab] = []
    notices: List[str] = []
    claimed_dock_ids: Set[str] = set()

    for index, raw in enumerate(raw_specs or ()):
        if not isinstance(raw, Mapping):
            notices.append(f"Ignoring corrupted open-tab record at index {index}.")
            continue
        try:
            spec = TabSpec.from_dict(raw)
            if not spec.traces:
                notices.append(f"Ignoring open-tab record at index {index} without a trace.")
                continue
            base = spec.traces[0]
            resolved = resolve_trace(base.source_id, base.channel_name, source_lookup)
            evaluation_config, notice = _evaluation_config_for(raw, spec)
            overlays = _resolve_overlays(spec, source_lookup, index, notices)
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            notices.append(f"Ignoring corrupted open-tab record at index {index}: {exc}")
            continue
        if notice is not None:
            notices.append(notice)
        if spec.dock_id is not None:
            if spec.dock_id in claimed_dock_ids:
                spec = dataclasses.replace(spec, dock_id=None)
            else:
                claimed_dock_ids.add(spec.dock_id)
        tabs.append(RestoreTab(spec, resolved, evaluation_config, overlays))

    return RestorePlan(tuple(tabs), tuple(notices))
