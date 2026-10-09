"""The QApplication of a Full Benchmark: paints are timed as Benchmark steps."""

import time

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget
from pyqtgraph.widgets.GraphicsView import GraphicsView

from core.benchmark import benchmark_step


class BenchmarkApplication(QApplication):
    """
    Times `paint_graph` (a graph view or its OpenGL viewport painting) and
    `repaint_window` (a top-level window's UpdateRequest: repaint, compose and
    swap -- what reaches the monitor). The steps nest: a window repaint
    contains the graph paints under it. `last_paint` is when the latest of
    either ended, so the Benchmark can tell when the screen went quiet.
    """

    def __init__(self, argv):
        super().__init__(argv)
        self.last_paint = time.perf_counter()

    def notify(self, receiver, event):
        kind = event.type()
        if kind == QEvent.Type.Paint and (isinstance(receiver, GraphicsView)
                                          or isinstance(receiver.parent(), GraphicsView)):
            step = "paint_graph"
        elif kind == QEvent.Type.UpdateRequest and isinstance(receiver, QWidget) and receiver.isWindow():
            step = "repaint_window"
        else:
            return super().notify(receiver, event)
        try:
            with benchmark_step(step):
                return super().notify(receiver, event)
        finally:
            self.last_paint = time.perf_counter()
