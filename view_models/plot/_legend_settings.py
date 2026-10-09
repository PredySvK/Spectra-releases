"""
Legend text and display units for a plotted trace.

Two things: turning Pint's internal unit tokens back into the short labels an
NVH engineer reads ("gravity" -> "g"), and assembling the one-line legend a
trace carries.

Was a class of classmethods over a class-level dict -- a module wearing a
class's clothes, which is why the class name is gone rather than renamed.
"""

from typing import Any, Dict, Optional

from core.units import strip_channel_name_prefix

# Maps Pint's internal calculation tokens back into the canonical short display
# representations used on the UI canvas.
_CANONICAL_DISPLAY_UNITS = {
    "gravity": "g",
    "volt": "V",
    "millivolt": "mV",
    "pascal": "Pa",
    "hertz": "Hz",
    "meter/second**2": "m/s2",
    "millimeter/second**2": "mm/s2",
    "dimensionless": "dimensionless",
}


def format_display_unit(internal_pint_unit: str) -> str:
    """Translates raw Pint execution tokens back into short industry standard labels."""
    if not internal_pint_unit:
        return ""
    # Fallback to the original input string token if not registered inside our display matrix
    return _CANONICAL_DISPLAY_UNITS.get(str(internal_pint_unit).strip(), internal_pint_unit)


def build_legend_text(
    file_name: str,
    raw_channel_name: str,
    active_unit_str: str,
    source_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """
    The legend line for one trace: '[file.unv] Channel_1 [g]'.

    Expandable to richer templates like '{acquisition_date} | {sensor_name}';
    `source_meta` is where the extra attributes would come from.
    """
    # 1. Standardize and strip operational text prefixes from the incoming sensor name
    clean_channel_name = strip_channel_name_prefix(raw_channel_name)
    if source_meta is not None and "imported_order" in source_meta:
        order = source_meta["imported_order"]
        order_label = "?" if order is None else f"{order:g}"
        clean_channel_name += f" (imported result, order {order_label})"

    # 2. Keep only the file's own name, discarding the directory path
    clean_file_label = str(file_name).strip()
    if "/" in clean_file_label:
        clean_file_label = clean_file_label.split("/")[-1]
    if "\\" in clean_file_label:
        clean_file_label = clean_file_label.split("\\")[-1]

    # Ensure the filename is always enclosed in square brackets
    if clean_file_label and not clean_file_label.startswith("["):
        clean_file_label = f"[{clean_file_label}]"

    # 3. Cleanse internal Pint output tokens using the reverse lookup above
    polished_unit = format_display_unit(active_unit_str)

    if clean_file_label:
        return f"{clean_file_label} {clean_channel_name} [{polished_unit}]"

    return f"{clean_channel_name} [{polished_unit}]"


def base_display_unit(raw_unit: str) -> str:
    """
    The plain physical unit behind a spectral label.

    Axis labels read 'g RMS' or '(g)^2/Hz' depending on the display format,
    but Band RMS is always an RMS in the underlying unit, so the decoration
    is stripped rather than repeated. Callers resolve `raw_unit` themselves
    first -- BandRmsCursorsMixin falls back from a 'dB' axis unit to a
    trace's/block's own source unit before calling this.
    """
    unit = (raw_unit or "").strip()
    for suffix in (" RMS", " PEAK", " Peak", " rms", " peak"):
        if unit.endswith(suffix):
            unit = unit[: -len(suffix)]
            break
    if unit.startswith("(") and ")" in unit:
        unit = unit[1:unit.index(")")]
    return format_display_unit(unit)
