# =====================================================================
# FILE: signal_processing/evaluation/__init__.py
# =====================================================================
"""
Evaluation (ADR §1.64): pulling Single values out of a set of curves.

No Qt, no app_context (tests/test_architecture.py enforces it) -- an
Evaluation is a function of blocks and identities, so it runs the same way
from a dock adapter today as from a future workflow runner.
"""

from signal_processing.evaluation.registry import EvaluationSpec, EVALUATIONS
from signal_processing.evaluation.runner import evaluate

__all__ = ["EvaluationSpec", "EVALUATIONS", "evaluate"]
