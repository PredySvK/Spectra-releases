# =====================================================================
# FILE: view_models/parameter_sets/_parameter_sets.py
# =====================================================================
"""
Formatting helpers for Parameter Set presentation in the UI.

Parameter Set grouping and signatures live in selection.parameter_sets (#163).
"""
from core.block_kinds import KIND_OVERALL_LEVEL, PARAM_F_STOP
from core.tacho_cleaning import TACHO_CLEANING_PARAMS, is_tacho_cleaned, resolve_tacho_cleaning
from selection.parameter_sets import parameter_signature


def format_parameter_set_details(params: dict, kind: str) -> str:
    """
    One line per setting that distinguishes this Parameter Set, for the
    panel's detail view -- the same keys the signature is built from, so what
    the user reads is exactly what the grouping was decided by.

    An RPM Tracked result always shows its Tacho cleaning; a recipe without a
    value was computed with the default. Those lines are only
    shown -- the signature, and so the grouping, leaves a default out. The
    threshold of a switched-off Hampel filter shaped nothing and is not shown
   .
    """
    def shown(key, value):
        # f_stop=None is Full Bandwidth, an intent -- "None" reads as a setting that is missing.
        if kind == KIND_OVERALL_LEVEL and key == PARAM_F_STOP and value is None:
            return "Full Bandwidth"
        if key in TACHO_CLEANING_PARAMS:
            return ("on" if value else "off") if isinstance(value, bool) else f"{float(value):g}"
        return value

    pairs = dict(parameter_signature(kind, params)[1:])
    if is_tacho_cleaned(kind, params):
        pairs.update(resolve_tacho_cleaning(params).shaping_params)
    return "\n".join(f"{key}: {shown(key, pairs[key])}" for key in sorted(pairs))

