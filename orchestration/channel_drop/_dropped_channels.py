"""Drop descriptors resolved against the Data Pool, and the way back."""

from typing import Callable, Iterable, Mapping

from core.channel_drop import build_drop_descriptor
from core.models import ChannelMetadata, MeasurementRunIndex
from session.data_pool import DeadLink, find_dropped_channel


def resolve_dropped_channel(
    descriptor: Mapping,
    run_lookup: Callable[[str], MeasurementRunIndex | DeadLink],
) -> tuple[MeasurementRunIndex, ChannelMetadata] | str:
    """The pooled run and channel a descriptor names, or the log line saying why it is refused.

    ``run_lookup`` is ``DataPool.run_lookup``.
    """
    name = descriptor["channel_name"]
    run = run_lookup(descriptor["file_path"])
    if isinstance(run, DeadLink):
        return f"ERROR: Cannot add '{name}' -- its file is not currently loaded."
    channel = find_dropped_channel(run, name, descriptor["channel_index"])
    if channel is None:
        return f"ERROR: Cannot add '{name}' -- its channel was not found on '{run.file_name}'."
    return run, channel


def resolve_dropped_channels(
    descriptors: Iterable[Mapping],
    run_lookup: Callable[[str], MeasurementRunIndex | DeadLink],
    log: Callable[[str], None],
) -> list:
    """
    A drop's descriptors as the `(run_index, channel_meta, label)` rows a
    double click on the same Data Pool rows hands to
    Workspace.open_channels_tab. A descriptor whose file or channel is not in
    the pool is refused with its reason in the log -- no bare run is made up.
    """
    rows = []
    for descriptor in descriptors:
        resolved = resolve_dropped_channel(descriptor, run_lookup)
        if isinstance(resolved, str):
            log(resolved)
            continue
        rows.append((*resolved, descriptor["channel_name"]))
    return rows


def build_channel_descriptors(rows: Iterable) -> list:
    """
    The drop descriptors of `(run_index, channel_meta, label)` rows -- the
    inverse of `resolve_dropped_channels`, in the shape a drag out of the Data
    Pool carries.
    """
    return [build_drop_descriptor(run_index, channel_meta) for run_index, channel_meta, _ in rows]
