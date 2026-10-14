# =====================================================================
# FILE: core/channel_drop.py
# =====================================================================
"""
The drop descriptor: the dict a channel carries into a graph or a tab.

A Data Pool drag, a Selection, a restored overlay and a companion curve all
hand a channel on as this dict, and the drop route turns it back into a
channel. Both directions live here, so a new channel fact (as Source amplitude
was) is added once and every route carries it. A graph-to-graph drag goes
through here too: `core.data_block.read_display_meta` turns the curve's
display meta back into a channel first.

The dict stays plain: it travels as mime JSON, sits in pending drops and in
saved projects, and routes add keys of their own (`orders_to_extract`,
`memo_key`).
"""

from typing import Any, Dict, Tuple

from core.models import ChannelMetadata, MeasurementRunIndex, resolve_channel_block_kind


def build_drop_descriptor(run: MeasurementRunIndex, channel: ChannelMetadata) -> Dict[str, Any]:
    """The drop descriptor of one channel of `run`, with this session's channel index."""
    descriptor = {
        "file_path": str(run.file_path),
        "file_name": str(run.file_name),
        "channel_index": int(channel.index),
        "channel_name": str(channel.name),
        "channel_type": str(channel.type),
        "unit": str(channel.unit),
        "block_kind": resolve_channel_block_kind(channel),
        "func_type": channel.func_type,
    }
    # Empty means the project has no answer and the reader's default stands,
    # so it is left out rather than written as "".
    if channel.source_amplitude:
        descriptor["source_amplitude"] = channel.source_amplitude
    return descriptor


def read_drop_descriptor(descriptor) -> Tuple[MeasurementRunIndex, ChannelMetadata]:
    """
    The run and channel a descriptor names, built from the descriptor alone.

    The run is bare (no other channels, no metadata); a caller that has the
    file loaded prefers the pool's own channel and falls back to this.
    """
    run = MeasurementRunIndex(descriptor["file_name"], descriptor["file_path"])
    channel = ChannelMetadata(descriptor["channel_index"], descriptor["channel_name"],
                              descriptor["channel_type"], descriptor["unit"])
    channel.block_kind = descriptor.get("block_kind")
    channel.func_type = descriptor.get("func_type", channel.func_type)
    if descriptor.get("source_amplitude"):
        channel.source_amplitude = descriptor["source_amplitude"]
    return run, channel
