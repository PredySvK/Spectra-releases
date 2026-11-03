"""
Legend text and display units for a plotted trace.

Two things: turning Pint's internal unit tokens back into the short labels an
NVH engineer reads ("gravity" -> "g"), and assembling the one-line legend a
trace carries.

Was a class of classmethods over a class-level dict -- a module wearing a
class's clothes, which is why the class name is gone rather than renamed.
"""

from typing import Any, Dict, Optional

from core.block_kinds import (
    KIND_ORDER_CUT,
    KIND_ORDER_RESIDUAL,
    KIND_OVERALL_LEVEL,
    META_EFFECTIVE_F_START,
    META_EFFECTIVE_F_STOP,
    PARAM_F_START,
    PARAM_F_STOP,
    PARAM_ORDER,
    STEP_READ,
)
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


def _curve_name(block: Any) -> str:
    """
    What a curve of `block` is, named after its channel: "Order 2", "OAL",
    "OAL 10–500 Hz", "Residual" -- or "" when the channel alone says it.

    An OAL only names its band when it is not the Full Bandwidth default: a
    Parameter Set's identity is the *requested* band (``provenance.params``),
    but a changed band is shown with the *effective* one (``metadata``) --
    what was actually integrated over this file after clipping to its
    Nyquist. An Imported order cut is named through
    ``source_meta["imported_order"]`` instead.
    """
    kind = getattr(block, "kind", None)
    if kind == KIND_ORDER_RESIDUAL:
        return "Residual"
    if kind == KIND_ORDER_CUT:
        order = block.provenance.params.get(PARAM_ORDER)
        if block.provenance.step == STEP_READ or order is None:
            return ""
        return f"Order {order:g}"
    if kind != KIND_OVERALL_LEVEL or block.provenance.step == STEP_READ:
        return ""     # an Imported level names its band in the file, not here
    params = block.provenance.params if block.provenance else {}
    if params.get(PARAM_F_START) == 10.0 and params.get(PARAM_F_STOP) is None:
        return "OAL"
    eff_lo = block.metadata.get(META_EFFECTIVE_F_START)
    eff_hi = block.metadata.get(META_EFFECTIVE_F_STOP)
    return f"OAL {eff_lo:g}–{eff_hi:g} Hz"


def build_legend_text(
    file_name: str,
    raw_channel_name: str,
    active_unit_str: str,
    source_meta: Optional[Dict[str, Any]] = None,
    block: Any = None,
) -> str:
    """
    The legend line for one trace: '[file.unv] Channel_1 Order 2 [g]'.

    The one legend rule for every curve -- base, overlay and every display
    rebuild -- so a curve's legend cannot change with how it got into the
    graph. `block` names what the curve is after the channel (``_curve_name``).
    """
    # 1. Standardize and strip operational text prefixes from the incoming sensor name
    clean_channel_name = strip_channel_name_prefix(raw_channel_name)
    curve_name = _curve_name(block)
    if curve_name:
        clean_channel_name += f" {curve_name}"
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
