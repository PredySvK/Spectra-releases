"""
The colours of a graph's plot area, from `core.theme` Graph theme tokens.

Every pyqtgraph colour of a dock (background, axes, grid, legend text, Cursor,
Band RMS Cursor, Highlight's dimming target) is read from `GRAPH_TOKENS`.
"""

import pyqtgraph as pg

from gui.appearance import GRAPH_TOKENS


def style_plot_area(plot_widget: pg.PlotWidget) -> None:
    """Sets the background explicitly and the axes (hence grid and legend) from tokens."""
    plot_widget.setBackground(GRAPH_TOKENS.background)
    for name in ("left", "bottom", "right", "top"):
        axis = plot_widget.getAxis(name)
        axis.setPen(GRAPH_TOKENS.axis)
        axis.setTextPen(GRAPH_TOKENS.axis)
