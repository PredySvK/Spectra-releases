"""
Which Import template reads which file of an Add or a Refresh, and which files
fit none of the templates they name.

A folder can hold several Import templates, each for the files whose names fit
its pattern. A file whose name fits a template but whose content does not is a
**misfit**: it stays out of the pool and is listed in the report of the run
with the reason -- an outcome, never an error that stops the scan and never a
file dropped silently. A file that fits two templates is a question for the
user; this module decides the questions, showing them is the shell's business.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from core.import_template import ImportTemplate
from io_modules.import_template import resolve_template_name_fit, read_template_misfit_reason
from io_modules.measurement_files import is_measurement_file


@dataclass(frozen=True)
class Misfit:
    """
    A file that does not fit the template(s) its name belongs to, and why.
    `template` names them for the report; `templates` are their names.
    """

    path: str
    template: str
    reason: str
    templates: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateQuestion:
    """One question: which of `candidates` reads each of `file_count` files that fit all of them."""

    candidates: Tuple[str, ...]
    file_count: int


# Answers the shell gives back: candidates -> the chosen template name; None is Cancel.
ImportTemplateAsker = Callable[[Tuple[TemplateQuestion, ...]], Optional[Mapping[Tuple[str, ...], str]]]


@dataclass(frozen=True)
class TemplateAssignment:
    """
    What the templates make of a set of files: `assigned` (path -> template
    name), `ambiguous` (path -> the names of every template that fits it) and
    `misfits`.
    """

    assigned: Mapping[str, str]
    ambiguous: Mapping[str, Tuple[str, ...]]
    misfits: Tuple[Misfit, ...]


def plan_template_assignment(paths: Iterable[str], templates: Sequence[ImportTemplate]) -> TemplateAssignment:
    """
    Sorts `paths` by what `templates` make of them. Reads each candidate's
    header, so it runs on a worker.

    A file no template's name pattern names is left alone. One whose name fits
    but whose content fits no template is a misfit -- unless a built-in reader
    recognises it, in which case the suffix decides as before.
    """
    assigned: Dict[str, str] = {}
    ambiguous: Dict[str, Tuple[str, ...]] = {}
    misfits = []
    for path in paths:
        named = [template for template in templates if resolve_template_name_fit(path, template)]
        if not named:
            continue
        reasons = {template.name: read_template_misfit_reason(path, template) for template in named}
        fitting = tuple(name for name, reason in reasons.items() if not reason)
        if len(fitting) == 1:
            assigned[path] = fitting[0]
        elif fitting:
            ambiguous[path] = fitting
        elif not is_measurement_file(path):
            misfits.append(Misfit(
                path, ", ".join(reasons), "; ".join(f"{name}: {reason}" for name, reason in reasons.items()),
                tuple(reasons)))
    return TemplateAssignment(assigned, ambiguous, tuple(misfits))


def plan_template_questions(ambiguous: Mapping[str, Tuple[str, ...]]) -> Tuple[TemplateQuestion, ...]:
    """One question for each set of templates that fit the same files, in a stable order."""
    counts: Dict[Tuple[str, ...], int] = {}
    for candidates in ambiguous.values():
        counts[candidates] = counts.get(candidates, 0) + 1
    return tuple(TemplateQuestion(candidates, count) for candidates, count in sorted(counts.items()))


def resolve_template_answers(ambiguous: Mapping[str, Tuple[str, ...]],
                             answers: Mapping[Tuple[str, ...], str]) -> Dict[str, str]:
    """The answer of each question spread over its files: file path -> template name."""
    return {path: answers[candidates] for path, candidates in ambiguous.items()
            if answers.get(candidates) in candidates}


def resolve_unanswered_misfits(ambiguous: Mapping[str, Tuple[str, ...]],
                        answered: Mapping[str, str]) -> Tuple[Misfit, ...]:
    """The files nobody chose a template for, as misfits: they stay out of the pool."""
    return tuple(
        Misfit(path, ", ".join(candidates),
               f"fits several Import templates ({', '.join(candidates)}); choose one when adding the folder",
               tuple(candidates))
        for path, candidates in ambiguous.items() if path not in answered)
