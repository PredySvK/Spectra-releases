"""
Measurement selection -- how a Selection's count is shown, without Qt.

``describe_counts(resolution)`` is the "N measurement(s) / M channel(s)" line
the Selection editor and the Explorer's Selections tab share; ``None`` (a count
still running) reads "Counting…".
"""

from ._count_line import describe_counts

__all__ = [
    "describe_counts",
]
