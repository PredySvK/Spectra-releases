"""
Legend text and display units for a plotted trace.

Two things: turning Pint's internal unit tokens back into the short labels an
NVH engineer reads ("gravity" -> "g"), and assembling the one-line legend a
trace carries.

Was a class of classmethods over a class-level dict -- a module wearing a
class's clothes, which is why the class name is gone rather than renamed.
"""

from typing import Any, Dict, Mapping, Optional

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
from core.filter_card_config import COLUMN_ANALYSIS_TYPE, COLUMN_CHANNEL, COLUMN_FILE_NAME
from core.legend_config import FIELD_RESULT_NAME, FIELD_UNIT, LegendConfig
from core.unit_label import resolve_unit_label
from core.units import strip_channel_name_prefix
from selection.trace_filter import format_result_kind
from view_models.display_prefix import resolve_number_format

# The parts a curve itself knows; every other key is read off its Curve metadata record.
_CURVE_OWN_FIELDS = frozenset((COLUMN_FILE_NAME, COLUMN_CHANNEL, FIELD_RESULT_NAME, FIELD_UNIT))

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
    Nyquist. An order cut is "Order N" whether computed
    or Imported.
    """
    kind = getattr(block, "kind", None)
    if kind == KIND_ORDER_RESIDUAL:
        return "Residual"
    if kind == KIND_ORDER_CUT:     # computed or Imported: the same name, so the two compare (§1.315)
        order = block.provenance.params.get(PARAM_ORDER)
        return "" if order is None else f"Order {order:g}"
    if kind != KIND_OVERALL_LEVEL or block.provenance.step == STEP_READ:
        return ""     # an Imported level names its band in the file, not here
    params = block.provenance.params if block.provenance else {}
    if params.get(PARAM_F_START) == 10.0 and params.get(PARAM_F_STOP) is None:
        return "OAL"
    eff_lo = block.metadata.get(META_EFFECTIVE_F_START)
    eff_hi = block.metadata.get(META_EFFECTIVE_F_STOP)
    return f"OAL {eff_lo:g}–{eff_hi:g} Hz"


def _result_name(curve_name: str, source_meta: Optional[Dict[str, Any]]) -> str:
    """
    The Result name part: the curve name, else an Imported order cut's order
    from `source_meta` ("Order ?" when its file does not say it).
    """
    if curve_name or source_meta is None or "imported_order" not in source_meta:
        return curve_name
    order = source_meta["imported_order"]
    return "Order ?" if order is None else f"Order {order:g}"


def format_curve_metadata_value(key: str, value: Any) -> str:
    """One Curve metadata value as the Cursor Box and the Curve name read it:
    numbers in the Auto format, dates as stored ISO text, Analysis type through
    its result-kind label; "" for no value."""
    if value is None:
        return ""
    if key == COLUMN_ANALYSIS_TYPE:
        return format_result_kind(value)
    if isinstance(value, float):
        return resolve_number_format("", None).format(value)
    return str(value)


def legend_reads_curve_metadata(config: LegendConfig) -> bool:
    """Whether a Curve name by ``config`` has a part only the Curve metadata record knows."""
    return any(key not in _CURVE_OWN_FIELDS for key in config.fields)


def build_legend_text(
    file_name: str,
    raw_channel_name: str,
    active_unit_str: str,
    source_meta: Optional[Dict[str, Any]] = None,
    block: Any = None,
    config: LegendConfig = LegendConfig(),
    curve_metadata: Optional[Mapping[str, Any]] = None,
) -> str:
    """
    The Curve name for one trace: '[file.unv] Channel_1 Order 2 [g]'.

    The one legend rule for every curve -- base, overlay and every display
    rebuild -- so a curve's legend cannot change with how it got into the
    graph. Parts follow `config` in Priority order, joined by a space; File name
    and Unit go in [ ], every other part is its bare value; a part with no
    value is skipped. `block` names what the curve is after the channel
    (``_curve_name``). Every other part -- Parameter set, a Raw or Excel field,
    Direction... -- is the curve's value in ``curve_metadata``, its Curve metadata
    record (``view_models.curve_metadata.build_curve_metadata``, the record the
    Cursor reads); File name and Channel stay the curve's own.
    """
    # Keep only the file's own name, discarding the directory path
    file_label = str(file_name).strip()
    file_label = file_label.split("/")[-1].split("\\")[-1]
    if file_label and not file_label.startswith("["):
        file_label = f"[{file_label}]"

    polished_unit = format_display_unit(active_unit_str)
    values = {
        COLUMN_FILE_NAME: file_label,
        COLUMN_CHANNEL: strip_channel_name_prefix(raw_channel_name),
        FIELD_RESULT_NAME: _result_name(_curve_name(block), source_meta),
        FIELD_UNIT: f"[{polished_unit}]" if polished_unit else "",
    }
    record = curve_metadata or {}
    parts = (values[key] if key in _CURVE_OWN_FIELDS else format_curve_metadata_value(key, record.get(key))
             for key in config.fields)
    return " ".join(part for part in parts if part)


def base_display_unit(raw_unit: str) -> str:
    """
    The plain physical unit behind a spectral label.

    Axis labels read 'g RMS' or '(g)^2/Hz' depending on the display format,
    but Band RMS is always an RMS in the underlying unit, so the decoration
    is stripped rather than repeated. Callers resolve `raw_unit` themselves
    first -- the Band RMS readout falls back from a 'dB' axis unit to a
    trace's/block's own source unit before calling this.
    """
    return format_display_unit(resolve_unit_label(raw_unit).unit)
