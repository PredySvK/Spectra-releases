"""Disk-read payloads for the Order Tracking and Overall Level docks."""

from io_modules.data_accessor import DataAccessor
from orchestration.live_compute._payloads import read_two_channels
from selection.tacho import find_tacho_channel


def read_order_channels(run_index, vib_meta, tacho_block, tacho_meta=None):
    """Read an order vibration channel and reuse or load its tacho block --
    `tacho_meta`, or the run's own when None; a run with no tacho channel
    gives None for it, for the compute to refuse."""
    if tacho_block is None:
        tacho_meta = tacho_meta or find_tacho_channel(run_index)
        if tacho_meta is not None:
            return read_two_channels(run_index, vib_meta, tacho_meta)
    return DataAccessor.fetch_channel_data(run_index, vib_meta), tacho_block


def read_overall_level_channels(run_index, vib_meta, tacho_block, tracking_rpm, tacho_meta=None):
    """Read Overall Level inputs, loading a tacho (`tacho_meta`, or the run's
    own when None) only for RPM tracking."""
    if tracking_rpm and tacho_block is None:
        tacho_meta = tacho_meta or find_tacho_channel(run_index)
        if tacho_meta is not None:
            return read_two_channels(run_index, vib_meta, tacho_meta)
    return DataAccessor.fetch_channel_data(run_index, vib_meta), tacho_block
