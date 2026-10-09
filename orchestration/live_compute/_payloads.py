# =====================================================================
# FILE: orchestration/live_compute/_payloads.py
# =====================================================================
"""
Background worker payloads for interactive analysis tabs.

Plain functions (no Qt, no AppContext) run inside worker tasks by
Workspace -- pulled out of gui/ into orchestration/ so the
"nothing here may touch a Qt object" boundary is physical, not just a
banner comment. The slow part (disk I/O) never runs on the GUI thread; only the callbacks back in gui/, which run
on the GUI thread, touch a dock.
"""

from io_modules.data_accessor import DataAccessor


def read_two_channels(run_index, vib_meta, tacho_meta):
    """A vibration channel plus its tacho -- shared by Order Tracking's "open a
    tab" path and LiveOrderResults's live-compute dispatch."""
    vib_block = DataAccessor.fetch_channel_data(run_index, vib_meta)
    tacho_block = DataAccessor.fetch_channel_data(run_index, tacho_meta)
    return vib_block, tacho_block


def read_spectrogram_channels(run_index, channel_meta, tacho_candidates):
    """
    Reads the vibration channel and, if the caller supplied auto-link
    candidates (RPM tracking requested with no tacho bound yet), the first
    "tacho"-typed one of them that actually reads -- mirrors the original
    inline try-each-candidate loop this replaces.

    Returns (vib_block, tacho_block_or_None, tacho_meta_used_or_None).
    """
    vib_block = DataAccessor.fetch_channel_data(run_index, channel_meta)

    tacho_block = None
    tacho_meta_used = None
    for _label, candidate_meta in tacho_candidates:
        if candidate_meta.type != "tacho":
            continue
        try:
            tacho_block = DataAccessor.fetch_channel_data(run_index, candidate_meta)
            tacho_meta_used = candidate_meta
            break
        except Exception:
            continue

    return vib_block, tacho_block, tacho_meta_used
