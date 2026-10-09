"""An overlay's saved identity, and the drop descriptor it is re-dropped with."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from core.models import MeasurementRunIndex
from io_modules.measurement_files import canonical_path
from selection.channel_identity import resolve_channel_at_index
from session.data_pool import ResolvedTrace, build_source_lookup
from session.open_tabs import TraceSpec
from view_models.plot import GraphCurves


def _pool_channel_name(run: Optional[MeasurementRunIndex], channel_index: int) -> Optional[str]:
    # The key `resolve_trace` looks the channel up by on reopen.
    channel = resolve_channel_at_index(run.available_channels, channel_index) if run else None
    return channel[0] if channel else None


def build_overlay_trace_specs(curves: GraphCurves,
                              loaded_runs: Iterable[MeasurementRunIndex]) -> List[TraceSpec]:
    """The ``TraceSpec`` of every ``GraphCurves.overlay_traces`` curve.

    Named by the channel the Data Pool holds at that file and channel index,
    so the saved name is one ``resolve_trace`` finds again; a file no longer
    in the pool keeps the curve's own channel name.
    """
    source_lookup = build_source_lookup(list(loaded_runs))
    return [_trace_spec(trace, source_lookup) for trace in curves.overlay_traces()]


def build_base_trace_spec(curves: GraphCurves,
                          loaded_runs: Iterable[MeasurementRunIndex]) -> Optional[TraceSpec]:
    """The ``TraceSpec`` of the base curve, read off the curve itself -- for a
    graph opened with several channels at once, which has no run of its own.
    None when the base curve names no channel (none yet, or an h5 curve)."""
    base = curves.base_trace
    if base is None or base.result_set_id or not (base.meta_ref or {}).get("file_path"):
        return None
    source_lookup = build_source_lookup(list(loaded_runs))
    return _trace_spec(base, source_lookup, compute_spec=base.compute_spec, is_base=True)


def _trace_spec(trace, source_lookup, **extra) -> TraceSpec:
    source_id = canonical_path(str(trace.meta_ref.get("file_path", "")))
    channel_index = int(trace.meta_ref.get("channel_index", 0))
    name = _pool_channel_name(source_lookup.get(source_id), channel_index)
    return TraceSpec(
        source_id=source_id,
        channel_name=name if name is not None else trace.channel_name,
        **extra,
    )


def build_drop_descriptor(resolved: ResolvedTrace) -> Dict[str, Any]:
    """The channel-drop payload of a resolved overlay -- the shape a drag out
    of the Data Pool carries, with this session's channel index."""
    run, meta = resolved.run_index, resolved.channel_meta
    return {
        "file_path": str(run.file_path),
        "file_name": str(run.file_name),
        "channel_index": int(meta.index),
        "channel_name": str(meta.name),
        "channel_type": str(meta.type),
        "unit": str(meta.unit),
    }
