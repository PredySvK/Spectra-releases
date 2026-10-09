"""Pure validation and preparation for result-content channel drops."""

import dataclasses
from dataclasses import dataclass
from typing import Iterable, Mapping, NamedTuple

from core.dsp_configs import OrderTrackingConfig
from selection.channel_identity import build_channel_key, resolve_channel_at_index
from selection.tacho import find_tacho_channel


class ResultContentMemoKey(NamedTuple):
    """
    Identity of one live order result: which channel of which file, computed
    with which settings, with the cache asked or not, against the file as it is
    on disk now. The size/mtime are part of it because the live memo outlives
    a re-measured file -- without them a dock kept plotting curves computed from
    the previous contents of that path.
    """

    file_path: str
    channel_index: int
    config_items: tuple
    use_cache: bool
    size: object
    mtime_ns: object


@dataclass(frozen=True)
class ResultContentDropPlan:
    """The data needed by the GUI to accept or refuse one result-content drop."""

    accepted: bool
    message: str | None = None
    run: object | None = None
    tacho_meta: object | None = None
    channel_meta: object | None = None
    channel_name: str | None = None
    memo_key: ResultContentMemoKey | None = None


def result_content_memo_key(
    file_path: str,
    channel_index: int,
    config: OrderTrackingConfig,
    source_stamp: Mapping | None,
    use_cache: bool = True,
) -> ResultContentMemoKey:
    """Lists in the config (e.g. orders_to_extract) are flattened to tuples so
    the key is hashable."""
    config_items = tuple(
        sorted(
            (name, tuple(value) if isinstance(value, list) else value)
            for name, value in dataclasses.asdict(config).items()
        )
    )
    stamp = source_stamp or {}
    return ResultContentMemoKey(
        *build_channel_key(file_path, channel_index),
        config_items,
        use_cache,
        stamp.get("size"),
        stamp.get("mtime_ns"),
    )


def plan_result_content_drop(
    descriptor: Mapping,
    runs_by_path: Mapping[str, object],
    seen_keys: Iterable[tuple],
    config: OrderTrackingConfig,
    source_stamp: Mapping | None,
    use_cache: bool = True,
) -> ResultContentDropPlan:
    """Validate a drop and prepare the worker inputs without Qt or I/O.

    ``source_stamp`` is captured by the GUI-side file-stamp operation and passed
    in as data so this decision remains deterministic and testable. ``seen_keys``
    contains the dock's already accepted ``build_channel_key`` keys.
    """
    file_path = descriptor["file_path"]
    channel_index = descriptor["channel_index"]
    channel_name = descriptor["channel_name"]
    if build_channel_key(file_path, channel_index) in set(seen_keys):
        return ResultContentDropPlan(False)

    run = runs_by_path.get(file_path)
    if run is None:
        return ResultContentDropPlan(
            False,
            f"ERROR: Cannot add '{channel_name}' to the comparison -- its file is not currently loaded.",
            channel_name=channel_name,
        )

    tacho_meta = find_tacho_channel(run)
    if tacho_meta is None:
        return ResultContentDropPlan(
            False,
            f"ERROR: Cannot add '{channel_name}' -- '{run.file_name}' has no tacho channel.",
            run=run,
            channel_name=channel_name,
        )

    channel = resolve_channel_at_index(run.available_channels, channel_index)
    if channel is None:
        return ResultContentDropPlan(
            False,
            f"ERROR: Cannot add '{channel_name}' -- its channel metadata was not found on '{run.file_name}'.",
            run=run,
            tacho_meta=tacho_meta,
            channel_name=channel_name,
        )

    return ResultContentDropPlan(
        True,
        run=run,
        tacho_meta=tacho_meta,
        channel_meta=channel[1],
        channel_name=channel_name,
        memo_key=result_content_memo_key(
            file_path, channel_index, config, source_stamp, use_cache=use_cache
        ),
    )
