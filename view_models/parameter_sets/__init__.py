"""
view_models.parameter_sets -- Presentation formatting for Parameter Sets.

Architecture:
- View-model floor (Floor 3): How should Parameter Set details be formatted for display, without Qt?
- Parameter Set detail formatting: format_parameter_set_details.

What does NOT belong here: Qt widgets or drawing calls (gui/), deciding what
runs (orchestration/), what project is currently open (session/), which
curves or parameter sets are grouped/selected (selection/), or signal processing computation (signal_processing/).
"""

from ._parameter_sets import format_parameter_set_details

__all__ = [
    "format_parameter_set_details",
]
