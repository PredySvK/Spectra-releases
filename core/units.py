# =====================================================================
# FILE: core/units.py
# =====================================================================
"""
Core Physical Unit System Engine utilizing Pint framework.
Manages legacy engineering string conversions, cross-dimensional validations,
and high-speed vectorized NumPy arrays adjustments.
Now includes Smart Spectral Parsing to scale complex DSP formats instantly post-FFT.
"""

import logging
import re
from dataclasses import dataclass

import numpy as np
from pint import UnitRegistry, UndefinedUnitError

from core.axis_projections import X_AXIS_NATIVE

logger = logging.getLogger(__name__)


@dataclass
class UnitPreferences:
    """
    The global display units, as a plain value object instead of the whole
    AppContext: the four convert_signal_to_global_unit needs for the Y axis,
    and the X axis unit (core.axis_projections.X_AXIS_UNITS, issue #459) a
    graph shows its frequency and speed axes in.

    core/ is meant to be the leaf everything else depends on and which depends
    on nothing in the project itself; taking AppContext (the outermost, most
    session-specific object in the app) as a parameter inverted that. AppContext
    builds one of these via unit_preferences() and hands it down; this module
    never needs to know AppContext exists.
    """
    acceleration: str = "g"
    pressure: str = "Pa"
    voltage: str = "V"
    speed: str = "rpm"
    x_axis_unit: str = X_AXIS_NATIVE

# Initialize a single, top-level centralized unit framework companion for the active process.
_UREG = UnitRegistry()

_UNV_UNIT_MAPPING = {
    'g': 'g',
    'v': 'V',
    'volt': 'V',
    'mv': 'mV',
    'millivolt': 'mV',
    'pa': 'Pa',
    'pascal': 'Pa',
    'bar': 'bar',
    'mbar': 'mbar',
    'rpm': 'rpm',
    'hz': 'Hz',
    'hertz': 'Hz',
    'rad/s': 'rad/s',
    'm/s2': 'm/s2',
    'm/s²': 'm/s2',
    'm/s**2': 'm/s2',
    'm/s^2': 'm/s2',
    'mm/s2': 'mm/s2',
    'mm/s²': 'mm/s2',
    'mm/s**2': 'mm/s2',
    'mm/s^2': 'mm/s2',
}

_SW_CANONICAL_GROUPS = [
    ["g", "m/s2", "mm/s2"],  # Domain Index 0: Acceleration
    ["Pa", "bar", "mbar"],   # Domain Index 1: Acoustic / fluid pressure
    ["V", "mV"],             # Domain Index 2: Electrical voltage
    ["rpm", "Hz", "rad/s"]   # Domain Index 3: Rotational speed / frequency
]


def sanitize_unit_string(raw_unit: str) -> str:
    """Standardizes raw engineering unit characters from file headers into clean internal tokens."""
    if not raw_unit:
        return 'dimensionless'
    cleaned = str(raw_unit).strip().lower()
    canonical = _UNV_UNIT_MAPPING.get(cleaned, raw_unit)

    pint_translation = {
        'g': 'gravity',
        'V': 'volt',
        'mV': 'millivolt',
        'Pa': 'pascal',
        'Hz': 'hertz',
        'm/s2': 'meter/second**2',
        'mm/s2': 'millimeter/second**2'
    }
    return pint_translation.get(canonical, canonical)


def check_units_compatibility(base_unit: str, incoming_unit: str) -> bool:
    """Evaluates whether two unit strings are dimensionally compatible."""
    # Strict fallback for complex spectral strings matching to bypass Pint errors safely
    if str(base_unit).lower().strip() == str(incoming_unit).lower().strip():
        return True

    sanitized_base = sanitize_unit_string(base_unit)
    sanitized_incoming = sanitize_unit_string(incoming_unit)

    for group in _SW_CANONICAL_GROUPS:
        if sanitized_base in group and sanitized_incoming in group:
            return True

    try:
        base_q = _UREG.Quantity(1, sanitized_base)
        incoming_q = _UREG.Quantity(1, sanitized_incoming)
        return base_q.is_compatible_with(incoming_q)
    except (UndefinedUnitError, TypeError):
        return False


# Pint units that read as a shaft speed. Against these, "hertz" means
# revolutions per second, not bare 1/s: Pint treats radian as dimensionless, so
# a literal hertz -> rad/s would come out as 1 Hz = 1 rad/s instead of 2*pi.
_ROTATIONAL_SPEED_UNITS = ("rpm", "rad/s")


def _resolve_linear_factor(sanitized_from: str, sanitized_to: str) -> float:
    """
    Scalar that turns one unit of `sanitized_from` into `sanitized_to`.

    The single conversion rule shared by convert_numeric_array and
    convert_signal_to_global_unit, so the speed domain cannot drift apart
    between them again. Raises whatever Pint raises on an impossible pair.
    """
    if sanitized_from == "hertz" and sanitized_to in _ROTATIONAL_SPEED_UNITS:
        sanitized_from = "revolution/second"
    elif sanitized_to == "hertz" and sanitized_from in _ROTATIONAL_SPEED_UNITS:
        sanitized_to = "revolution/second"
    return _UREG.Quantity(1.0, sanitized_from).to(sanitized_to).magnitude


def convert_numeric_array(y_data: np.ndarray, from_unit: str, to_unit: str, strict: bool = False) -> np.ndarray:
    """
    Performs lightning-fast vectorized conversion of raw numeric amplitudes.

    strict=False (default) preserves the historical fallback: a failed conversion
    logs a warning and returns the data unconverted, which is fine for GUI display
    paths where showing the raw value beats crashing. strict=True raises instead --
    required for DSP inputs like tacho-to-rpm, where silently feeding raw volts into
    order tracking produces a plausible-looking but physically wrong result, which is
    worse than a crash.
    """
    sanitized_from = sanitize_unit_string(from_unit)
    sanitized_to = sanitize_unit_string(to_unit)

    if sanitized_from == sanitized_to:
        return y_data

    try:
        # Resolve the conversion to a single scalar factor on a unit quantity,
        # then scale the raw array with plain numpy -- same approach as
        # convert_signal_to_global_unit. Wrapping the whole y_data in a Pint
        # quantity works too, but it re-parses the unit string and routes the
        # array multiply through Pint on every call for no gain.
        factor = _resolve_linear_factor(sanitized_from, sanitized_to)
        return y_data * factor
    except Exception as e:
        if strict:
            raise ValueError(
                f"Unit conversion failed from [{from_unit}] to [{to_unit}]: {e}"
            ) from e
        logger.warning("High-speed conversion failed from [%s] to [%s]: %s", from_unit, to_unit, e)
        return y_data


_ALL_SUPPORTED_UNITS = [u for group in _SW_CANONICAL_GROUPS for u in group]


def get_compatible_options(current_unit: str) -> list:
    """
    Returns available unit options with dimensionally compatible units prioritized first.

    Units dimensionally compatible with `current_unit` are listed first, followed
    by all other supported units to allow cross-dimensional corrections (e.g.
    a tacho recorded as volts, an unassigned accelerometer).
    For unknown or unassigned units, all supported units are returned.
    """
    cleaned_input = str(current_unit).strip().lower() if current_unit else ""
    canonical_input = _UNV_UNIT_MAPPING.get(cleaned_input, current_unit)

    compatible_group = []
    for group in _SW_CANONICAL_GROUPS:
        if canonical_input in group:
            compatible_group = list(group)
            break

    if not compatible_group:
        return list(_ALL_SUPPORTED_UNITS)

    return compatible_group + [u for u in _ALL_SUPPORTED_UNITS if u not in compatible_group]


_ACC_TOKENS = frozenset({"acc", "accelerometer"})
_TACHO_TOKENS = frozenset({"tacho", "tachometer"})
_MIC_TOKENS = frozenset({"mic", "microphone", "sound"})
_VOLTAGE_TOKENS = frozenset({"trigger"})

_AMBIGUOUS_UNITS = frozenset({"", "v", "mv", "volt", "millivolt", "dimensionless", "none"})


def _resolve_channel_tokens(name: str) -> set[str]:
    """Splits channel name into lowercase alphanumeric words, handling CamelCase, underscores, digits."""
    if not name:
        return set()
    raw_tokens = re.findall(r"[A-Za-z]+|\d+", str(name))
    tokens: set[str] = set()
    for token in raw_tokens:
        camel_parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\b)", token)
        if camel_parts:
            for part in camel_parts:
                tokens.add(part.lower())
        else:
            tokens.add(token.lower())
    return tokens


def determine_channel_type(unit_str: str, channel_name: str) -> str:
    """
    Determines channel type from engineering unit and channel name.

    Unambiguous physical unit domains take precedence over name heuristics so
    that an accelerometer in 'g' or 'm/s2' is never misclassified based on name
    substrings (e.g. 'Seismic_Acc', 'Dynamic_Acc', 'Tacho_side_acc').

    When the unit is ambiguous (e.g. V, mV, dimensionless, unassigned), whole
    words and tokens in the channel name are inspected to detect sensor type.
    """
    cleaned_input = str(unit_str).strip().lower() if unit_str else ""
    canonical_unit = _UNV_UNIT_MAPPING.get(cleaned_input, unit_str)

    # 1. Unambiguous physical unit domain takes absolute precedence
    for group in _SW_CANONICAL_GROUPS:
        if "g" in group and canonical_unit in group:
            return "accelerometer"
        if "Pa" in group and canonical_unit in group:
            return "microphone"
        if "rpm" in group and canonical_unit in group:
            return "tacho"

    # 2. Ambiguous units (e.g. V, mV, dimensionless, unassigned): infer from channel name tokens
    if cleaned_input in _AMBIGUOUS_UNITS or canonical_unit in ("V", "mV"):
        tokens = _resolve_channel_tokens(channel_name)
        if tokens & _ACC_TOKENS:
            return "accelerometer"
        elif tokens & _TACHO_TOKENS:
            return "tacho"
        elif tokens & _MIC_TOKENS:
            return "microphone"
        elif tokens & _VOLTAGE_TOKENS:
            return "voltage"
        elif canonical_unit in ("V", "mV"):
            return "voltage"

    # 3. Fallback when name gives no clue or for non-NVH physical units (e.g. N, degC)
    return "general_dynamic"


# Reader bookkeeping prefixes that pollute a channel name for display. UNV
# channels arrive as "Time for Inverter_Cover:+X"; the graph/spectrogram dock
# titles and the legend all want the bare sensor name, and used to each carry
# their own copy of this list.
_CHANNEL_NAME_DISPLAY_PREFIXES = ("Time for ", "time for ", "Signal for ", "signal for ")


def strip_channel_name_prefix(raw_name: str) -> str:
    """Drop a reader's leading "Time for "/"Signal for " label from a channel name."""
    if not raw_name:
        return ""
    clean_name = str(raw_name).strip()
    for prefix in _CHANNEL_NAME_DISPLAY_PREFIXES:
        if clean_name.startswith(prefix):
            return clean_name[len(prefix):]
    return clean_name


def strip_amplitude_suffix(unit: str) -> str:
    """
    Peels off a pre-existing "(...)^2", "(...)^2/Hz", " RMS" or " PEAK" suffix,
    leaving the bare physical unit -- "g RMS" -> "g", "(Pa)^2/Hz" -> "Pa".

    Shared by format_spectral_unit/format_order_unit (so labelling an
    already-spectral unit again can't double the suffix, e.g. a source channel
    whose raw unit string from the file is itself "g RMS" for a calibrated RMS
    channel producing "g RMS RMS") and by convert_signal_to_global_unit's smart
    parser, which needs the same split to find the linear scale factor.

    Loops until a pass changes nothing, so a unit already doubled up by data
    computed before this fix (e.g. a persisted "g RMS RMS" session) heals on
    the next refresh instead of needing a restart.
    """
    while True:
        cu_upper = unit.upper()
        if unit.endswith(")^2/Hz") or unit.endswith(")²/Hz") or unit.endswith("^2/Hz"):
            part = unit.split(")^2/Hz")[0].split(")²/Hz")[0].split("^2/Hz")[0]
            stripped = part.rstrip(")").lstrip("(")
        elif unit.endswith(")^2") or unit.endswith(")²"):
            part = unit.split(")^2")[0].split(")²")[0]
            stripped = part.rstrip(")").lstrip("(")
        elif unit in ("g^2", "g²"):
            stripped = "g"
        elif " RMS" in cu_upper:
            stripped = unit[:cu_upper.rfind(" RMS")].strip()
        elif " PEAK" in cu_upper:
            stripped = unit[:cu_upper.rfind(" PEAK")].strip()
        else:
            return unit
        if stripped == unit:
            return unit
        unit = stripped


def format_spectral_unit(base_unit: str, spectrum_format: str, amplitude_mode: str) -> str:
    """
    The single rule for labelling a 1D spectrum block, so it cannot be written
    three different ways in three call sites again.

    linear -> "g RMS" (or PEAK); power/canonical -> "(g)^2"; psd -> "(g)^2/Hz".
    """
    base_unit = strip_amplitude_suffix(base_unit)
    if spectrum_format == "psd":
        return f"({base_unit})^2/Hz"
    if spectrum_format in ("power", "canonical"):
        return f"({base_unit})^2"
    return f"{base_unit} {amplitude_mode.upper()}"


def is_squared_format(spectrum_format) -> bool:
    """The single rule for "this spectrum format is a squared quantity" (needs 10*log10, not 20*log10).

    ``canonical`` is deliberately not squared here: callers ask it about the
    *requested display* format, which is never ``canonical``; unit labels
    (``format_order_unit``) add it on top because a canonical block is g^2.
    """
    return spectrum_format in ("power", "psd")


def format_order_unit(base_unit: str, spectrum_format: str, amplitude_mode: str = "rms") -> str:
    """The single rule for labelling an order cut block."""
    base_unit = strip_amplitude_suffix(base_unit)
    if is_squared_format(spectrum_format) or spectrum_format == "canonical":
        return f"({base_unit})^2"
    return f"{base_unit} {amplitude_mode.upper()}"


def convert_signal_to_global_unit(y_data, current_unit, channel_type, preferences=None):
    """
    --- THE CENTRALIZED MATRICES CONVERSION ENGINE (SMART SCALING) ---
    Parses complex spectral string formats instantly post-FFT.
    Calculates the root physical linear scalar via Pint, squares it if necessary (Power/PSD),
    and applies lightning-fast vectorized conversion without re-triggering heavy DSP pipelines.
    """
    if y_data is not None and hasattr(y_data, "__len__") and len(y_data) == 0:
        return y_data, current_unit

    preferences = preferences or UnitPreferences()

    field_map = {
        "accelerometer": "acceleration",
        "microphone": "pressure",
        "voltage": "voltage",
        "tacho": "speed",
    }

    field_name = field_map.get(channel_type)
    if not field_name:
        base_probe = strip_amplitude_suffix(current_unit)
        deduced_type = determine_channel_type(base_probe, "")
        field_name = field_map.get(deduced_type)

    if not field_name:
        return y_data, current_unit

    target_global_unit = getattr(preferences, field_name)
    if not target_global_unit:
        return y_data, current_unit

    # 1. SMART PARSER: Extract mathematical properties and pure physical base unit
    spec_format = "time"
    amp_mode = ""

    cu_upper = current_unit.upper()
    if current_unit.endswith(")^2/Hz") or current_unit.endswith(")²/Hz") or current_unit.endswith("^2/Hz"):
        spec_format = "psd"
    elif current_unit.endswith(")^2") or current_unit.endswith(")²") or current_unit in ("g^2", "g²"):
        spec_format = "power"
    elif " RMS" in cu_upper:
        spec_format = "linear"
        amp_mode = "RMS"
    elif " PEAK" in cu_upper:
        spec_format = "linear"
        amp_mode = "PEAK"

    base_unit = strip_amplitude_suffix(current_unit)

    if base_unit == target_global_unit:
        return y_data, current_unit

    # 2. Extract linear scale conversion factor utilizing the active Pint engine
    sanitized_base = sanitize_unit_string(base_unit)
    sanitized_target = sanitize_unit_string(target_global_unit)

    if sanitized_base == sanitized_target:
        return y_data, current_unit

    try:
        linear_factor = _resolve_linear_factor(sanitized_base, sanitized_target)
    except Exception as e:
        # Fallback to safe return if Pint fails to cross dimensions natively
        logger.warning("Spectral scale conversion failed from [%s] to [%s]: %s", sanitized_base, sanitized_target, e)
        return y_data, current_unit

    # 3. Apply mathematically rigorous domain squaring if we are inside Power or PSD modes
    if spec_format in ["psd", "power"]:
        final_scalar = linear_factor ** 2
    else:
        final_scalar = linear_factor

    # Instantaneous scalar multiplication (Zero FFT recalculation overhead)
    converted_y = y_data * final_scalar if y_data is not None else None

    # 4. Synthesize the clean Testlab-style canonical string via the same rule
    # the DSP path uses. "time" has no spectral suffix, so it stays bare.
    if spec_format in ("psd", "power", "linear"):
        final_unit_str = format_spectral_unit(target_global_unit, spec_format, amp_mode)
    else:
        final_unit_str = target_global_unit

    return converted_y, final_unit_str
