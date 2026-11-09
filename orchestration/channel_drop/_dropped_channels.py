"""Drop descriptors resolved against the Data Pool, and the way back.

The one place a dropped channel becomes the pooled run and channel it names:
every lane of a drop and every tab a drop opens starts here, so a channel is
refused for the same reasons with the same line wherever it lands.
"""

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from core.channel_drop import build_drop_descriptor
from core.models import ChannelMetadata, MeasurementRunIndex
from selection.tacho import find_tacho_channel
from session.data_pool import DeadLink, find_dropped_channel


NOT_LOADED_REFUSAL = "ERROR: Cannot add channels of '{file_name}' -- its file is not currently loaded."
_NOT_FOUND_REFUSAL = "ERROR: Cannot add '{channel_name}' -- its channel was not found on '{file_name}'."


@dataclass(frozen=True)
class DroppedChannel:
    """A drop descriptor resolved against the Data Pool: the pooled run and
    channel it names and, once a tracked lane resolved it, its file's tacho
    (None for a lane that needs none or when the dock's own tacho serves)."""

    descriptor: dict
    run_index: MeasurementRunIndex
    channel_meta: ChannelMetadata
    tacho_meta: ChannelMetadata | None = None

    @property
    def row(self) -> tuple:
        """The `(run_index, channel_meta, label)` row a double click on the same
        Data Pool row hands to Workspace.open_channels_tab."""
        return self.run_index, self.channel_meta, self.descriptor["channel_name"]


def resolve_dropped_channels(
    descriptors: Iterable[Mapping],
    run_lookup: Callable[[str], MeasurementRunIndex | DeadLink],
    log: Callable[[str], None],
    *,
    refused_paths: set | None = None,
) -> list[DroppedChannel]:
    """The pooled channels ``descriptors`` name, in drop order; ``run_lookup``
    is ``DataPool.run_lookup``.

    A descriptor whose file the pool does not hold is refused with one line
    per file -- ``refused_paths`` carries the files already refused across the
    calls of one drop; one whose channel the file does not hold is refused with
    a line of its own. No bare run is made up from the descriptor alone.
    """
    refused = set() if refused_paths is None else refused_paths
    channels = []
    for descriptor in descriptors:
        path = descriptor["file_path"]
        run = run_lookup(path)
        if isinstance(run, DeadLink):
            if path not in refused:
                refused.add(path)
                log(NOT_LOADED_REFUSAL.format(file_name=descriptor["file_name"]))
            continue
        channel = find_dropped_channel(run, descriptor["channel_name"], descriptor["channel_index"])
        if channel is None:
            log(_NOT_FOUND_REFUSAL.format(channel_name=descriptor["channel_name"],
                                          file_name=run.file_name))
            continue
        channels.append(DroppedChannel(descriptor, run, channel))
    return channels


def resolve_tacho_per_file(
    channels: Iterable[DroppedChannel],
    dock_tacho_path: str | None,
) -> tuple[list[DroppedChannel], list[DroppedChannel]]:
    """``channels`` with their file's tacho, resolved once per file, and the
    first channel of every file without one -- the order its refusal is said in.

    A channel of the file the dock's own tacho comes from takes that tacho:
    it is already a resolved block, so the file is not searched for one.
    """
    served, refused = [], []
    tacho_by_path: dict[str, ChannelMetadata | None] = {}
    for channel in channels:
        path = channel.descriptor["file_path"]
        if path == dock_tacho_path:
            served.append(channel)
            continue
        if path not in tacho_by_path:
            tacho_by_path[path] = find_tacho_channel(channel.run_index)
            if tacho_by_path[path] is None:
                refused.append(channel)
        tacho = tacho_by_path[path]
        if tacho is not None:
            served.append(DroppedChannel(channel.descriptor, channel.run_index,
                                         channel.channel_meta, tacho))
    return served, refused


def build_channel_descriptors(rows: Iterable) -> list:
    """
    The drop descriptors of `(run_index, channel_meta, label)` rows -- the
    inverse of `resolve_dropped_channels`, in the shape a drag out of the Data
    Pool carries.
    """
    return [build_drop_descriptor(run_index, channel_meta) for run_index, channel_meta, _ in rows]
