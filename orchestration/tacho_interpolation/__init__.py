"""
Tacho interpolation log line for the orchestration floor.

Orchestration floor: in what order things run and what is said around them. This
component composes the one system-log line a computation says before it carries
a file's tacho onto another rate, so a batch and a live compute word it alike.
Whether a tacho has to be interpolated is the rule in selection/tacho; one line
is said per file and target rate, and the caller decides when (never on a cache hit).

What does not belong here: the rule itself (selection/), the interpolation
(signal_processing/), Qt.
"""

from ._line import build_tacho_interpolation_line, is_tacho_interpolation_line

__all__ = ["build_tacho_interpolation_line", "is_tacho_interpolation_line"]
