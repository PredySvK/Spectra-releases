"""
Channel identity parsing for the selection floor.

Selection floor: which subset of curves or measurements is relevant?
Channel identity answers whether two curves or measurements refer to the same
physical sensor and direction regardless of reader label formatting, and
which channel of a file a drop, a curve or a memo entry means -- by index,
because same-named channels share everything else.

What does not belong here: reading from disk or file format parsing (io_modules/),
how curves are drawn or Qt widgets (view_models/, gui/), or cache layout logic
(io_modules/result_cache/).
"""

from ._channel_identity import (
    build_channel_key,
    format_channel_identity,
    is_channel_name_unique,
    resolve_channel_at_index,
    resolve_stripped_override,
    split_channel_base_and_direction,
    strip_order_overlay_prefix,
    strip_reader_label_prefix,
)

__all__ = [
    "build_channel_key",
    "format_channel_identity",
    "is_channel_name_unique",
    "resolve_channel_at_index",
    "resolve_stripped_override",
    "split_channel_base_and_direction",
    "strip_order_overlay_prefix",
    "strip_reader_label_prefix",
]
