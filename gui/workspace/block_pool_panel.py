# =====================================================================
# FILE: gui/workspace/block_pool_panel.py
# =====================================================================
"""
The Block Pool: the palette of processing blocks you drop into a workflow
(ARCHITECTURE_DECISIONS §1.6, Epic P phase 7C).

One row per entry in `signal_processing.workflow.BLOCKS`. A row can be
double-clicked -- adds the block wired to the workflow's currently selected block
-- or dragged onto the Workflow canvas, which places it unconnected at the cursor.
This replaces the "+ Add Block" menu that used to live inside WorkflowView.

Sits in gui/ because it is a Qt widget; it may import signal_processing/. It is
built by UnvChannelExplorer as a sub-tab of the Explorer dock, shown only while
the ribbon's Workflow tab is active (main_window.show_workflow_view ->
UnvChannelExplorer.set_block_pool_visible). The canvas consumes the BLOCK_MIME_TYPE contract.

All internal documentation strings and variable labels are standardly written
in English.
"""
from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from core.workflow_graph import INPUT_BLOCK_TYPE
from gui.workflow import BLOCK_MIME_TYPE, apply_workflow_style
from signal_processing.workflow import BLOCKS, spec_for

# The input node is a node, not a registered block: it has no adapter in BLOCKS
# (signal_processing stays I/O-free). It still belongs in the palette -- it is
# the first node of every diagram, and phase 8's canvas can carry several -- so
# it rides the same drag/double-click contract, keyed by INPUT_BLOCK_TYPE, which
# WorkflowView.add_block special-cases.
_INPUT_BLURB = "The measurement data a workflow runs over (whole Data Pool, or a saved selection)."

_BLOCK_BLURB = {
    "remove_dc": "Subtract the DC offset from a time signal.",
    "spectrum": "Averaged single-sided FFT spectrum.",
    "spectrogram": "Time- or rpm-tracked waterfall.",
    "order_tracking": "Amplitude of each order versus rpm.",
    "overall_level": "Energy of one frequency band versus rpm or time.",
}

_BLOCK_TYPE_ROLE = Qt.ItemDataRole.UserRole


def _pretty_block(block_type: str) -> str:
    return block_type.replace("_", " ").title()


class _BlockList(QListWidget):
    """A list whose rows drag a `BLOCK_MIME_TYPE` payload (and nothing else --
    the pool is a source, never a drop target)."""

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        block_type = item.data(_BLOCK_TYPE_ROLE)
        mime = QMimeData()
        mime.setData(BLOCK_MIME_TYPE, block_type.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class BlockPoolPanel(QWidget):
    """The palette. Emits `block_activated(block_type)` on a double-click; the
    drag side is handled by `_BlockList` and consumed by the canvas."""

    block_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        apply_workflow_style(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(4)

        hint = QLabel("Drag a block onto the canvas, or double-click to auto-wire to the selected block.")
        hint.setWordWrap(True)
        hint.setProperty("workflowCaption", True)
        layout.addWidget(hint)

        self.list = _BlockList(self)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.itemDoubleClicked.connect(
            lambda item: self.block_activated.emit(item.data(_BLOCK_TYPE_ROLE))
        )
        layout.addWidget(self.list, stretch=1)

        input_item = QListWidgetItem("Input Data")
        input_item.setData(_BLOCK_TYPE_ROLE, INPUT_BLOCK_TYPE)
        gestures = "Drag onto the canvas to place a block. Double-click to add with compatible auto-wire. Select blocks on the canvas; Delete or right-click > Delete blocks removes them and their wires."
        self.list.setToolTip(gestures)
        input_item.setToolTip(f"{_INPUT_BLURB}\n{gestures}")
        self.list.addItem(input_item)

        for block_type in BLOCKS:
            spec = spec_for(block_type)
            item = QListWidgetItem(_pretty_block(block_type))
            item.setData(_BLOCK_TYPE_ROLE, block_type)
            blurb = _BLOCK_BLURB.get(block_type, "")
            item.setToolTip(f"{blurb}\nProduces: {spec.produces}\n{gestures}".strip())
            self.list.addItem(item)
