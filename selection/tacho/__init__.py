"""
Tacho rule for the selection floor.

Selection floor: which subset of curves or measurements is relevant? Tacho
picks the one channel a run's RPM tracking reads (the first Tacho-type channel)
and answers whether an RPM-tracked analysis can run at all, so Order Tracking,
Overall Level, the spectrogram and the drop planners share one rule.

What does not belong here: reading the channel (io_modules/), the wording of
the refusal shown to the user (gui/), or Qt.
"""

from ._tacho import find_tacho_channel, tacho_missing

__all__ = ["find_tacho_channel", "tacho_missing"]
