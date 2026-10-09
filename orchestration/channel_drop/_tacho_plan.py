"""Pure planning for channel-drop tacho resolution."""

from dataclasses import dataclass
from typing import Iterable, Mapping

from core.models import ChannelMetadata, MeasurementRunIndex
from selection.tacho import find_tacho_channel


@dataclass(frozen=True)
class TachoRefusal:
    """A source file whose tacho could not be resolved for a drop."""

    file_name: str
    file_path: str


@dataclass(frozen=True)
class TachoDropPlan:
    """Prepared worker inputs and source files refused during planning."""

    prepared: tuple[tuple[dict, str, MeasurementRunIndex, ChannelMetadata, ChannelMetadata | None], ...]
    refusals: tuple[TachoRefusal, ...]


def plan_tacho_per_file(
    descriptors: Iterable[Mapping],
    runs_by_path: Mapping[str, MeasurementRunIndex],
    dock_tacho_path: str | None,
    *,
    against_time: bool,
) -> TachoDropPlan:
    """Prepare dropped channels and resolve each source file's tacho once.

    A dock tacho is already a resolved block, so its source file is never
    looked up in ``runs_by_path``. In time mode no tacho lookup is performed.
    The first descriptor from a file determines the order of refusal messages;
    later descriptors from the same refused file are skipped.
    """

    prepared = []
    refusals = []
    tacho_meta_by_path: dict[str, ChannelMetadata] = {}
    refused_paths: set[str] = set()

    for descriptor in descriptors:
        channel_name = descriptor["channel_name"]

        mock_run = MeasurementRunIndex(descriptor["file_name"], descriptor["file_path"])
        mock_meta = ChannelMetadata(
            descriptor["channel_index"],
            channel_name,
            descriptor["channel_type"],
            descriptor["unit"],
        )
        mock_meta.block_kind = descriptor.get("block_kind")
        mock_meta.func_type = descriptor.get("func_type", mock_meta.func_type)

        path = descriptor["file_path"]
        tacho_meta = None
        if not against_time and path != dock_tacho_path:
            if path in refused_paths:
                continue
            tacho_meta = tacho_meta_by_path.get(path)
            if tacho_meta is None:
                tacho_meta = find_tacho_channel(runs_by_path.get(path))
                if tacho_meta is None:
                    refused_paths.add(path)
                    refusals.append(TachoRefusal(descriptor["file_name"], path))
                    continue
                tacho_meta_by_path[path] = tacho_meta

        prepared.append((descriptor, channel_name, mock_run, mock_meta, tacho_meta))

    return TachoDropPlan(tuple(prepared), tuple(refusals))
