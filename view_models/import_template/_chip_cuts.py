"""
Step 3 of the import wizard (#1033): a chip's own cuts -- what "Split a
chip…" offers for a click between two characters or a double click on a word,
what the cuts make of each sample's value, and the cuts applied to the text
sources.

A cut is offered only when it fits the chip's value in every sample and splits
it into the same number of pieces; one that does not is offered greyed out with
the reason. The pieces are ordinary chips (core.import_template.ChipCuts);
pieces are not cut again, so the editor always works on the delimiter chip.

Pure: plain values in, plain values out.
"""

from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

from core.import_template import (
    CUT_AFTER_CHARACTERS, CUT_AFTER_TEXT, CUT_BEFORE_END, CUT_LETTERS_DIGITS, CUT_OUT, ChipCut, ChipCuts, TextSource,
)
from io_modules.import_template import build_cut_spans, build_text_chips

SourceKey = Tuple[str, int]
SourceCuts = Tuple[Tuple[SourceKey, ChipCuts], ...]


@dataclass(frozen=True)
class CutOffer:
    """One cut the editor offers, how it reads, and why it does not fit every sample (blank when it does)."""

    cut: ChipCut
    label: str
    problem: str = ""

    @property
    def is_fitting(self) -> bool:
        return not self.problem


def resolve_cut_pieces(value: str, cuts: Sequence[ChipCut]) -> Tuple[Tuple[str, ...], str]:
    """The pieces `cuts` make of one value, and why a cut does not fit it (blank when all do; then no pieces)."""
    spans, problem = build_cut_spans(value, cuts)
    if problem:
        return (), f"'{value}' {problem}"
    return tuple(value[start:end] for start, end in spans), ""


def _fit_problem(values: Sequence[str], cut: ChipCut) -> str:
    counts = set()
    for value in values:
        pieces, problem = resolve_cut_pieces(value, (cut,))
        if problem:
            return problem
        counts.add(len(pieces))
    return "it makes a different number of pieces in the samples" if len(counts) > 1 else ""


def _offer(values: Sequence[str], cut: ChipCut, label: str) -> CutOffer:
    return CutOffer(cut, label, _fit_problem(values, cut))


def build_cut_offers(values: Sequence[str], at: int) -> Tuple[CutOffer, ...]:
    """
    The cuts a click between the characters `at - 1` and `at` of the first
    value offers, the first fitting one being the default: between letters and
    numbers, after the text before the click, after `at` characters, `at` from
    the end. Empty at the ends of the value.
    """
    if not values or not 0 < at < len(values[0]):
        return ()
    first = values[0]
    offers: List[CutOffer] = []
    if (not first[at - 1].isspace() and not first[at].isspace()) and first[at - 1].isdigit() != first[at].isdigit():
        offers.append(_offer(values, ChipCut(CUT_LETTERS_DIGITS), "between letters and numbers"))
    offers.append(_offer(values, ChipCut(CUT_AFTER_TEXT, text=first[:at]), f"after the text '{first[:at]}'"))
    offers.append(_offer(values, ChipCut(CUT_AFTER_CHARACTERS, count=at), f"after {at} characters"))
    offers.append(_offer(values, ChipCut(CUT_BEFORE_END, count=len(first) - at),
                         f"{len(first) - at} characters before the end"))
    return tuple(offers)


def build_word_cut_offer(values: Sequence[str], start: int, end: int) -> Optional[CutOffer]:
    """The cut a double click on the word `start`:`end` of the first value offers: cut that text out."""
    if not values or not 0 <= start < end <= len(values[0]):
        return None
    word = values[0][start:end]
    if not word.strip():
        return None
    return _offer(values, ChipCut(CUT_OUT, text=word), f"cut out '{word}'")


def resolve_default_offer(offers: Sequence[CutOffer]) -> Optional[CutOffer]:
    """The cut a click makes without asking: the first one that fits every sample."""
    return next((offer for offer in offers if offer.is_fitting), None)


def resolve_cut_label(cut: ChipCut) -> str:
    """How a cut reads in the editor's list."""
    return {CUT_LETTERS_DIGITS: "between letters and numbers",
            CUT_AFTER_TEXT: f"after the text '{cut.text}'",
            CUT_AFTER_CHARACTERS: f"after {cut.count} characters",
            CUT_BEFORE_END: f"{cut.count} characters before the end",
            CUT_OUT: f"cut out '{cut.text}'"}[cut.kind]


def resolve_chip_values(sources: Sequence[TextSource], texts: Sequence[Optional[str]], key: SourceKey,
                        chip: int) -> Tuple[str, ...]:
    """
    The value of delimiter chip `chip` of a source in each text (the texts of the channels), before its own
    cuts and without repeats, in order; a text without that chip adds none.
    """
    source = next((found for found in sources if found.key == key), None)
    if source is None:
        return ()
    whole = replace(source, cut_chips=())
    values: Dict[str, None] = {}
    for text in texts:
        if text is None:
            continue
        found = build_text_chips(text, whole).chips
        if chip < len(found):
            values[found[chip].text] = None
    return tuple(values)


def apply_chip_cuts(sources: Sequence[TextSource], cuts: SourceCuts) -> Tuple[TextSource, ...]:
    """The sources with their chips' own cuts, in chip order."""
    result = []
    for source in sources:
        own = tuple(sorted((found for key, found in cuts if key == source.key), key=lambda found: found.chip))
        result.append(replace(source, cut_chips=own) if own else source)
    return tuple(result)
