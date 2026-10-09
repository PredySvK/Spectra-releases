"""
Qt-free color palette and carousel styling configuration.

Provides the master high-luminescence palette and line style cycling for
graph overlays without importing Qt.
"""

from typing import Set, Tuple

# MASTER NVH POWERTRAIN HIGH-LUMINESCENCE PALETTE
# 18 distinct high-brightness colors carefully picked for clean contrast on dark grids
NVH_COLOR_PALETTE = [
    '#ff3333',  # Bright Red
    '#3399ff',  # Electric Blue
    '#00ff66',  # Lime Green
    '#cc33ff',  # Neon Purple
    '#ff6600',  # Industrial Orange
    '#00ffff',  # Cyan
    '#ffffff',  # Pure White
    '#ff66cc',  # Soft Pink
    '#ffff33',  # Neon Yellow-Green
    '#99ff33',  # Bright Chartreuse
    '#33ffcc',  # Turquoise
    '#3333ff',  # Deep Royal Blue
    '#ff3399',  # Hot Magenta
    '#ffa07a',  # Light Salmon
    '#98fb98',  # Pale Green
    '#87cefa',  # Light Sky Blue
    '#e6e6fa',  # Lavender
    '#f4a460',  # Sandy Brown
]

# Dash pattern per full rollover of the color palette. Plain strings, not
# Qt.PenStyle, so the plot model builder can pick a pen without importing Qt;
# the renderer maps the name back when it draws.
_CAROUSEL_STYLES = ("solid", "dash", "dot", "dashdot")


def carousel_pen_spec(index_counter: int) -> Tuple[str, str]:
    """
    Qt-free (hex_color, style_name) for overlay curve N.

    Cycles the 18-color palette; each full rollover shifts the dash pattern
    (solid -> dash -> dot -> dashdot, then held).
    """
    palette_length = len(NVH_COLOR_PALETTE)
    cycle_count = index_counter // palette_length
    selected_hex_color = NVH_COLOR_PALETTE[index_counter % palette_length]
    style_name = _CAROUSEL_STYLES[min(cycle_count, len(_CAROUSEL_STYLES) - 1)]
    return selected_hex_color, style_name


class HeldPens:
    """The pens of the held curves, kept so a caller adding curves one by one
    picks the next one without rescanning every held curve (#442)."""

    def __init__(self) -> None:
        self._colors: Set[str] = set()
        self._pens: Set[Tuple[str, str]] = set()

    def hold(self, color: str, style: str) -> None:
        if color:
            normalized = color.strip().lower()
            self._colors.add(normalized)
            self._pens.add((normalized, style))

    def free_index(self) -> int:
        """The lowest pen carousel index not in use by any held curve.

        Picks the smallest index whose color is not held. When all colors in
        the palette are in use, picks the smallest index whose (color, style)
        combination is unused, so curves stay visually distinct even after
        earlier overlays are removed or hidden by a trace filter.
        """
        for index in range(len(NVH_COLOR_PALETTE)):
            color, _ = carousel_pen_spec(index)
            if color.lower() not in self._colors:
                return index

        max_distinct_combinations = len(NVH_COLOR_PALETTE) * len(_CAROUSEL_STYLES)
        for index in range(len(NVH_COLOR_PALETTE), max_distinct_combinations):
            color, style = carousel_pen_spec(index)
            if (color.lower(), style) not in self._pens:
                return index

        return 0
