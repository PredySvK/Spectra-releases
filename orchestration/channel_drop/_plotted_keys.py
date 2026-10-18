"""Drop keys of what a dock already plots (Qt-free)."""

from typing import Any, Iterable, Mapping, Set

from view_models.plot import resolve_order_curve_identity
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
        identity for trace in traces
        if (identity := resolve_order_curve_identity(trace)) is not None
    )
    return keys
