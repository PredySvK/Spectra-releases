"""A curve's identity: its channel (file, channel index) and, for an order curve, its order."""

from typing import Any, Optional, Tuple

from core.block_kinds import PARAM_ORDER
from selection.channel_identity import build_channel_key


def resolve_curve_channel_key(trace: Any) -> Tuple[str, int]:
    """The ``build_channel_key`` of the channel ``trace`` was computed from,
    read off its ``meta_ref``; ``("", 0)`` for a curve without one (an h5
    result-set curve), which matches no dropped channel."""
    meta = trace.meta_ref or {}
    return build_channel_key(meta.get("file_path", ""), meta.get("channel_index", 0))


def resolve_order_curve_identity(trace: Any) -> Optional[Tuple[str, int, float]]:
    """(file path, channel index, order) of an order-cut ``trace``, or None.

    The index is normalised to ``int`` and the order to ``float`` so an order
    written as ``2`` and as ``2.0`` (or an index read back as ``"2"``) is one
    identity -- a repeated drop of the same channel must not plot a duplicate
    (#665 C02). None for a trace without file/channel meta or without an order.
    """
    meta = trace.meta_ref or {}
    order = (trace.compute_spec or {}).get(PARAM_ORDER)
    if "file_path" not in meta or "channel_index" not in meta or order is None:
        return None
    return (*build_channel_key(meta["file_path"], meta["channel_index"]), float(order))
