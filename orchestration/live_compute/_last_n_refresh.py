"""Which curves a Refresh Last N recomputes."""

from typing import Any, Mapping, Optional, Sequence, Tuple


def plan_last_n_refresh(
    overlays: Sequence[Mapping[str, Any]],
    n: int,
    base_channel: Optional[Tuple[str, int]],
) -> Optional[Tuple[Mapping[str, Any], ...]]:
    """
    The drop descriptors of the `n` most recently added overlays of a graph, or
    None when `n` reaches back to the Base curve, which is exactly a plain Refresh.

    The Base curve is always the oldest curve on a graph, so it counts as one of
    the N only once N covers every curve. An order tab's own extra order cuts
    share the Base curve's `base_channel` -- `(file_path, channel_index)` -- without
    being its Base curve; they are no overlay.
    """
    overlays = [
        descriptor for descriptor in overlays
        if (descriptor["file_path"], descriptor["channel_index"]) != base_channel
    ]
    if n < 1 or n >= len(overlays) + 1:
        return None
    return tuple(overlays[-n:])
