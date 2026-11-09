"""The count line a Selection is shown with."""
from typing import Optional

from selection.measurement_selection import SelectionResolution


def describe_counts(resolution: Optional[SelectionResolution]) -> str:
    """The "N measurements / M channels" line the editor and the tab share."""
    if resolution is None:
        return "Counting…"
    return (f"{resolution.measurement_count} measurement(s) / "
            f"{resolution.channel_count} channel(s)")
