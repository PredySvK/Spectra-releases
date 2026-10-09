# =====================================================================
# FILE: io_modules/result_cache/cache_naming.py
# =====================================================================
"""
Turns a "Calculate & Save Data" selection into a readable result-set label
and provides filename-safe sanitization for result cache files.
"""
import re
from typing import Dict, List, Optional, Sequence, Tuple

_NOT_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]")
_WHITESPACE_RE = re.compile(r"\s+")
_REPEATED_UNDERSCORE_RE = re.compile(r"_{2,}")


def sanitize_for_filename(text: str) -> str:
    """Collapses whitespace to underscores and drops anything not filename-safe."""
    return _strip_to_filename_safe(text) or "Channel"


def _strip_to_filename_safe(text: str) -> str:
    text = _WHITESPACE_RE.sub("_", text.strip())
    text = _NOT_FILENAME_SAFE_RE.sub("", text)
    return _REPEATED_UNDERSCORE_RE.sub("_", text).strip("_")


def sanitize_result_set_label(text: str) -> str:
    """
    A user-typed result-set name reduced to something safe to be a folder name.

    Same rules as sanitize_for_filename but returns "" (not "Channel") when
    nothing survives, so begin_result_set can tell "user typed junk" from "user
    typed nothing" -- the label decides the on-disk folder, and an unsanitised
    one could escape the cache dir (`..\\..\\x`) or land shards straight over
    `cache/scan/` (audit 02 finding 5.1). `. / \\ :` and whitespace all go, so
    the service suffixes `.staging` / `.retired` stay uncollidable too.
    """
    return _strip_to_filename_safe(text)


def _format_order_token(order: float) -> str:
    return str(int(order)) if float(order).is_integer() else str(order)


def build_order_component(orders: Sequence[float]) -> str:
    """
    "1x" for a single order, "1x5x" for a scattered few, "1-5x" for a
    consecutive integer run -- the range form only kicks in when every value
    is a whole number and they are actually consecutive, so 1, 2, 4.5 still
    spells out each one.
    """
    values = sorted(float(o) for o in orders)
    if not values:
        return "0x"

    all_integers = all(v.is_integer() for v in values)
    is_consecutive_run = (
        all_integers and len(values) >= 2
        and all(values[i + 1] - values[i] == 1 for i in range(len(values) - 1))
    )
    if is_consecutive_run:
        return f"{int(values[0])}-{int(values[-1])}x"

    return "".join(f"{_format_order_token(v)}x" for v in values)


def build_channel_component(selected_base_directions: Dict[str, List[Optional[str]]],
                            total_available_bases: int) -> str:
    """
    One sensor -> its (sanitised) name, with directions collapsed onto the end
    ("Inverter_Cover_X", "Inverter_Cover_XYZ"). Several sensors -> "All_Channels"
    when every available one was picked, otherwise "{N}_Channels" -- naming
    each one would make the filename unreadable once more than a couple are
    selected.
    """
    bases = list(selected_base_directions.keys())

    if len(bases) == 1:
        base = sanitize_for_filename(bases[0])
        directions = sorted(d for d in selected_base_directions[bases[0]] if d)
        if not directions:
            return base
        if len(directions) == 1:
            return f"{base}_{directions[0]}"
        return f"{base}_{''.join(directions)}"

    if total_available_bases > 0 and len(bases) >= total_available_bases:
        return "All_Channels"
    return f"{len(bases)}_Channels"


def build_result_set_label(orders: Sequence[float],
                           selected_base_directions: Dict[str, List[Optional[str]]],
                           total_available_bases: int, *,
                           channel_component: Optional[str] = None) -> str:
    order_component = build_order_component(orders)
    if channel_component is None:
        channel_component = build_channel_component(selected_base_directions, total_available_bases)
    return f"Order_Tracking_{order_component}_{channel_component}"


# What a result set of each kind is called, and which parameter distinguishes
# two sets of that kind at a glance. Order cuts are not in here: their label is
# built by build_result_set_label above, whose exact spelling predates §1.21 and
# is what every already-saved project's folder is named.
_KIND_LABEL_PARTS = {
    "spectrum": ("Spectrum", "fft_size"),
    "spectrogram": ("Spectrogram", "fft_size"),
    "overall_level": ("Overall_Level", "fft_size"),
    "time_response": ("Time", ""),
}


def build_kind_result_set_label(kind: str, params: Dict[str, object],
                                channel_component: str) -> str:
    """
    A readable folder name for a result set of any kind.

    Order cuts keep going through build_result_set_label so that
    "Order_Tracking_1x_All_Channels" stays exactly what it always was -- a
    project's existing cache folders are named that, and renaming the scheme
    would orphan them. Everything else gets "{Kind}_{distinguishing param}_
    {channels}"; a label only has to be readable and unique, since what a set
    was actually computed with is the params hash, not its name.
    """
    if kind == "order_cut":
        raise ValueError("Order-cut labels are built by build_result_set_label().")

    name, param_key = _KIND_LABEL_PARTS.get(kind, (sanitize_for_filename(kind).title(), ""))
    value = params.get(param_key) if param_key else None
    middle = f"{value}_" if value is not None else ""
    return f"{name}_{middle}{channel_component}"
