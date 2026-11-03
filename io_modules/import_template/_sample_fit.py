"""
The wizard's check of further sample files: does the template fit each of them.
A file that does not is listed with the reason, as the misfit report names it.
"""

from dataclasses import dataclass
from typing import Sequence, Tuple

from core.import_template import ImportTemplate
from io_modules.import_template._reader import read_template_misfit_reason


@dataclass(frozen=True)
class SampleFit:
    """A further sample file and why the template does not fit it (blank: it fits)."""

    path: str
    problem: str

    @property
    def fits(self) -> bool:
        return not self.problem


def read_sample_fits(paths: Sequence[str], template: ImportTemplate) -> Tuple[SampleFit, ...]:
    """Whether the template fits each file, read like the scan does. Reads the head of every file: run it on a worker."""
    fits = []
    for path in paths:
        try:
            fits.append(SampleFit(path, read_template_misfit_reason(path, template)))
        except Exception as error:      # one unreadable file must not hide the others' result
            fits.append(SampleFit(path, f"cannot be checked ({error})"))
    return tuple(fits)
