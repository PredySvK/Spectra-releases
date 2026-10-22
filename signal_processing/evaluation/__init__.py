# =====================================================================
# FILE: signal_processing/evaluation/__init__.py
# =====================================================================
"""
Evaluation: pulling Single values out of a set of curves.

No Qt, no app_context (tests/test_architecture.py enforces it) -- an
Evaluation is a function of blocks and identities, so it runs the same way
from a dock adapter today as from a future workflow runner.
"""

from signal_processing.evaluation.dominant_orders_eval import (
    DEFAULT_MIN_ORDER_DISTANCE, DEFAULT_ORDER_MAX, DEFAULT_ORDER_MIN, DEFAULT_ORDER_RESOLUTION,
    DEFAULT_N as DEFAULT_DOMINANT_N,
)
from signal_processing.evaluation.registry import EvaluationSpec, EVALUATIONS
from signal_processing.evaluation.runner import evaluate
from signal_processing.evaluation.topn_eval import DEFAULT_MIN_PROMINENCE_DB, DEFAULT_N
from signal_processing.evaluation.typed_orders_eval import DEFAULT_ORDER_WIDTH

__all__ = [
    "EvaluationSpec", "EVALUATIONS", "evaluate",
    "DEFAULT_N", "DEFAULT_MIN_PROMINENCE_DB", "DEFAULT_DOMINANT_N", "DEFAULT_ORDER_MIN", "DEFAULT_ORDER_MAX",
    "DEFAULT_MIN_ORDER_DISTANCE", "DEFAULT_ORDER_RESOLUTION", "DEFAULT_ORDER_WIDTH",
]
