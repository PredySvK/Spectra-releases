"""
Trace filter orchestration: filter card persistence and mask application
workflows (what runs, in what order, when filters are applied or edited).

Pure functions (no Qt, no AppContext) coordinating filter card persistence
and mask planning.

What does not belong here: Qt widgets or prompt dialogs (gui/), facet
calculations and gating rules (selection/), or active project session
storage implementation (session/) -- orchestration coordinates them, it does
not implement them.
"""

from orchestration.trace_filter._filter_card import save_filter_card
from orchestration.trace_filter._identity_context import (
    IdentityContext,
    build_identity_context,
)
from orchestration.trace_filter._mask_plan import (
    MaskApplicationPlan,
    plan_mask_application,
)

__all__ = [
    "IdentityContext",
    "MaskApplicationPlan",
    "build_identity_context",
    "plan_mask_application",
    "save_filter_card",
]
