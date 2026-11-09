# =====================================================================
# FILE: gui/workspace/legend_gear.py
# =====================================================================
"""
The gear at the top-right corner of a graph's legend: it shows while the mouse is
over the legend and a click opens Legend Settings (plot §1.299).

The gear is a child widget of the graph view, not an item of its scene, so no
scene export of the plot ever draws it. It is a child of the view itself, not of
its viewport: a rendering mode switch replaces the viewport and deletes its
children (plot §1.300). The legend is found through the
scene's mouse moves, which also run while the legend is dragged, so the gear
follows a moved legend and a Highlight repaint of its rows changes nothing.

Runs synchronously on the GUI thread: it only moves one small widget.
"""

from typing import Any, Callable

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtWidgets import QToolButton

GEAR_SIZE_PX = 18


class LegendGear(QObject):
    """Hover gear over ``legend`` in ``plot_widget``; ``on_click`` opens the window."""

    def __init__(self, plot_widget: Any, legend: Any, on_click: Callable[[], None]) -> None:
        super().__init__(plot_widget)
        self._plot_widget = plot_widget
        self._legend = legend
        self.button = QToolButton(plot_widget)
        self.button.setObjectName("LegendGearButton")
        self.button.setText("⚙")
        self.button.setToolTip("Legend Settings…")
        self.button.setCursor(Qt.CursorShape.ArrowCursor)
        self.button.setFixedSize(GEAR_SIZE_PX, GEAR_SIZE_PX)
        self.button.setAutoRaise(True)
        self.button.hide()
        self.button.clicked.connect(on_click)
        self.button.installEventFilter(self)
        plot_widget.installEventFilter(self)
        plot_widget.scene().sigMouseMoved.connect(self._on_scene_mouse_moved)

    def _legend_rect(self) -> QRectF:
        return self._legend.sceneBoundingRect()

    def _legend_has_rows(self) -> bool:
        return bool(self._legend.items) and self._legend.isVisible()

    def _on_scene_mouse_moved(self, scene_pos: QPointF) -> None:
        if self._legend_has_rows() and self._legend_rect().contains(scene_pos):
            self._place_and_show()
        else:
            self._hide_unless_hovered()

    def _place_and_show(self) -> None:
        viewport = self._plot_widget.viewport()
        top_right = viewport.mapTo(self._plot_widget, self._plot_widget.mapFromScene(self._legend_rect().topRight()))
        x = max(0, top_right.x() - self.button.width())
        self.button.move(x, max(0, top_right.y()))
        self.button.show()
        self.button.raise_()

    def _hide_unless_hovered(self) -> None:
        # The gear sits over the legend, so the scene stops hearing the mouse once it is on the gear.
        if not self.button.underMouse():
            self.button.hide()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Leave:
            if watched is self.button:
                # Back onto the legend keeps it (scene moves follow); anywhere else hides it.
                pos = self._plot_widget.viewport().mapFromGlobal(self.button.cursor().pos())
                scene_pos = self._plot_widget.mapToScene(pos)
                if not (self._legend_has_rows() and self._legend_rect().contains(scene_pos)):
                    self.button.hide()
            else:
                self._hide_unless_hovered()
        return False
