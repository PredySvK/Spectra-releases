"""Resolve companion drop requests using the project's indexed sources.

- run_companion_curves: background preparation of the partners' drop descriptors.
- CompanionCurvesState: which order curves a dock already looked at and which
  partners it added itself.
"""

from ._companion_curves import run_companion_curves
from ._companion_curves_state import CompanionCurvesState

__all__ = ["CompanionCurvesState", "run_companion_curves"]
