"""Drop keys of what a dock already plots (Qt-free)."""

from typing import Any, Iterable, Mapping, Set

from core.block_kinds import PARAM_ORDER
from orchestration.channel_drop._routing import drop_key


def read_plotted_keys(curve_descriptors: Iterable[Mapping], traces: Iterable[Any]) -> Set[tuple]:
    """Keys of the plotted curves (``meta_ref`` of each descriptor) plus one per order
    trace (``meta_ref`` of the trace and its ``PARAM_ORDER``)."""
    keys = {
        drop_key(meta_ref)
        for plotted in curve_descriptors
        for meta_ref in (plotted.get("meta_ref", {}),)
        if "file_path" in meta_ref and "channel_index" in meta_ref
    }
    keys.update(
        (*drop_key(trace.meta_ref), float(trace.compute_spec[PARAM_ORDER]))
        for trace in traces
        if trace.meta_ref and "file_path" in trace.meta_ref and "channel_index" in trace.meta_ref
        and trace.compute_spec and trace.compute_spec.get(PARAM_ORDER) is not None
    )
    return keys
