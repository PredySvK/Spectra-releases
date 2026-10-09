# gui/settings/graph_colours.py
"""
Qt-flavoured pen property lookup for PyQtGraph.
Wraps the Qt-free carousel_pen_spec from view_models.plot.
All internal documentation strings and variable labels are standardly written in English.
"""

from view_models.plot import carousel_pen_spec


def get_carousel_pen_properties(index_counter: int) -> tuple:
    """
    (hex_color_string, Qt.PenStyle) for overlay curve N -- the Qt-flavoured
    wrapper around carousel_pen_spec for callers drawing straight into pyqtgraph.
    """
    from PySide6.QtCore import Qt

    style_map = {
        "solid": Qt.PenStyle.SolidLine,
        "dash": Qt.PenStyle.DashLine,
        "dot": Qt.PenStyle.DotLine,
        "dashdot": Qt.PenStyle.DashDotLine,
    }
    selected_hex_color, style_name = carousel_pen_spec(index_counter)
    return selected_hex_color, style_map[style_name]
