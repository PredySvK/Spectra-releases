"""
Which Source amplitude questions an ingest has to ask before it reads anything.

The program cannot tell whether an Imported result's amplitude is RMS or Peak,
so an Add asks once per reader that has files in the plan -- not per file -- and
the answer is written to every one of those files' source entries. This module
decides the questions; showing them is the shell's business (gui/).
"""

from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional, Tuple

from io_modules.measurement_files import resolve_default_source_amplitude

# How the user knows each reader: the Pairing tab's words, not class names.
_READER_LABELS = {
    "AccReaderMasta": "MASTA",
    "AccReaderProcessedMeasurement": "Processed measurement",
    "AccReaderAnsys": "ANSYS",
}


@dataclass(frozen=True)
class SourceAmplitudeQuestion:
    """One question: what the amplitude means in `file_count` files of one reader."""

    reader: str
    label: str
    default: str
    file_count: int


# Answers the shell gives back: reader name -> "rms" | "peak"; None is Cancel.
SourceAmplitudeAsker = Callable[[Tuple[SourceAmplitudeQuestion, ...]], Optional[Mapping[str, str]]]


def plan_source_amplitude_questions(imported_files: Mapping[str, Tuple[str, ...]]
                                    ) -> Tuple[SourceAmplitudeQuestion, ...]:
    """One question for each reader that has files, in a stable (label) order."""
    questions = [
        SourceAmplitudeQuestion(
            reader=reader, label=_READER_LABELS.get(reader, reader),
            default=resolve_default_source_amplitude(reader), file_count=len(paths))
        for reader, paths in imported_files.items() if paths
    ]
    return tuple(sorted(questions, key=lambda question: question.label))


def resolve_file_amplitudes(imported_files: Mapping[str, Tuple[str, ...]],
                            answers: Mapping[str, str]) -> Dict[str, str]:
    """The answer of each reader spread over its files: file path -> "rms" | "peak"."""
    return {path: answers[reader]
            for reader, paths in imported_files.items() if reader in answers
            for path in paths}
