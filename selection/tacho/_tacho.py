def find_tacho_channel(run_index):
    """Return the first tacho channel of a run, or ``None`` when it has none."""
    if run_index is None:
        return None
    for channel_meta in getattr(run_index, "available_channels", {}).values():
        if getattr(channel_meta, "type", None) == "tacho":
            return channel_meta
    return None


def tacho_missing(run_index, *, tacho_bound: bool = False, tracking_mode: str = "rpm") -> bool:
    """True when an analysis tracked against RPM has no tacho to read.

    Time mode never needs one. ``tacho_bound`` means a tacho block is already
    attached (a dock refresh), so the run need not offer a channel any more.
    """
    if tracking_mode != "rpm" or tacho_bound:
        return False
    return find_tacho_channel(run_index) is None
