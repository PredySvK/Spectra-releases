"""
view_models.trace_filter -- Presentation-side conversion from Trace to TraceIdentity.

Architecture:
- View-model floor (Floor 3): How should an already-drawn Trace be translated into
  the TraceIdentity a filter facet or evaluation needs, without Qt?
- Trace identity conversion: identity_for_trace, identity_for_stored_curve,
  resolve_stored_curves_already_held, trace_parameter_signature, KIND_BY_X_QUANTITY.

What does NOT belong here: Qt widgets or drawing calls (gui/), deciding what
runs (orchestration/), what project is currently open (session/), which
curves are filtered or grouped (selection/), or signal processing computation (signal_processing/).
"""

from ._trace_identity import (
    KIND_BY_X_QUANTITY,
    identity_for_stored_curve,
    identity_for_trace,
    resolve_stored_curves_already_held,
    trace_parameter_signature,
)

__all__ = [
    "KIND_BY_X_QUANTITY",
    "identity_for_stored_curve",
    "identity_for_trace",
    "resolve_stored_curves_already_held",
    "trace_parameter_signature",
]
