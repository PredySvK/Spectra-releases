"""Draw canvas descriptions and translate mouse gestures into edit signals."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QMenu

from gui.appearance import APP_TOKENS
from core.workflow_graph import INPUT_BLOCK_TYPE
from gui.workspace.channel_drop_target import SELECTION_DRAG_MIME
from signal_processing.workflow import BLOCKS
from view_models.workflow import WorkflowCanvas

# UTF-8 block type shared by the Block Pool producer and canvas drop target.
BLOCK_MIME_TYPE = "application/x-nvh-block-type"

_CONTROLS = "Wheel: zoom. Left-button drag on a block: move. Left-button drag on background or middle-button drag: pan. Double-click a block: focus its Properties. Drag a Selection onto an Input block: pick its data. Left click: select; Ctrl+click: select multiple blocks. Right-click a block > Run Chain: run its connected chain. Drag from Block Pool: add here. Double-click in Block Pool: add with compatible auto-wire. Delete or right-click > Delete blocks: remove selected blocks and their wires. Ctrl+Z / Ctrl+Y: undo / redo committed edits. Ctrl+S: save the project."
_WIRING = "Drag an output port (right) to an input port (left). Grey inputs cannot accept this wire. One output can feed several inputs; wiring an occupied input replaces its wire. Click a wire to select it, then Delete or right-click > Delete wires. Escape cancels a wire drag."


def _build_wire_path(start: QPointF, end: QPointF) -> QPainterPath:
    mid_x = (start.x() + end.x()) / 2
    path = QPainterPath(start)
    path.lineTo(mid_x, start.y())
    path.lineTo(mid_x, end.y())
    path.lineTo(end)
    return path


def _build_save_badge_path() -> QPainterPath:
    """A vector floppy-disk badge, sharp at any DPI without an emoji font."""
    path = QPainterPath(QPointF(0, 0))
    path.lineTo(12, 0)
    path.lineTo(16, 4)
    path.lineTo(16, 16)
    path.lineTo(0, 16)
    path.closeSubpath()
    path.addRect(3, 0, 7, 5)
    path.addRect(3, 9, 10, 7)
    return path


class _WireItem(QGraphicsPathItem):
    """Give thin wires a comfortable hit area without changing their drawing."""

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())

    def boundingRect(self):
        return self.shape().boundingRect()


class _SaveBadgeItem(QGraphicsItem):
    """Paint the save mark as vectors without making it a selectable wire."""

    def boundingRect(self):
        return QRectF(-1, -1, 18, 18)

    def paint(self, painter, option, widget=None):
        painter.setPen(QPen(QColor(APP_TOKENS.workflow_accent), 1.5))
        painter.drawPath(_build_save_badge_path())


class WorkflowCanvasView(QGraphicsView):
    """Blocks and wires with move, selection, zoom and pan gestures."""

    block_selected = Signal(object)
    run_chain_requested = Signal(str)
    properties_requested = Signal(str)
    selection_dropped = Signal(str, object)
    block_moved = Signal(str, float, float)
    block_dropped = Signal(str, float, float)
    delete_requested = Signal(object)
    wire_started = Signal(str)
    wire_requested = Signal(str, str, str)
    wire_delete_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAcceptDrops(True)
        self.setObjectName("WorkflowCanvas")
        self.setToolTip(f"{_CONTROLS}\n{_WIRING}")
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        # Qt paints scene geometry directly at the device pixel ratio.
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(APP_TOKENS.workflow_background))
        self._blocks = {}
        self._wires = []
        self._ports = {}
        self._wire_drag = None
        self._block_drag = None
        self._pan_position = None
        self._pan_button = None
        self._fit_pending = False
        self.scene().selectionChanged.connect(self._on_selection_changed)

    def set_description(self, description: WorkflowCanvas) -> None:
        """Redraw without changing zoom/pan after an edit."""
        scene = self.scene()
        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        scene.blockSignals(True)
        scene.clear()
        self._blocks.clear()
        self._wires.clear()
        self._ports.clear()
        self._wire_drag = None
        self._block_drag = None
        endpoints = {}
        for block in description.blocks:
            item = scene.addRect(0, 0, block.width, block.height,
                                 QPen(QColor(APP_TOKENS.workflow_error if block.error_text else APP_TOKENS.workflow_border), 2),
                                 QColor(APP_TOKENS.workflow_surface))
            item.setPos(block.x, block.y)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            item.setData(0, block.block_id)
            item.setData(3, bool(block.error_text))
            item.setToolTip(
                f"Chain {block.chain_index + 1}"
                + (f"\n{block.error_text}" if block.error_text else "")
                + f"\n{_CONTROLS}"
            )
            self._blocks[block.block_id] = item
            title_lines = [block.label, f"[{block.block_type}]"]
            if block.selection_label is not None:
                title_lines.append(block.selection_label)
            title = scene.addSimpleText("\n".join(title_lines), self.font())
            title.setParentItem(item)
            metrics = QFontMetricsF(title.font())
            title.setText("\n".join(metrics.elidedText(text, Qt.TextElideMode.ElideRight, block.width - 24)
                                    for text in title_lines))
            title.setToolTip(
                f"{block.label} [{block.block_type}]"
                + (f"\n{block.selection_label}" if block.selection_label is not None else "")
                + (f"\n{block.error_text}" if block.error_text else "")
                + f"\n{_CONTROLS}"
            )
            title.setPos(12, 5)
            title.setBrush(QColor(APP_TOKENS.workflow_text))
            title.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            for side in ("left", "right"):
                ports = [port for port in block.ports if port.side == side]
                for index, port in enumerate(ports):
                    x = 0 if side == "left" else block.width
                    y = 62 + 24 * index
                    colour = QColor(APP_TOKENS.workflow_kind_colours.get(port.kinds[0], APP_TOKENS.workflow_muted))
                    dot = scene.addEllipse(-5, -5, 10, 10, QPen(colour), colour)
                    dot.setParentItem(item)
                    dot.setPos(x, y)
                    tooltip = f"{port.name}: {', '.join(port.kinds)}"
                    if port.from_measurement:
                        tooltip += " (from measurement)"
                    if side == "left":
                        tooltip += " (required)" if port.required else " (optional)"
                    dot.setToolTip(f"{tooltip}\n{_WIRING}")
                    dot.setData(1, (block.block_id, port.name, side))
                    dot.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    self._ports[block.block_id, port.name, side] = (dot, colour)
                    port_label = f"{port.name} · from measurement" if port.from_measurement else port.name
                    label = scene.addSimpleText(port_label, self.font())
                    label.setParentItem(item)
                    label.setBrush(colour)
                    label.setPos(10 if side == "left" else block.width - label.boundingRect().width() - 10, y - 9)
                    label.setToolTip(f"{tooltip}\n{_WIRING}")
                    label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    endpoints[block.block_id, port.name, side] = (item, QPointF(x, y))
            if block.save_label is not None:
                badge = _SaveBadgeItem(item)
                badge.setToolTip(f"Save result set: {block.save_label}\n{_CONTROLS}")
                badge.setPos(12, block.height - 22)
                badge.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        for wire in description.wires:
            start = endpoints.get((wire.from_block, wire.from_port, "right"))
            end = endpoints.get((wire.to_block, wire.to_port, "left"))
            if start is None or end is None:
                continue
            item = _WireItem()
            item.setPen(QPen(QColor(APP_TOKENS.workflow_muted), 2))
            scene.addItem(item)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
            item.setData(2, (wire.to_block, wire.to_port))
            item.setToolTip(f"{wire.from_block}.out → {wire.to_block}.{wire.to_port}\n{_WIRING}")
            item.setZValue(-1)
            self._wires.append((item, start, end))
        self._redraw_wires()
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-120, -120, 120, 120).united(visible_rect))
        self.centerOn(visible_rect.center())
        scene.blockSignals(False)

    def _redraw_wires(self) -> None:
        for item, (source, output), (target, input_position) in self._wires:
            start = source.mapToScene(output)
            end = target.mapToScene(input_position)
            item.setPath(_build_wire_path(start, end))

    def reset_view(self) -> None:
        """Fit a newly opened or structurally changed diagram once visible."""
        self._fit_pending = True
        if self.isVisible():
            self._fit_description()

    def _fit_description(self) -> None:
        bounds = self.scene().itemsBoundingRect()
        if not bounds.isEmpty():
            self.fitInView(bounds.adjusted(-20, -20, 20, 20), Qt.AspectRatioMode.KeepAspectRatio)
            if self.transform().m11() > 1:
                self.resetTransform()
            self.centerOn(bounds.center())
        self._fit_pending = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._fit_pending:
            self._fit_description()

    def select_block(self, block_id: str | None) -> None:
        scene = self.scene()
        scene.blockSignals(True)
        scene.clearSelection()
        if block_id in self._blocks:
            self._blocks[block_id].setSelected(True)
        scene.blockSignals(False)
        self._refresh_selection_style()

    def mouseDoubleClickEvent(self, event) -> None:
        item = self._block_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and item is not None:
            self._block_drag = None
            self.select_block(item.data(0))
            self.block_selected.emit(item.data(0))
            self.properties_requested.emit(item.data(0))
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _refresh_selection_style(self) -> None:
        for item in self._blocks.values():
            colour = (APP_TOKENS.workflow_error if item.data(3) else
                      APP_TOKENS.workflow_accent if item.isSelected() else APP_TOKENS.workflow_border)
            item.setPen(QPen(QColor(colour), 3 if item.isSelected() else 2))

    def _on_selection_changed(self) -> None:
        self._refresh_selection_style()
        for item, _, _ in self._wires:
            item.setPen(QPen(QColor(APP_TOKENS.workflow_accent if item.isSelected() else APP_TOKENS.workflow_muted),
                             3 if item.isSelected() else 2))
        for item in self.scene().selectedItems():
            if item.data(0):
                self.block_selected.emit(item.data(0))
                return
        self.block_selected.emit(None)

    def selected_block_ids(self) -> tuple[str, ...]:
        """Return selected workflow blocks, excluding their child decorations."""
        return tuple(item.data(0) for item in self.scene().selectedItems() if item.data(0))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._wire_drag is not None:
            self._cancel_wire_drag()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            block_ids = self.selected_block_ids()
            wires = self._selected_wires()
            if wires:
                self.wire_delete_requested.emit(wires)
            if block_ids:
                self.delete_requested.emit(block_ids)
            event.accept()
            return
        super().keyPressEvent(event)

    def _block_at(self, position):
        item = self.itemAt(position)
        while item is not None and not item.data(0):
            item = item.parentItem()
        return item

    def contextMenuEvent(self, event) -> None:
        hit = self.itemAt(event.pos())
        if hit is not None and hit.data(2):
            if not hit.isSelected():
                self.scene().clearSelection()
                hit.setSelected(True)
            wires = self._selected_wires()
            menu = QMenu(self)
            menu.setToolTipsVisible(True)
            action = menu.addAction("Delete wires")
            action.setToolTip("Delete selected wires (Delete).")
            if menu.exec(event.globalPos()) == action:
                self.wire_delete_requested.emit(wires)
            return
        item = self._block_at(event.pos())
        if item is not None and not item.isSelected():
            self.select_block(item.data(0))
            self.block_selected.emit(item.data(0))
        block_ids = self.selected_block_ids()
        if not block_ids:
            return
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        run_action = menu.addAction("Run Chain") if item is not None else None
        if run_action is not None:
            run_action.setToolTip("Run only this block's connected chain, using its Input selection.")
        action = menu.addAction("Delete blocks")
        action.setToolTip("Delete selected blocks and their wires (Delete).")
        chosen = menu.exec(event.globalPos())
        if run_action is not None and chosen == run_action:
            self.run_chain_requested.emit(item.data(0))
        elif chosen == action:
            self.delete_requested.emit(block_ids)

    def _drop_block_type(self, mime) -> str | None:
        if not mime.hasFormat(BLOCK_MIME_TYPE):
            return None
        try:
            block_type = bytes(mime.data(BLOCK_MIME_TYPE)).decode("utf-8")
        except UnicodeDecodeError:
            return None
        return block_type if block_type == INPUT_BLOCK_TYPE or block_type in BLOCKS else None

    def dragEnterEvent(self, event) -> None:
        if self._drop_block_type(event.mimeData()) is not None or event.mimeData().hasFormat(SELECTION_DRAG_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(SELECTION_DRAG_MIME):
            try:
                name = bytes(event.mimeData().data(SELECTION_DRAG_MIME)).decode("utf-8")
            except UnicodeDecodeError:
                event.ignore()
                return
            item = self._block_at(event.position().toPoint())
            self.selection_dropped.emit(name, item.data(0) if item is not None else None)
            event.acceptProposedAction()
            return
        block_type = self._drop_block_type(event.mimeData())
        if block_type is None:
            event.ignore()
            return
        position = self.mapToScene(event.position().toPoint())
        self.block_dropped.emit(block_type, position.x(), position.y())
        event.acceptProposedAction()

    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta:
            factor = 1.2 if delta > 0 else 1 / 1.2
            current = self.transform().m11()
            target = min(4.0, max(min(0.2, current), current * factor))
            self.scale(target / current, target / current)
        event.accept()

    def mousePressEvent(self, event) -> None:
        hit = self.itemAt(event.position().toPoint())
        port = self._port_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and port is not None:
            if port[2] == "right":
                dot, _ = self._ports[port]
                preview = self.scene().addPath(QPainterPath(), QPen(QColor(APP_TOKENS.workflow_accent), 2))
                preview.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                preview.setZValue(-1)
                self._wire_drag = (port[0], dot.scenePos(), preview)
                self.wire_started.emit(port[0])
            event.accept()
            return
        item = self._block_at(event.position().toPoint())
        background_drag = event.button() == Qt.MouseButton.LeftButton and item is None and not (hit and hit.data(2))
        if event.button() == Qt.MouseButton.MiddleButton or background_drag:
            self._pan_position = event.position()
            self._pan_button = event.button()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and item is not None:
            self._block_drag = (item, self.mapToScene(event.position().toPoint()), item.pos())

    def mouseMoveEvent(self, event) -> None:
        if self._wire_drag is not None:
            _, start, preview = self._wire_drag
            end = self.mapToScene(event.position().toPoint())
            preview.setPath(_build_wire_path(start, end))
            event.accept()
            return
        if self._pan_position is not None:
            delta = event.position() - self._pan_position
            self._pan_position = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            event.accept()
            return
        if self._block_drag is not None:
            item, start, position = self._block_drag
            item.setPos(position + self.mapToScene(event.position().toPoint()) - start)
            self._redraw_wires()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._wire_drag is not None:
            source_id = self._wire_drag[0]
            port = self._port_at(event.position().toPoint())
            self._cancel_wire_drag()
            if port is not None and port[2] == "left":
                self.wire_requested.emit(source_id, port[0], port[1])
            event.accept()
            return
        if event.button() == self._pan_button:
            self._pan_position = None
            self._pan_button = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._block_drag is not None:
            item, _, original = self._block_drag
            self._block_drag = None
            position = item.pos()
            if position != original:
                self.block_moved.emit(item.data(0), position.x(), position.y())

    def _port_at(self, position):
        for item in self.items(position):
            if item.data(1):
                return item.data(1)
        return None

    def set_wire_targets(self, targets: dict[tuple[str, str], str]) -> None:
        """Dim refused input ports for the current output drag."""
        for (block_id, name, side), (dot, colour) in self._ports.items():
            if side == "left":
                shade = QColor(APP_TOKENS.workflow_border) if targets.get((block_id, name)) else colour
                dot.setBrush(shade)
                dot.setPen(QPen(shade))

    def _cancel_wire_drag(self) -> None:
        self.scene().removeItem(self._wire_drag[2])
        self._wire_drag = None
        self.set_wire_targets({})

    def _selected_wires(self) -> tuple[tuple[str, str], ...]:
        return tuple(item.data(2) for item in self.scene().selectedItems() if item.data(2))
