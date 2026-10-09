# =====================================================================
# FILE: session/open_tabs.py
# =====================================================================
"""
The recipe for one open analytical dock and its session persistence data.

Deliberately not a serialised ``PlotModel``: ``Trace.y``/``y_raw`` are numpy
arrays computed from disk, and persisting them would turn "the recipe" into
"a cache" -- a different, larger problem this project already tracks
separately (``ideas/session_persistence/PLAN.md`` §7, the write-behind H5
cache gated behind ``dispatch_compute`` existing). ``TabSpec`` carries only
what a fresh drop already carries: which source and channel each curve came
from, and the ``compute_spec`` it should be recomputed with.

Lives in ``session`` (R01: what is currently open and how it changes over time).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple, Union

from core.evaluation import EvaluationConfig
from io_modules.measurement_files import canonical_path
from selection.channel_identity import strip_order_overlay_prefix
from session.data_pool import DeadLink, ResolvedTrace, build_source_lookup, resolve_trace


@dataclass
class TraceSpec:
    """
    One curve's identity + recipe -- enough for ``dispatch_compute`` (S4) to
    recompute it, not enough to draw it. ``source_id`` is the resolver key
    (S3: ``canonical_path(file_path)``), not a path to read directly --
    same rule ``canonical_path`` itself carries.
    """

    source_id: str
    channel_name: str
    compute_spec: Optional[Dict[str, Any]] = None
    is_base: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "channel_name": self.channel_name,
            "compute_spec": self.compute_spec,
            "is_base": self.is_base,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceSpec":
        return cls(
            source_id=str(data.get("source_id", "")),
            channel_name=str(data.get("channel_name", "")),
            compute_spec=data.get("compute_spec"),
            is_base=bool(data.get("is_base", False)),
        )


def _legacy_overlay_trace(desc: Mapping[str, Any]) -> TraceSpec:
    """One saved ``overlay_specs`` drop dict as the ``TraceSpec`` it stands for.

    Its "channel_name" was the curve's legend label: "[file_name] " in front,
    and possibly an "O:N " order-overlay tag. Both are peeled off, leaving the
    channel name a base curve is saved under. ``channel_index`` is dropped --
    it is what a re-recorded file with reordered channels gets wrong.
    """
    name = str(desc.get("channel_name", ""))
    file_tag = f"[{desc.get('file_name', '')}] "
    if name.startswith(file_tag):
        name = name[len(file_tag):]
    return TraceSpec(
        source_id=canonical_path(str(desc.get("file_path", ""))),
        channel_name=strip_order_overlay_prefix(name),
        compute_spec=desc.get("compute_spec"),
    )


def _traces_from(data: Mapping[str, Any]) -> List[TraceSpec]:
    traces = [TraceSpec.from_dict(t) for t in data.get("traces", [])]
    if traces:
        # Without a base there is no tab to put the overlays on.
        traces.extend(_legacy_overlay_trace(d) for d in data.get("overlay_specs", []))
    return traces


@dataclass
class TabSpec:
    """
    One open dock's recipe. ``build_shell(spec)`` (S4) turns this into an
    empty dock with the right title; ``dispatch_compute(spec)`` turns it into
    a computed one, on the same background path a fresh drop already uses.

    ``analysis_kind`` matches the dock's own ``analysis_kind`` ("time" |
    "spectrum" | "orders" | "overall_level" | "spectrogram"). A
    ``SpectrogramDock`` has no traces (ARCHITECTURE_DECISIONS §1.7) -- ``traces`` holds just
    its one vibration channel. No separate tacho ``TraceSpec``: S6 restores a
    spectrogram through the same ``build_shell``+``dispatch_compute(...,
    is_fresh_open=True)`` pair a live open uses, and
    ``_dispatch_compute`` already auto-links a tacho onto a
    freshly built dock (``dock.tacho_block is None``) the same way regardless
    of whether the dock is new or restored -- recording which tacho channel
    had been bound would only shadow that existing, already-deterministic
    lookup.
    """

    analysis_kind: str = "time"
    # The base curve first, then every curve dragged onto the dock afterwards
    # -- one identity for both, resolved the same way on reopen. A project
    # saved before overlays were ``TraceSpec``s holds them as drop dicts under
    # "overlay_specs"; ``from_dict`` reads those into ``traces`` and
    # ``to_dict`` never writes that key again (ARCHITECTURE_DECISIONS §1.86).
    traces: List[TraceSpec] = field(default_factory=list)
    # The dock's own id, handed back to the rebuilt dock on reopen so a custom
    # Local filter card's `owner_dock_id` still names it (ARCHITECTURE_DECISIONS
    # §1.94, issue #65). None for a project saved before ids were persisted,
    # and for a duplicate `build_restore_plan` refuses -- the dock then gets a
    # fresh id, and any card still naming the old one is pruned as orphaned.
    dock_id: Optional[str] = None
    # This dock's own Local-scope filter content, one entry per profile id
    # that has ever been checked against it (session.trace_filter.
    # FilterSelectionStore.export_local_selections_for_dock/import_local_selections_for_dock) --
    # keyed by profile id, not dock id: the recipe and its local filter travel
    # together on the same TabSpec, and a project saved before `dock_id`
    # persisted still carries its local filter this way
    # (plans/2026-09-05_filtre-maska-nad-kazdym-grafom.md T5). Global
    # selections and profile identities persist separately, under
    # gui.handlers.filter_routing.FILTER_STATE_KEY.
    filter_selections: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Result-set ids read onto this dock via `gui.handlers.result_content.
    # ResultContentHandler.load_into_dock` (ARCHITECTURE_DECISIONS §1.30, plan F5) --
    # `GraphCurves.loaded_result_set_ids`, captured so a dock's h5 content
    # survives a save/reopen the same way its dropped channels already do.
    # Just ids, not the curves themselves: same "recipe, not a cache" rule
    # this file's own docstring states for `traces`, and re-reading is the
    # one path `ResultContentHandler.load_into_dock` already has.
    loaded_result_set_ids: List[str] = field(default_factory=list)
    # This dock's evaluation configuration (ADR §1.64 point 1, issue #138):
    # evaluation algorithm name, parameters, and whether to respect the trace filter.
    # Single values are not persisted; they are recomputed on demand.
    evaluation_config: EvaluationConfig = field(default_factory=EvaluationConfig)

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
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TabSpec":
        raw_eval = data.get("evaluation_config")
        if isinstance(raw_eval, EvaluationConfig):
            eval_cfg = raw_eval
        elif isinstance(raw_eval, dict):
            eval_cfg = EvaluationConfig.from_dict(raw_eval)
        else:
            eval_cfg = EvaluationConfig()

        return cls(
            analysis_kind=str(data.get("analysis_kind", "time")),
            traces=_traces_from(data),
            dock_id=str(data["dock_id"]) if data.get("dock_id") else None,
            filter_selections={k: dict(v) for k, v in data.get("filter_selections", {}).items()},
            loaded_result_set_ids=[str(rid) for rid in data.get("loaded_result_set_ids", [])],
            evaluation_config=eval_cfg,
        )


@dataclass(frozen=True)
class RestoreTab:
    """One parsed tab recipe and its current Data Pool resolution."""

    spec: TabSpec
    resolved: Union[ResolvedTrace, DeadLink]
    evaluation_config: EvaluationConfig
    overlays: Tuple[ResolvedTrace, ...] = ()


@dataclass(frozen=True)
class RestorePlan:
    """Pure restore result: valid tab recipes plus non-fatal notices."""

    tabs: Tuple[RestoreTab, ...] = ()
    notices: Tuple[str, ...] = ()


def _default_evaluation() -> EvaluationConfig:
    return EvaluationConfig(evaluation_name="max", params={}, respect_trace_filter=True)


def _evaluation_config_for(raw: Mapping[str, Any], spec: TabSpec) -> Tuple[EvaluationConfig, Optional[str]]:
    """Return a safe EvaluationConfig and a notice for malformed saved data."""
    if "evaluation_config" not in raw or raw.get("evaluation_config") is None:
        return _default_evaluation(), None

    raw_eval = raw.get("evaluation_config")
    if not isinstance(raw_eval, (dict, EvaluationConfig)):
        return _default_evaluation(), "Corrupted evaluation settings in tab state, resetting to default."

    cfg = spec.evaluation_config if isinstance(raw_eval, EvaluationConfig) else EvaluationConfig.from_dict(raw_eval)
    from signal_processing.evaluation.registry import EVALUATIONS

    if cfg.evaluation_name not in EVALUATIONS:
        return EvaluationConfig(
            evaluation_name="max",
            params={},
            respect_trace_filter=cfg.respect_trace_filter,
            metadata_columns=cfg.metadata_columns,
        ), f"Unknown evaluation type '{cfg.evaluation_name}' in tab state, resetting to default."

    return cfg, None


def _resolve_overlays(spec: TabSpec, source_lookup: Dict[str, Any], index: int,
                      notices: List[str]) -> Tuple[ResolvedTrace, ...]:
    resolved_overlays: List[ResolvedTrace] = []
    for overlay in spec.traces[1:]:
        resolved = resolve_trace(overlay.source_id, overlay.channel_name, source_lookup)
        if isinstance(resolved, DeadLink):
            notices.append(
                f"Overlay '{overlay.channel_name}' of open-tab record at index {index} "
                f"could not be restored ({resolved.reason})."
            )
            continue
        resolved_overlays.append(resolved)
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
