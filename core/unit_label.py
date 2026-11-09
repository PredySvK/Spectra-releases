# =====================================================================
# FILE: core/unit_label.py
# =====================================================================
"""
Unit label: the whole unit text a curve is shown with -- "g RMS", "(g)^2",
"(g)^2/Hz" -- a Display unit plus the Format and Amplitude it is shown in.

This module is the one place that builds a Unit label and the one place that
reads one back (#892). Nobody else matches "^2", " RMS" or "/Hz" suffixes.

A unit counts as squared only when this program wrote it in parentheses
("(Pa)^2") or when a whole known unit stands before "^2" / "²" ("Pa^2", "g²"),
as a file may spell it. "m/s²" and "mm/s²" are known units (acceleration), not
a squared "m/s". Any other text -- "dB", "N^2" -- is a plain unit and is left
exactly as it came.
"""

from dataclasses import dataclass

__all__ = [
    "UnitLabel",
    "build_unit_label",
    "resolve_unit_label",
    "resolve_unit_spelling",
]


@dataclass(frozen=True)
class UnitLabel:
    """A Unit label split into its parts.

    ``spectrum_format`` is "" for a plain unit, else "linear", "power" or
    "psd"; ``amplitude_mode`` is "RMS" or "PEAK" for "linear" and "" otherwise.
    """
    unit: str
    spectrum_format: str = ""
    amplitude_mode: str = ""


# The program's spelling of each unit a file may write differently. A key is
# lower case; a unit text is "known" when its lower-case form is a key.
_UNIT_SPELLINGS = {
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
    's': 's',
    'sec': 's',
    'second': 's',
}

_SQUARE_MARKS = ("^2", "²")
_PSD_SUFFIX = "/Hz"
_AMPLITUDE_MODES = ("RMS", "PEAK")


def resolve_unit_spelling(raw_unit: str) -> str:
    """The program's spelling of a unit ("m/s^2" -> "m/s2", "pascal" -> "Pa"), or the input unchanged."""
    cleaned = str(raw_unit).strip().lower() if raw_unit else ""
    return _UNIT_SPELLINGS.get(cleaned, raw_unit)


def _is_known_unit(text: str) -> bool:
    return text.strip().lower() in _UNIT_SPELLINGS


def _peel_square(text: str):
    """The unit under a "^2" / "²", or None when ``text`` is not a squared unit."""
    for mark in _SQUARE_MARKS:
        if not text.endswith(mark):
            continue
        inner = text[: -len(mark)].strip()
        if inner.startswith("(") and inner.endswith(")"):
            return inner[1:-1].strip()
        if _is_known_unit(inner):
            return inner
    return None


def _peel_once(text: str):
    """The outermost decoration of ``text`` as a UnitLabel, or None for a plain unit."""
    if _is_known_unit(text):
        return None
    if text.endswith(_PSD_SUFFIX):
        inner = _peel_square(text[: -len(_PSD_SUFFIX)].strip())
        if inner is not None:
            return UnitLabel(inner, "psd")
    inner = _peel_square(text)
    if inner is not None:
        return UnitLabel(inner, "power")
    upper = text.upper()
    for mode in _AMPLITUDE_MODES:
        if upper.endswith(" " + mode):
            return UnitLabel(text[: -len(mode) - 1].strip(), "linear", mode)
    return None


def resolve_unit_label(text: str) -> UnitLabel:
    """
    Splits a Unit label into its Display unit, Format and Amplitude.

    The outermost decoration decides Format and Amplitude. Any decoration under
    it is peeled as well, so a label doubled by data written before labels
    were read back ("g RMS RMS") reads as plain "g RMS".
    """
    text = (text or "").strip()
    outer = _peel_once(text)
    if outer is None:
        return UnitLabel(text)
    unit = outer.unit
    while (inner := _peel_once(unit)) is not None:
        unit = inner.unit
    return UnitLabel(unit, outer.spectrum_format, outer.amplitude_mode)


def build_unit_label(unit: str, spectrum_format: str, amplitude_mode: str) -> str:
    """
    The Unit label of a spectrum shown in ``spectrum_format`` x ``amplitude_mode``:
    linear -> "g RMS" (or PEAK); power and canonical -> "(g)^2"; psd -> "(g)^2/Hz".

    ``unit`` may already be a Unit label (a file channel whose unit reads
    "g RMS"); its Display unit is used, so the decoration is never doubled.
    """
    unit = resolve_unit_label(unit).unit
    if spectrum_format == "psd":
        return f"({unit})^2/Hz"
    if spectrum_format in ("power", "canonical"):
        return f"({unit})^2"
    return f"{unit} {amplitude_mode.upper()}"
