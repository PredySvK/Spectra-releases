"""Pure planning for channel-drop tacho resolution."""

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from core.channel_drop import read_drop_descriptor
from core.models import ChannelMetadata, MeasurementRunIndex
from selection.tacho import find_tacho_channel
from session.data_pool import DeadLink


@dataclass(frozen=True)
class TachoRefusal:
    """A source file whose tacho could not be resolved for a drop: it has none,
    or -- ``not_loaded`` -- the Data Pool does not hold the file at all."""

    file_name: str
    file_path: str
    not_loaded: bool = False


@dataclass(frozen=True)
class TachoDropPlan:
    """Prepared worker inputs and source files refused during planning."""

    prepared: tuple[tuple[dict, str, MeasurementRunIndex, ChannelMetadata, ChannelMetadata | None], ...]
    refusals: tuple[TachoRefusal, ...]


def plan_tacho_per_file(
    descriptors: Iterable[Mapping],
    run_lookup: Callable[[str], MeasurementRunIndex | DeadLink],
    dock_tacho_path: str | None,
    *,
    against_time: bool,
) -> TachoDropPlan:
    """Prepare dropped channels and resolve each source file's tacho once.

    A dock tacho is already a resolved block, so its source file is never
    looked up through ``run_lookup`` (``DataPool.run_lookup``);
    a file it reports as a ``DeadLink`` is refused as ``not_loaded``. In time mode no tacho lookup is performed.
    The first descriptor from a file determines the order of refusal messages;
    later descriptors from the same refused file are skipped.
    """

    prepared = []
    refusals = []
    tacho_meta_by_path: dict[str, ChannelMetadata] = {}
    refused_paths: set[str] = set()

    for descriptor in descriptors:
        channel_name = descriptor["channel_name"]

        mock_run, mock_meta = read_drop_descriptor(descriptor)

        path = descriptor["file_path"]
        tacho_meta = None
        if not against_time and path != dock_tacho_path:
            if path in refused_paths:
                continue
            tacho_meta = tacho_meta_by_path.get(path)
            if tacho_meta is None:
                run = run_lookup(path)
                not_loaded = isinstance(run, DeadLink)
                tacho_meta = None if not_loaded else find_tacho_channel(run)
                if tacho_meta is None:
                    refused_paths.add(path)
                    refusals.append(TachoRefusal(descriptor["file_name"], path, not_loaded))
                    continue
                tacho_meta_by_path[path] = tacho_meta

        prepared.append((descriptor, channel_name, mock_run, mock_meta, tacho_meta))

    return TachoDropPlan(tuple(prepared), tuple(refusals))
