# =====================================================================
# FILE: view_models/data_pool/_measurement_flag.py
# =====================================================================
"""
Measurement flags: the marks a Data Pool row carries.

A flag is derived from the run each time the tree is built and stored nowhere,
so no cache format depends on it. A new kind is a new MeasurementFlag type
listed in MEASUREMENT_FLAG_KINDS; the tree and the panel do not change.
"""

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Sequence, Tuple, Type

from selection.tacho import find_tacho_interpolation


@dataclass(frozen=True)
class MeasurementFlag:
    """One report about a measurement: its kind's glyph and the text behind it."""

    glyph: ClassVar[str]
    text: str

    @classmethod
    def build_from(cls, run: Any) -> Tuple["MeasurementFlag", ...]:
        """The reports of this kind about `run`; none when it does not apply."""
        raise NotImplementedError


@dataclass(frozen=True)
class PartiallyReadFlag(MeasurementFlag):
    """Part of the file could not be read; the channels shown are still usable."""

    glyph: ClassVar[str] = "◐"

    @classmethod
    def build_from(cls, run: Any) -> Tuple["PartiallyReadFlag", ...]:
        if not run.lost_parts:
            return ()
        lost = "\n".join(f"  {part.describe()}" for part in run.lost_parts)
        return (cls(text=f"Incomplete: part of this file could not be read.\n{lost}\n\n"
                         "The channels shown are complete and can be used."),)


@dataclass(frozen=True)
class TachoInterpolationFlag(MeasurementFlag):
    """The tacho has another rate than a time channel and is interpolated onto it."""

    glyph: ClassVar[str] = "ⓘ"

    @classmethod
    def build_from(cls, run: Any) -> Tuple["TachoInterpolationFlag", ...]:
        found = find_tacho_interpolation(run)
        if found is None:
            return ()
        rates = ", ".join(f"{rate:g} Hz" for rate in found.channel_rates)
        return (cls(text=f"Tacho {found.tacho_name} ({found.tacho_rate:g} Hz) is interpolated "
                         f"onto the channel rate ({rates})."),)


MEASUREMENT_FLAG_KINDS: Tuple[Type[MeasurementFlag], ...] = (PartiallyReadFlag, TachoInterpolationFlag)


def build_measurement_flags(run: Any, kinds: Sequence[Type[MeasurementFlag]]) -> Tuple[MeasurementFlag, ...]:
    """Every report of `kinds` about `run`, in the order of the kinds."""
    return tuple(flag for kind in kinds for flag in kind.build_from(run))


def _by_glyph(flags: Sequence[MeasurementFlag]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for flag in flags:
        groups.setdefault(flag.glyph, []).append(flag.text)
    return groups


def build_flag_labels(flags: Sequence[MeasurementFlag]) -> str:
    """The row's glyphs side by side; a glyph with two or more reports gets their count."""
    return " ".join(glyph if len(texts) == 1 else f"{glyph}{len(texts)}"
                    for glyph, texts in _by_glyph(flags).items())


def build_flag_glyphs(flags: Sequence[MeasurementFlag]) -> str:
    """The row's glyphs without counts: what a search may hit, as a count is no word."""
    return " ".join(_by_glyph(flags))


def build_flag_tooltip(flags: Sequence[MeasurementFlag]) -> str:
    """The reports grouped by glyph; a lone report needs no glyph to tell it apart."""
    if len(flags) == 1:
        return flags[0].text
    return "\n\n".join(
        "\n".join(f"{glyph} {text}" for text in texts)
        for glyph, texts in _by_glyph(flags).items()
    )
