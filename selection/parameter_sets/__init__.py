"""
Parameter Set grouping and shape signatures for the selection floor.

Selection floor: which subset of curves or measurements is relevant?
Parameter Sets partition result sets by their computation settings
(shape signature), assigning stable project-wide numbering so switching
views or primary sets never renumbers existing traces.

What does not belong here: presentation formatting of details (view_models/
or io_modules/), storage/cache layout logic (io_modules/result_cache/),
or Qt widgets (gui/).
"""

from ._parameter_sets import (
    ORDER_ABS_TOL,
    ORDER_REL_TOL,
    ParameterSet,
    Signature,
    build_parameter_sets,
    default_primary_index,
    filter_result_sets_by_parameter_set,
    orders_equal,
    parameter_set_for_signature,
    parameter_sets_from_traces,
    parameter_signature,
    result_set_signature,
    shape_signature,
    signature_matches_any,
    signature_value_matches,
    signatures_match,
)

__all__ = [
    "ORDER_ABS_TOL",
    "ORDER_REL_TOL",
    "ParameterSet",
    "Signature",
    "build_parameter_sets",
    "default_primary_index",
    "filter_result_sets_by_parameter_set",
    "orders_equal",
    "parameter_set_for_signature",
    "parameter_sets_from_traces",
    "parameter_signature",
    "result_set_signature",
    "shape_signature",
    "signature_matches_any",
    "signature_value_matches",
    "signatures_match",
]
