# =====================================================================
# FILE: core/channel_drop.py
# =====================================================================
"""
The drop descriptor: the dict a channel carries into a graph or a tab.

A Data Pool drag, a Selection, a restored overlay and a companion curve all
hand a channel on as this dict; a graph-to-graph drag too, once
`core.data_block.read_display_meta` has turned the curve's display meta back
into the channel's address. It is the channel's address -- file, name and
index -- plus the block kind the drop is split into lanes by. Every other
channel fact is the pooled channel's: the drop finds the channel in the Data
Pool (`resolve_dropped_channels`) and computes with that one, so a new channel
fact needs no key here.

The dict stays plain: it travels as mime JSON and sits in pending drops, and
routes add keys of their own (`orders_to_extract`).
"""

from typing import Any, Dict

from core.models import ChannelMetadata, MeasurementRunIndex, resolve_channel_block_kind

RECIPE_KEY = "compute_spec"
"""The key a restored overlay's descriptor carries its saved recipe under
(`TraceSpec.compute_spec`): a drop that carries one is computed with it laid
over the ribbon, not with the ribbon alone."""

TAB_CACHE_KEY = "tab_cache_file"
"""The key a restored overlay's descriptor carries its saved Tab cache file
name under (`TraceSpec.tab_cache_file`): the drop reads that file before it
computes anything."""


def build_drop_descriptor(run: MeasurementRunIndex, channel: ChannelMetadata) -> Dict[str, Any]:
    """The drop descriptor of one channel of `run`, with this session's channel index."""
    return {
        "file_path": str(run.file_path),
        "file_name": str(run.file_name),
        "channel_index": int(channel.index),
        "channel_name": str(channel.name),
        "block_kind": resolve_channel_block_kind(channel),
    }
