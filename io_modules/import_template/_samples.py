"""
The import wizard's samples on disk: every sample file read whole, and the
further files of the first sample's kind in its folder. Both grow with the
data, so they run on a worker.
"""

import os
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from io_modules.import_template._table import Workbook, read_workbook
from io_modules.import_template._text_table import TextFormat


@dataclass(frozen=True)
class SampleRead:
    """One sample file read: its workbook, or why it cannot be read (`workbook` is None)."""

    path: str
    workbook: Optional[Workbook]
    problem: str = ""


def read_samples(paths: Sequence[str], text_format: TextFormat) -> Tuple[SampleRead, ...]:
    """Every sample, each read whole with `text_format`; a file that cannot be read says why and the others are read."""
    reads = []
    for path in paths:
        try:
            reads.append(SampleRead(path, read_workbook(path, None, None, text_format)))
        except Exception as error:      # any broken file: openpyxl, zip, decoding, permissions
            reads.append(SampleRead(path, None, str(error) or type(error).__name__))
    return tuple(reads)


def read_more_samples(path: str) -> Tuple[str, ...]:
    """The other files in the folder of `path` with its suffix (any case), sorted by name."""
    folder, suffix = os.path.dirname(os.path.abspath(path)), os.path.splitext(path)[1].lower()
    own = os.path.normcase(os.path.abspath(path))
    try:
        names = os.listdir(folder)
    except OSError:
        return ()
    found = [os.path.join(folder, name) for name in names if os.path.splitext(name)[1].lower() == suffix]
    return tuple(sorted((other for other in found
                         if os.path.normcase(other) != own and os.path.isfile(other)), key=str.lower))
