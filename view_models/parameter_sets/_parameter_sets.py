# =====================================================================
# FILE: view_models/parameter_sets/_parameter_sets.py
# =====================================================================
"""
Formatting helpers for Parameter Set presentation in the UI.

Parameter Set grouping and signatures live in selection.parameter_sets (#163).
"""
from selection.parameter_sets import shape_signature


def format_parameter_set_details(params: dict, kind: str = "") -> str:
    """
    One line per setting that distinguishes this Parameter Set, for the
    panel's detail view -- the same keys the signature is built from, so what
    the user reads is exactly what the grouping was decided by. `kind` defaults
    to order cuts for callers that predate mixed-kind result sets.
    """
    from core.block_kinds import KIND_ORDER_CUT, KIND_OVERALL_LEVEL, PARAM_F_STOP
    kind = kind or KIND_ORDER_CUT

    def shown(key, value):
        # f_stop=None is Full Bandwidth, an intent -- "None" reads as a setting that is missing.
        if kind == KIND_OVERALL_LEVEL and key == PARAM_F_STOP and value is None:
            return "Full Bandwidth"
        return value

    return "\n".join(
        f"{key}: {shown(key, value)}" for key, value in shape_signature(kind, params)
    )
