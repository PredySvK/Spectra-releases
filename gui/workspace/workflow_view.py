# =====================================================================
# FILE: gui/workspace/workflow_view.py
# =====================================================================
"""
The Workflow panel (ARCHITECTURE_DECISIONS §1.6, Epic P phase 7C).

An interim editor for the block-diagram workflows a project stores. It is
universal -- not tied to any analysis tab: you make an empty workflow, add
blocks from the palette (each gets its `core/dsp_configs.py` defaults, no ribbon
involved), edit a block's params in place, and pick the measurement selection on
the input node. Wiring is auto-linear here: a new block connects to the selected
node's output when the kinds are compatible.

The node *tree* is a stand-in until phase 8's node canvas, which replaces it as
the authoring surface. What survives that: `core/workflow_graph.py` (the model +
JSON), `signal_processing/workflow.py` (validation, run, BLOCKS), `BlockParamForm`
(the canvas reuses it in a block's settings dialog) and the 7B runner.

Sits in gui/ because it is a Qt widget; it may import signal_processing/. The
central area of sub_area swaps between the analysis docks and this view when the
ribbon's Workflow tab is selected (main_window.show_workflow_view).

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMenu, QPlainTextEdit, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.workflow_graph import (
    INPUT_BLOCK_TYPE, InputSpec, Workflow,
    with_node_replaced, without_node,
)
from selection.source_facets import all_pool_sources, build_channel_facet
from selection.measurement_selection import WHOLE_POOL_SELECTION_NAME
from gui.workspace.block_pool_panel import BLOCK_MIME_TYPE
from gui.workspace.channel_drop_target import SELECTION_DRAG_MIME
from gui.workspace.save_spec_editor import SaveSpecEditor
from signal_processing.workflow import (
    BLOCKS, build_workflow_with_block, resolve_block_params, spec_for,
)
from view_models.workflow import (
    WorkflowStatus, format_input_summary, format_node_summary, format_workflow_status,
)

_NODE_ID_ROLE = Qt.ItemDataRole.UserRole
_NO_SELECTION = "(none)"
_INPUT_NONE = "none"
_INPUT_WHOLE_POOL = "whole_pool"
_INPUT_SELECTION = "selection"

_STATUS_STYLES = {
    WorkflowStatus.NOT_READY: "color: #d9534f; font-size: 10px;",
    WorkflowStatus.READY: "color: #4a9a4a; font-size: 10px;",
}

# `add_block`'s default `wire_to`: connect the new block to the tree's selected
# node. A caller passing an explicit node id (a drop target) or None (a drop on
# blank space) overrides it.
_USE_SELECTED = object()


class _NodeTree(QTreeWidget):
    """The node tree, plus a drop target for Block Pool drags. Emits
    `block_dropped(block_type, node_id_or_None)` -- the id of the node the block
    was dropped on, or None for blank space. Node-to-node rewiring is a later
    7C step, so nothing is draggable out of here yet.

    `delete_requested(node_id)` fires on the Delete key: without a way to remove
    a node, one stray double-click in the Block Pool wedged the workflow forever
    (audit 02 finding 2.4)."""

    block_dropped = Signal(str, object)
    selection_dropped = Signal(str, object)
    delete_requested = Signal(str)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            item = self.currentItem()
            node_id = item.data(0, _NODE_ID_ROLE) if item is not None else None
            if node_id:
                self.delete_requested.emit(node_id)
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(BLOCK_MIME_TYPE) or event.mimeData().hasFormat(SELECTION_DRAG_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(BLOCK_MIME_TYPE) or event.mimeData().hasFormat(SELECTION_DRAG_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasFormat(SELECTION_DRAG_MIME):
            item = self.itemAt(event.position().toPoint())
            self.selection_dropped.emit(
                bytes(mime.data(SELECTION_DRAG_MIME)).decode("utf-8"),
                item.data(0, _NODE_ID_ROLE) if item is not None else None)
            event.acceptProposedAction()
            return
        if not mime.hasFormat(BLOCK_MIME_TYPE):
            super().dropEvent(event)
            return
        block_type = bytes(mime.data(BLOCK_MIME_TYPE)).decode("utf-8")
        item = self.itemAt(event.position().toPoint())
        node_id = item.data(0, _NODE_ID_ROLE) if item is not None else None
        self.block_dropped.emit(block_type, node_id)
        event.acceptProposedAction()


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #9aa0a6; font-size: 10px;")
    return label


class WorkflowView(QWidget):
    """
    Left: the project's workflows by name. Middle: the selected workflow's nodes
    as a tree (the input node is the root, an edge is a parent->child step, a
    fan-out is siblings). Right: the selected node's editor -- a parameter form
    plus a "Save result set" box (`SaveSpecEditor`) for a block, an
    input-selection picker for the input node -- and a plain-text summary of its
    wiring, save spec and lineage. "Apply node settings" writes params and save
    spec together.

    Blocks are added from the Block Pool dock (`block_pool_panel.py`): a
    double-click there calls `add_block`, a drag onto the node tree lands as
    `block_dropped` -> `_on_block_dropped`.
    """

    # The composition root opens the Selection editor and answers with
    # `select_input_selection` (#464).
    create_selection_requested = Signal()

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self._app_context = app_context
        self._workflow: Optional[Workflow] = None
        self._selected_node_id: Optional[str] = None
        self._build_ui()

    # ---- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, stretch=1)
        splitter.addWidget(self._build_workflow_list())
        splitter.addWidget(self._build_node_tree())
        splitter.addWidget(self._build_node_detail())
        splitter.setSizes([170, 250, 380])
        self._splitter = splitter

        self.lbl_empty = QLabel(
            "No workflows yet. Workflow → New Workflow, then add blocks here."
        )
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet("color: #9aa0a6;")
        outer.addWidget(self.lbl_empty)

        self._show_node_editor(None)

    def _build_workflow_list(self) -> QWidget:
        self.list_workflows = QListWidget()
        self.list_workflows.setMinimumWidth(150)
        self.list_workflows.currentItemChanged.connect(lambda *_: self._load_selected_workflow())
        return self._boxed("Workflows", self.list_workflows)

    def _build_node_tree(self) -> QWidget:
        # Blocks come from the Block Pool dock.
        middle = QWidget()
        mid_col = QVBoxLayout(middle)
        mid_col.setContentsMargins(0, 0, 0, 0)
        mid_col.setSpacing(2)
        mid_col.addWidget(_caption("Nodes"))

        self.tree_nodes = _NodeTree()
        self.tree_nodes.setHeaderHidden(True)
        self.tree_nodes.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree_nodes.setAcceptDrops(True)
        self.tree_nodes.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.tree_nodes.currentItemChanged.connect(lambda *_: self._on_node_selected())
        self.tree_nodes.block_dropped.connect(self._on_block_dropped)
        self.tree_nodes.selection_dropped.connect(self._on_selection_dropped)
        self.tree_nodes.delete_requested.connect(self._delete_node)
        self.tree_nodes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_nodes.customContextMenuRequested.connect(self._show_tree_menu)
        mid_col.addWidget(self.tree_nodes, stretch=1)

        # Whether the Workflow tab's Run button would do anything, spelled out
        # rather than left for the user to discover by pressing it.
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        mid_col.addWidget(self.lbl_status)
        return middle

    def _build_node_detail(self) -> QWidget:
        from gui.workspace.block_param_form import BlockParamForm
        detail = QWidget()
        right_col = QVBoxLayout(detail)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.addWidget(_caption("Node detail"))

        self.lbl_node_title = QLabel("Select a node")
        self.lbl_node_title.setStyleSheet("font-weight: bold;")
        right_col.addWidget(self.lbl_node_title)

        self.input_row = QWidget()
        input_layout = QHBoxLayout(self.input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(QLabel("Input selection:"))
        self.combo_input_selection = QComboBox()
        self.combo_input_selection.currentIndexChanged.connect(self._on_input_selection_changed)
        input_layout.addWidget(self.combo_input_selection, stretch=1)
        self.btn_create_selection = QPushButton("Create…")
        self.btn_create_selection.clicked.connect(self.create_selection_requested)
        input_layout.addWidget(self.btn_create_selection)
        right_col.addWidget(self.input_row)

        self.param_form = BlockParamForm()
        right_col.addWidget(self.param_form)

        self.save_editor = SaveSpecEditor(settings=getattr(self._app_context, "settings", None))
        right_col.addWidget(self.save_editor)

        self.btn_apply = QPushButton("Apply node settings")
        self.btn_apply.clicked.connect(self._on_apply_params)
        right_col.addWidget(self.btn_apply)

        self.txt_summary = QPlainTextEdit()
        self.txt_summary.setReadOnly(True)
        right_col.addWidget(self.txt_summary, stretch=1)
        return detail

    @staticmethod
    def _boxed(title: str, inner: QWidget) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(_caption(title))
        col.addWidget(inner, stretch=1)
        return box

    # ---- session ---------------------------------------------------------

    def _session(self):
        return getattr(self._app_context, "project_session", None)

    def _editable(self) -> bool:
        return self._session() is not None

    # ---- workflow list --------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the workflow list from the session, keeping the current
        selection by name when it still exists."""
        session = self._session()
        workflows = list(session.workflows()) if session is not None else []
        names = [w.name for w in workflows]

        previous = self.current_workflow_name()
        self.list_workflows.blockSignals(True)
        self.list_workflows.clear()
        for name in names:
            self.list_workflows.addItem(QListWidgetItem(name))
        self.list_workflows.blockSignals(False)

        has_any = bool(names)
        self._splitter.setVisible(has_any)
        self.lbl_empty.setVisible(not has_any)
        if not has_any:
            self._workflow = None
            self.tree_nodes.clear()
            self._show_node_editor(None)
            self._refresh_status()
            return

        target = names.index(previous) if previous in names else 0
        self.list_workflows.setCurrentRow(target)
        self._load_selected_workflow()

    def select_workflow(self, name: str) -> None:
        for row in range(self.list_workflows.count()):
            if self.list_workflows.item(row).text() == name:
                self.list_workflows.setCurrentRow(row)
                return

    def current_workflow_name(self) -> Optional[str]:
        item = self.list_workflows.currentItem()
        return item.text() if item is not None else None

    def _load_selected_workflow(self) -> None:
        session = self._session()
        name = self.current_workflow_name()
        self._workflow = session.find_workflow(name) if (session is not None and name) else None
        self._selected_node_id = None
        self._rebuild_tree()

    # ---- node tree -----------------------------------------------------

    def _rebuild_tree(self, keep_node_id: Optional[str] = None) -> None:
        self.tree_nodes.blockSignals(True)
        self.tree_nodes.clear()
        workflow = self._workflow
        first_item = None
        if workflow is not None:
            with_incoming = {edge.to_node for edge in workflow.edges}
            roots = [n.node_id for n in workflow.nodes if n.node_id not in with_incoming]
            if not roots:
                roots = list(workflow.node_ids)
            seen: set = set()
            for root in roots:
                item = self._tree_item(workflow, root, seen)
                self.tree_nodes.addTopLevelItem(item)
                if first_item is None:
                    first_item = item
            self.tree_nodes.expandAll()
        self.tree_nodes.blockSignals(False)

        target = self._find_item(keep_node_id) if keep_node_id else None
        self.tree_nodes.setCurrentItem(target or first_item)
        self._on_node_selected()
        self._refresh_status()

    def _refresh_status(self) -> None:
        """A one-line 'can this run?' under the tree, redrawn on every edit and
        every workflow switch (both go through _rebuild_tree)."""
        find_selection = getattr(self._session(), "find_selection", None)
        status, text = format_workflow_status(self._workflow, find_selection)
        self.lbl_status.setText(text)
        if status is not WorkflowStatus.EMPTY:
            self.lbl_status.setStyleSheet(_STATUS_STYLES[status])

    def _tree_item(self, workflow: Workflow, node_id: str, seen: set) -> QTreeWidgetItem:
        item = QTreeWidgetItem([self._node_label(workflow, node_id)])
        item.setData(0, _NODE_ID_ROLE, node_id)
        if node_id in seen:
            return item
        seen.add(node_id)
        for edge in workflow.outgoing(node_id):
            item.addChild(self._tree_item(workflow, edge.to_node, seen))
        return item

    def _find_item(self, node_id: str) -> Optional[QTreeWidgetItem]:
        stack = [self.tree_nodes.topLevelItem(i) for i in range(self.tree_nodes.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item is None:
                continue
            if item.data(0, _NODE_ID_ROLE) == node_id:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        return None

    def _node_label(self, workflow: Workflow, node_id: str) -> str:
        node = workflow.node(node_id)
        if node.is_input:
            base = f"{node_id}  ‹input: {format_input_summary(node.input)}›"
        else:
            base = f"{node_id}  [{node.block_type}]"
        if node.save is not None:
            base += f"  💾 {node.save.label or '(auto name)'}"
        return base

    # ---- right panel --------------------------------------------------

    def _on_node_selected(self) -> None:
        workflow = self._workflow
        item = self.tree_nodes.currentItem()
        node = None
        if workflow is not None and item is not None:
            try:
                node = workflow.node(item.data(0, _NODE_ID_ROLE))
            except KeyError:
                node = None
        self._selected_node_id = node.node_id if node is not None else None
        self._show_node_editor(node)

    def _show_node_editor(self, node) -> None:
        editable = self._editable()

        if node is None:
            self.lbl_node_title.setText("Select a node")
            self.input_row.setVisible(False)
            self.param_form.setVisible(False)
            self.save_editor.setVisible(False)
            self.btn_apply.setVisible(False)
            self.param_form.clear()
            self.txt_summary.clear()
            return

        if node.is_input:
            self.lbl_node_title.setText(f"{node.node_id} — input node")
            self.input_row.setVisible(True)
            self.param_form.setVisible(False)
            self.save_editor.setVisible(False)
            self.btn_apply.setVisible(False)
            self.param_form.clear()
            self._populate_input_combo(node.input)
            self.combo_input_selection.setEnabled(editable)
            self.txt_summary.setPlainText(
                "Input node. Pick what this workflow runs over:\n"
                f"  • '{WHOLE_POOL_SELECTION_NAME}' -- every measurement in the Data Pool, all "
                "channels, growing as the pool grows (the default).\n"
                "  • a saved selection -- a named subset, if one exists in the project.\n"
                "Resolved by the runner per file; not a registered block."
            )
            return

        self.lbl_node_title.setText(f"{node.node_id} — {node.block_type}")
        self.input_row.setVisible(False)
        try:
            spec = spec_for(node.block_type)
        except ValueError as exc:
            self.param_form.setVisible(False)
            self.save_editor.setVisible(False)
            self.btn_apply.setVisible(False)
            self.param_form.clear()
            self.txt_summary.setPlainText(str(exc))
            return
        self.param_form.setVisible(True)
        self.save_editor.setVisible(True)
        self.btn_apply.setVisible(True)
        self.btn_apply.setEnabled(editable)
        self.param_form.set_config(spec.config_cls, node.params, read_only=not editable)
        self.save_editor.set_spec(
            node.save, channel_groups=self._channel_groups(), read_only=not editable
        )
        self.txt_summary.setPlainText(format_node_summary(self._workflow, node, spec))

    def _channel_groups(self) -> dict:
        """`{base name: [directions]}` across the whole Data Pool -- what the
        SaveSpec editor's channel picker offers. The Data Pool, not
        `loaded_runs`: a workflow runs over a selection, so its save filter is
        scoped by the project."""
        session = self._session()
        if session is None:
            return {}
        groups: dict = {}
        for base, direction in build_channel_facet(all_pool_sources(session.project)):
            groups.setdefault(base, []).append(direction)
        return groups

    def select_input_selection(self, name: str) -> None:
        """Pick the stored selection `name` in the Input combo (and so on the
        Input node on screen) -- the Selection editor just saved it (#464)."""
        self.refresh_input_selections()
        combo = self.combo_input_selection
        for index in range(combo.count()):
            if combo.itemData(index) == (_INPUT_SELECTION, name):
                combo.setCurrentIndex(index)
                return

    def refresh_input_selections(self) -> None:
        """Re-offer the project's selections in the Input combo of the node on
        screen, keeping its pick -- a Selection was stored, renamed or deleted
        elsewhere (#462, #463)."""
        session = self._session()
        if self._workflow is not None and session is not None:
            # A rename rewrote the Input nodes behind the view's back (#463).
            self._workflow = session.find_workflow(self._workflow.name) or self._workflow
            self._refresh_status()
        if self._workflow is None or self._selected_node_id is None:
            return
        try:
            node = self._workflow.node(self._selected_node_id)
        except KeyError:
            return
        if node.is_input:
            self._populate_input_combo(node.input)

    def _populate_input_combo(self, spec: Optional[InputSpec]) -> None:
        session = self._session()
        names = [s.name for s in session.selections()] if session is not None else []
        self.combo_input_selection.blockSignals(True)
        self.combo_input_selection.clear()
        # Items carry their meaning as data, not as text: a user selection may
        # share its display text with the synthetic whole-pool item.
        self.combo_input_selection.addItem(_NO_SELECTION, _INPUT_NONE)
        self.combo_input_selection.addItem(WHOLE_POOL_SELECTION_NAME, _INPUT_WHOLE_POOL)
        for name in names:
            self.combo_input_selection.addItem(name, (_INPUT_SELECTION, name))
        if spec is not None and spec.whole_pool:
            self.combo_input_selection.setCurrentIndex(1)
        elif spec is not None and spec.selection_name in names:
            self.combo_input_selection.setCurrentIndex(2 + names.index(spec.selection_name))
        else:
            self.combo_input_selection.setCurrentIndex(0)
        self.combo_input_selection.blockSignals(False)

    # ---- edits -------------------------------------------------------

    def _save(self, workflow: Workflow, keep_node_id: Optional[str]) -> None:
        session = self._session()
        if session is None:
            return
        session.save_workflow(workflow)
        self._workflow = workflow
        self._rebuild_tree(keep_node_id)

    def add_block(self, block_type: str, wire_to=_USE_SELECTED) -> None:
        """
        Add a block of `block_type` to the current workflow. `wire_to` is the id
        of the node to connect the block's primary input to, None to leave it
        unconnected, or the `_USE_SELECTED` sentinel (the default, used by the
        Block Pool's double-click) to use the tree's selected node.

        The edge is only made when the source is single-output and its kind is
        one the new block's primary port accepts; otherwise the block lands
        unconnected, the same as today's "+ Add Block".

        `INPUT_BLOCK_TYPE` is not in `BLOCKS` -- it is a node, not a block -- so
        it takes its own path: a new input node, never wired, defaulting to the
        whole pool. A graph may carry several (phase 8's canvas branches from
        two inputs); the 7A runner still only runs a single-input graph.
        """
        workflow = self._workflow
        if workflow is None or not self._editable():
            return

        if block_type != INPUT_BLOCK_TYPE and block_type not in BLOCKS:
            return
        source_id = self._selected_node_id if wire_to is _USE_SELECTED else wire_to
        workflow, node_id = build_workflow_with_block(workflow, block_type, source_id)
        self._app_context.log(f"WORKFLOW: added '{node_id}' to '{workflow.name}'.")
        self._save(workflow, keep_node_id=node_id)

    def _on_block_dropped(self, block_type: str, node_id) -> None:
        """A Block Pool row was dragged onto the node tree. `node_id` is the
        node it landed on, or None for blank space (adds it unconnected)."""
        self.add_block(block_type, wire_to=node_id)

    def _on_selection_dropped(self, name: str, node_id) -> None:
        """A Selection was dragged onto the node tree: on the Input node it becomes the input (#465)."""
        workflow = self._workflow
        if workflow is None or node_id is None or not workflow.node(node_id).is_input:
            return
        self.tree_nodes.setCurrentItem(self._find_item(node_id))
        self.select_input_selection(name)

    def _show_tree_menu(self, pos) -> None:
        item = self.tree_nodes.itemAt(pos)
        node_id = item.data(0, _NODE_ID_ROLE) if item is not None else None
        if not node_id or not self._editable():
            return
        menu = QMenu(self)
        menu.addAction("Delete node", lambda: self._delete_node(node_id))
        menu.exec(self.tree_nodes.viewport().mapToGlobal(pos))

    def _delete_node(self, node_id: str) -> None:
        """Drop a node (and its edges) from the current workflow. Without this a
        stray block or a second input node wedged the workflow with no way back
        through the UI (audit 02 finding 2.4). The status line flags whatever the
        removal leaves not-ready."""
        workflow = self._workflow
        if workflow is None or not self._editable() or node_id not in workflow.node_ids:
            return
        workflow = without_node(workflow, node_id)
        self._app_context.log(f"WORKFLOW: removed '{node_id}' from '{workflow.name}'.")
        self._save(workflow, keep_node_id=None)

    def _on_apply_params(self) -> None:
        """"Apply node settings" -- writes the parameter form *and* the save spec
        in one rebuild, so a node is one save to the project and one tree
        redraw, not two."""
        workflow = self._workflow
        node_id = self._selected_node_id
        if workflow is None or node_id is None or not self._editable():
            return
        node = workflow.node(node_id)
        if node.is_input:
            return
        params = resolve_block_params(node.block_type, self.param_form.values())
        workflow = with_node_replaced(
            workflow, node_id,
            params=params,
            save=self.save_editor.current_spec(),
        )
        self._save(workflow, keep_node_id=node_id)

    def _on_input_selection_changed(self, index: int) -> None:
        workflow = self._workflow
        node_id = self._selected_node_id
        if workflow is None or node_id is None or not self._editable():
            return
        node = workflow.node(node_id)
        if not node.is_input:
            return
        data = self.combo_input_selection.itemData(index)
        if data == _INPUT_WHOLE_POOL:
            new_spec = InputSpec(whole_pool=True)
        elif isinstance(data, tuple) and data[0] == _INPUT_SELECTION:
            new_spec = InputSpec(selection_name=data[1])
        else:
            new_spec = InputSpec()
        if node.input == new_spec:
            return
        workflow = with_node_replaced(workflow, node_id, input=new_spec)
        self._save(workflow, keep_node_id=node_id)
