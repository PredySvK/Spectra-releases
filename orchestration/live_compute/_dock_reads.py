"""Disk-read payloads for the Order Tracking and Overall Level docks."""

from io_modules.data_accessor import DataAccessor
from orchestration.live_compute._payloads import read_two_channels
from selection.tacho import find_tacho_channel


def read_order_channels(run_index, vib_meta, tacho_block):
    """Read an order vibration channel and reuse or load its tacho block."""
    if tacho_block is None:
        return read_two_channels(run_index, vib_meta, find_tacho_channel(run_index))
    return DataAccessor.fetch_channel_data(run_index, vib_meta), tacho_block


def read_overall_level_channels(run_index, vib_meta, tacho_block, tracking_rpm):
    """Read Overall Level inputs, loading a tacho only for RPM tracking."""
    if tracking_rpm and tacho_block is None:
        tacho_meta = find_tacho_channel(run_index)
        if tacho_meta is not None:
            return read_two_channels(run_index, vib_meta, tacho_meta)
    return DataAccessor.fetch_channel_data(run_index, vib_meta), tacho_block


def lookup_cached_for_dock(finder, cache_kind, file_path, channel_name, params, wanted=None,
                           channel_index=None):
    """Perform one read-only cache lookup for a live dock worker."""
    if wanted is not None:
        return finder(
            file_path, channel_name, cache_kind, params,
            wanted_block_params=wanted, channel_index=channel_index,
        )
    return finder(file_path, channel_name, cache_kind, params, channel_index=channel_index)


def lookup_or_read_for_dock(lookup_args, is_cache_hit, read, read_args, channel_index=None):
    """
    The cache lookup and, on a miss, the raw read in one worker task (#504),
    so a miss never waits for a GUI callback before it reaches the disk.

    Returns ``(True, cached)`` on a hit, ``(False, read(*read_args))`` on a
    miss. A lookup that raises counts as a miss; a read that raises fails
    the task.
    """
    try:
        cached = lookup_cached_for_dock(*lookup_args, channel_index=channel_index)
    except Exception:
        cached = None
    if is_cache_hit(cached):
        return True, cached
    return False, read(*read_args)
