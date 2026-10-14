# =====================================================================
# FILE: gui/workspace/workflow_view.py
# =====================================================================
"""Canvas workflow editor with workflow tabs and Properties.

The scene projects the immutable Workflow; edits are stored through the project
session. Existing parameter, Input selection and Save settings forms are reused.
"""
from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLayout,
    QPushButton, QScrollArea, QSplitter, QTabBar,
    QToolBar, QVBoxLayout, QWidget,
)

from core.workflow_graph import (
    INPUT_BLOCK_TYPE, InputSpec, Workflow,
    with_block_replaced,
)
from selection.source_facets import all_pool_sources, build_channel_facet
from selection.measurement_selection import WHOLE_POOL_SELECTION_NAME
from gui.workspace.save_spec_editor import SaveSpecEditor
from gui.workflow import WorkflowCanvasView, apply_workflow_style
from signal_processing.workflow import (
    BLOCKS, resolve_block_params, spec_for,
)
from view_models.workflow import (
    format_workflow_status,
    build_workflow_canvas, resolve_block_move, resolve_block_add, resolve_block_delete,
    resolve_wire_connect, resolve_wire_targets, resolve_wire_disconnect,
)

_NO_SELECTION = "(none)"
_INPUT_NONE = "none"
_INPUT_WHOLE_POOL = "whole_pool"
_INPUT_SELECTION = "selection"

# `add_block`'s default `wire_to`: connect the new block to the canvas's selected
# block. A caller passing an explicit block id (a drop target) or None (a drop on
# blank space) overrides it.
_USE_SELECTED = object()


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("workflowCaption", True)
    return label


class WorkflowView(QWidget):
    """Author the active workflow on the canvas and edit selected block properties."""

    # The composition root opens the Selection editor and answers with
    # `select_input_selection` (#464).
    create_selection_requested = Signal()
    block_selection_changed = Signal(object)
    run_chain_requested = Signal(str)

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        apply_workflow_style(self)
        self._app_context = app_context
        self._workflow: Optional[Workflow] = None
        self._selected_block_id: Optional[str] = None
        self._build_ui()
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        # Editable Properties fields normally claim Ctrl+Z for their own text.
        # Within this editor the shortcuts restore committed workflow snapshots.
        if (event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                and isinstance(watched, QWidget) and self.isAncestorOf(watched)
                and self.isVisible()
                and event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and event.key() in (Qt.Key.Key_Z, Qt.Key.Key_Y)):
            event.accept()
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Z:
                    self.undo()
                else:
                    self.redo()
            return True
        return super().eventFilter(watched, event)

    # ---- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        toolbar = QToolBar("Workflow history", self)
        self.undo_action = toolbar.addAction("Undo")
        self.redo_action = toolbar.addAction("Redo")
        self.undo_action.setToolTip("Undo the last workflow edit (Ctrl+Z)")
        self.redo_action.setToolTip("Redo the last undone workflow edit (Ctrl+Y)")
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self._undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._undo_shortcut.activated.connect(self.undo)
        self._redo_shortcut.activated.connect(self.redo)
        outer.addWidget(toolbar)
        self._refresh_history_actions()

        self.workflow_tabs = QTabBar()
        self.workflow_tabs.setExpanding(False)
        self.workflow_tabs.setUsesScrollButtons(True)
        self.workflow_tabs.setToolTip("Click a workflow tab to open its canvas.")
        self.workflow_tabs.currentChanged.connect(lambda *_: self._load_selected_workflow())
        outer.addWidget(self.workflow_tabs)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, stretch=1)

        self.canvas = WorkflowCanvasView()
        self.canvas.block_selected.connect(self._on_canvas_block_selected)
        self.canvas.run_chain_requested.connect(self.run_chain_requested)
        self.canvas.properties_requested.connect(self._focus_properties)
        self.canvas.selection_dropped.connect(self._on_selection_dropped)
        self.canvas.block_moved.connect(self._on_canvas_block_moved)
        self.canvas.block_dropped.connect(self._on_canvas_block_dropped)
        self.canvas.delete_requested.connect(self._delete_blocks)
        self.canvas.wire_started.connect(self._on_wire_started)
        self.canvas.wire_requested.connect(self._on_wire_requested)
        self.canvas.wire_delete_requested.connect(self._delete_wires)
        canvas_box = self._boxed("Workflow canvas", self.canvas)
        self.lbl_wire_reason = QLabel("")
        self.lbl_wire_reason.setWordWrap(True)
        self.lbl_wire_reason.setProperty("workflowError", True)
        canvas_box.layout().addWidget(self.lbl_wire_reason)
        splitter.addWidget(canvas_box)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setToolTip("Readiness of the whole workflow. Run skips refused chains; Run Chain uses the selected block's chain.")
        canvas_box.layout().addWidget(self.lbl_status)
        self.properties_scroll = QScrollArea()
        self.properties_scroll.setObjectName("WorkflowProperties")
        self.properties_scroll.setWidgetResizable(True)
        self.properties_scroll.setToolTip("Double-click a canvas block to focus Properties. Ctrl+Z / Ctrl+Y restore committed workflow edits, including while a field has focus.")
        self.properties_scroll.setWidget(self._build_block_detail())
        splitter.addWidget(self.properties_scroll)
        splitter.setSizes([900, 360])
        self._splitter = splitter

        self.lbl_empty = QLabel(
            "No workflows yet. Workflow → New Workflow, then add blocks here."
        )
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setProperty("workflowCaption", True)
        outer.addWidget(self.lbl_empty)

        self._show_block_editor(None)

    def _build_block_detail(self) -> QWidget:
        from gui.workspace.block_param_form import BlockParamForm
        detail = QWidget()
        right_col = QVBoxLayout(detail)
        right_col.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        right_col.setContentsMargins(8, 8, 8, 8)
        right_col.addWidget(_caption("Properties"))

        self.lbl_block_title = QLabel("Select a block")
        self.lbl_block_title.setStyleSheet("font-weight: bold;")
        self.lbl_block_title.setWordWrap(True)
        right_col.addWidget(self.lbl_block_title)

        self.input_row = QWidget()
        input_layout = QHBoxLayout(self.input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(QLabel("Input selection:"))
        self.combo_input_selection = QComboBox()
        self.combo_input_selection.setToolTip("Choose Whole Data Pool or a saved Selection; applies immediately. You can also drag a Selection onto an Input block.")
        self.combo_input_selection.currentIndexChanged.connect(self._on_input_selection_changed)
        input_layout.addWidget(self.combo_input_selection, stretch=1)
        self.btn_create_selection = QPushButton("Create…")
        self.btn_create_selection.setToolTip("Open the Selection editor to create an Input selection.")
        self.btn_create_selection.clicked.connect(self.create_selection_requested)
        input_layout.addWidget(self.btn_create_selection)
        right_col.addWidget(self.input_row)

        self.param_form = BlockParamForm()
        self.param_form.layout().setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        right_col.addWidget(self.param_form)

        self.save_editor = SaveSpecEditor(settings=getattr(self._app_context, "settings", None))
        right_col.addWidget(self.save_editor)

        self.btn_apply = QPushButton("Apply block settings")
        self.btn_apply.setToolTip("Commit parameters and Save settings together. Ctrl+Z / Ctrl+Y undo or redo committed edits; Ctrl+S saves the project.")
        self.btn_apply.clicked.connect(self._on_apply_params)
        right_col.addWidget(self.btn_apply)
        right_col.addStretch(1)
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
        self.workflow_tabs.blockSignals(True)
        while self.workflow_tabs.count():
            self.workflow_tabs.removeTab(0)
        for name in names:
            self.workflow_tabs.addTab(name)
        self.workflow_tabs.blockSignals(False)

        has_any = bool(names)
        self.workflow_tabs.setVisible(has_any)
        self._splitter.setVisible(has_any)
        self.lbl_empty.setVisible(not has_any)
        if not has_any:
            self._workflow = None
            self.canvas.set_description(build_workflow_canvas(None))
            self._show_block_editor(None)
            self._refresh_status()
            self._refresh_history_actions()
            return

        target = names.index(previous) if previous in names else 0
        self.workflow_tabs.setCurrentIndex(target)
        self._load_selected_workflow()

    def select_workflow(self, name: str) -> None:
        for row in range(self.workflow_tabs.count()):
            if self.workflow_tabs.tabText(row) == name:
                self.workflow_tabs.setCurrentIndex(row)
                return

    def current_workflow_name(self) -> Optional[str]:
        index = self.workflow_tabs.currentIndex()
        return self.workflow_tabs.tabText(index) if index >= 0 else None

    def current_block_id(self) -> Optional[str]:
        """The active block whose connected chain Run Chain will use."""
        return self._selected_block_id

    def _load_selected_workflow(self) -> None:
        session = self._session()
        name = self.current_workflow_name()
        self._workflow = session.find_workflow(name) if (session is not None and name) else None
        self._selected_block_id = None
        self._refresh_canvas()
        self.canvas.reset_view()

    # ---- canvas ----------------------------------------------------------

    def _refresh_canvas(self, keep_block_id: Optional[str] = None) -> None:
        self._refresh_history_actions()
        self.lbl_wire_reason.clear()
        self.canvas.set_description(build_workflow_canvas(
            self._workflow, getattr(self._session(), "find_selection", None)))
        block_ids = [block.block_id for block in self._workflow.blocks] if self._workflow is not None else []
        block_id = keep_block_id if keep_block_id in block_ids else (block_ids[0] if block_ids else None)
        self.canvas.select_block(block_id)
        self._on_canvas_block_selected(block_id)
        self._refresh_status()

    def _focus_properties(self, _block_id: str) -> None:
        if self.input_row.isVisibleTo(self):
            target = self.combo_input_selection
        else:
            widgets = self.param_form.findChildren(QWidget)
            target = next((widget for widget in widgets if widget.isVisibleTo(self)
                           and widget.focusPolicy() != Qt.FocusPolicy.NoFocus), self.properties_scroll)
        self.properties_scroll.ensureWidgetVisible(target)
        target.setFocus()

    def _refresh_status(self) -> None:
        """A one-line 'can this run?' under the canvas, redrawn on every edit and
        every workflow switch (both go through _refresh_canvas)."""
        find_selection = getattr(self._session(), "find_selection", None)
        status, text = format_workflow_status(self._workflow, find_selection)
        self.lbl_status.setText(text)
        self.lbl_status.setProperty("workflowStatus", status.value)
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    # ---- Properties ------------------------------------------------------

    def _on_canvas_block_selected(self, block_id: str | None) -> None:
        self._selected_block_id = block_id
        self.block_selection_changed.emit(block_id)
        block = self._workflow.block(block_id) if self._workflow is not None and block_id is not None else None
        self._show_block_editor(block)

    def _on_canvas_block_moved(self, block_id: str, x: float, y: float) -> None:
        if self._workflow is None or not self._editable():
            return
        moved = resolve_block_move(self._workflow, block_id, (x, y))
        if moved is not self._workflow:
            self._save(moved, keep_block_id=block_id)

    def _on_wire_started(self, source_id: str) -> None:
        self.lbl_wire_reason.clear()
        if self._workflow is not None:
            self.canvas.set_wire_targets(resolve_wire_targets(self._workflow, source_id))

    def _on_wire_requested(self, source_id: str, target_id: str, port_name: str) -> None:
        if self._workflow is None or not self._editable():
            return
        workflow, reason = resolve_wire_connect(self._workflow, source_id, target_id, port_name)
        if reason:
            self.lbl_wire_reason.setText(reason)
        elif workflow is not self._workflow:
            self._save(workflow, keep_block_id=target_id)

    def _delete_wires(self, ports) -> None:
        if self._workflow is None or not self._editable():
            return
        workflow = self._workflow
        for target_id, port_name in ports:
            workflow = resolve_wire_disconnect(workflow, target_id, port_name)
        if workflow is not self._workflow:
            self._save(workflow, keep_block_id=self._selected_block_id)

    def _show_block_editor(self, workflow_block) -> None:
        editable = self._editable()

        if workflow_block is None:
            self.lbl_block_title.setText("Select a block")
            self.input_row.setVisible(False)
            self.param_form.setVisible(False)
            self.save_editor.setVisible(False)
            self.btn_apply.setVisible(False)
            self.param_form.clear()
            return

        if workflow_block.is_input:
            self.lbl_block_title.setText(f"{workflow_block.block_id} — Input block")
            self.input_row.setVisible(True)
            self.param_form.setVisible(False)
            self.save_editor.setVisible(False)
            self.btn_apply.setVisible(False)
            self.param_form.clear()
            self._populate_input_combo(workflow_block.input)
            self.combo_input_selection.setEnabled(editable)
            return

        self.lbl_block_title.setText(f"{workflow_block.block_id} — {workflow_block.block_type}")
        self.input_row.setVisible(False)
        try:
            spec = spec_for(workflow_block.block_type)
        except ValueError as exc:
            self.lbl_block_title.setText(f"{workflow_block.block_id} — {exc}")
            self.param_form.setVisible(False)
            self.save_editor.setVisible(False)
            self.btn_apply.setVisible(False)
            self.param_form.clear()
            return
        self.param_form.setVisible(True)
        self.save_editor.setVisible(True)
        self.btn_apply.setVisible(True)
        self.btn_apply.setEnabled(editable)
        self.param_form.set_config(spec.config_cls, workflow_block.params, read_only=not editable)
        self.save_editor.set_spec(
            workflow_block.save, channel_groups=self._channel_groups(), read_only=not editable
        )

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
        Input block on screen) -- the Selection editor just saved it (#464)."""
        self.refresh_input_selections()
        combo = self.combo_input_selection
        for index in range(combo.count()):
            if combo.itemData(index) == (_INPUT_SELECTION, name):
                combo.setCurrentIndex(index)
                return

    def refresh_input_selections(self) -> None:
        """Re-offer the project's selections in the Input combo of the block on
        screen, keeping its pick -- a Selection was stored, renamed or deleted
        elsewhere (#462, #463)."""
        session = self._session()
        if self._workflow is not None and session is not None:
            # A rename rewrote the Input blocks behind the view's back (#463).
            self._workflow = session.find_workflow(self._workflow.name) or self._workflow
            self._refresh_canvas(self._selected_block_id)
        if self._workflow is None or self._selected_block_id is None:
            return
        try:
            workflow_block = self._workflow.block(self._selected_block_id)
        except KeyError:
            return
        if workflow_block.is_input:
            self._populate_input_combo(workflow_block.input)

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

    def _refresh_history_actions(self) -> None:
        session = self._session()
        name = self._workflow.name if self._workflow is not None else None
        self.undo_action.setEnabled(bool(name and session and session.can_undo_workflow(name)))
        self.redo_action.setEnabled(bool(name and session and session.can_redo_workflow(name)))

    def undo(self) -> None:
        """Undo one committed edit of the active workflow."""
        session = self._session()
        if self._workflow is not None and session is not None:
            self._show_restored(session.undo_workflow(self._workflow.name))

    def redo(self) -> None:
        """Redo one edit of the active workflow."""
        session = self._session()
        if self._workflow is not None and session is not None:
            self._show_restored(session.redo_workflow(self._workflow.name))

    def _show_restored(self, workflow: Optional[Workflow]) -> None:
        if workflow is not None:
            self._workflow = workflow
            self._refresh_canvas(self._selected_block_id)

    def _save(self, workflow: Workflow, keep_block_id: Optional[str]) -> None:
        session = self._session()
        if session is None:
            return
        session.save_workflow(workflow)
        self._workflow = workflow
        self._refresh_canvas(keep_block_id)

    def add_block(self, block_type: str, wire_to=_USE_SELECTED) -> None:
        """
        Add a block of `block_type` to the current workflow. `wire_to` is the id
        of the block to connect the block's primary input to, None to leave it
        unconnected, or the `_USE_SELECTED` sentinel (the default, used by the
        Block Pool's double-click) to use the canvas's selected block.

        The wire is only made when the source is single-output and its kind is
        one the new block's primary port accepts; otherwise the block lands
        unconnected, the same as today's "+ Add Block".

        `INPUT_BLOCK_TYPE` is not in `BLOCKS` -- it is a block, not a block -- so
        it takes its own path: a new input block, never wired, defaulting to the
        whole pool. A graph may carry several (phase 8's canvas branches from
        two inputs); the 7A runner still only runs a single-input graph.
        """
        workflow = self._workflow
        if workflow is None or not self._editable():
            return

        if block_type != INPUT_BLOCK_TYPE and block_type not in BLOCKS:
            return
        source_id = self._selected_block_id if wire_to is _USE_SELECTED else wire_to
        workflow, block_id = resolve_block_add(workflow, block_type, source_id)
        self._app_context.log(f"WORKFLOW: added '{block_id}' to '{workflow.name}'.")
        self._save(workflow, keep_block_id=block_id)

    def _on_canvas_block_dropped(self, block_type: str, x: float, y: float) -> None:
        if self._workflow is None or not self._editable():
            return
        workflow, block_id = resolve_block_add(self._workflow, block_type, position=(x, y))
        self._save(workflow, keep_block_id=block_id)

    def _on_selection_dropped(self, name: str, block_id) -> None:
        workflow = self._workflow
        if workflow is None or block_id is None or not workflow.block(block_id).is_input:
            return
        self.canvas.select_block(block_id)
        self._on_canvas_block_selected(block_id)
        self.select_input_selection(name)

    def _delete_blocks(self, block_ids) -> None:
        if self._workflow is None or not self._editable():
            return
        workflow = resolve_block_delete(self._workflow, block_ids)
        if workflow is not self._workflow:
            self._save(workflow, keep_block_id=None)

    def _on_apply_params(self) -> None:
        """"Apply block settings" -- writes the parameter form *and* the save spec
        in one rebuild, so a block is one save to the project and one canvas
        redraw, not two."""
        workflow = self._workflow
        block_id = self._selected_block_id
        if workflow is None or block_id is None or not self._editable():
            return
        workflow_block = workflow.block(block_id)
        if workflow_block.is_input:
            return
        params = resolve_block_params(workflow_block.block_type, self.param_form.values())
        workflow = with_block_replaced(
            workflow, block_id,
            params=params,
            save=self.save_editor.current_spec(),
        )
        self._save(workflow, keep_block_id=block_id)

    def _on_input_selection_changed(self, index: int) -> None:
        workflow = self._workflow
        block_id = self._selected_block_id
        if workflow is None or block_id is None or not self._editable():
            return
        workflow_block = workflow.block(block_id)
        if not workflow_block.is_input:
            return
        data = self.combo_input_selection.itemData(index)
        if data == _INPUT_WHOLE_POOL:
            new_spec = InputSpec(whole_pool=True)
        elif isinstance(data, tuple) and data[0] == _INPUT_SELECTION:
            new_spec = InputSpec(selection_name=data[1])
        else:
            new_spec = InputSpec()
        if workflow_block.input == new_spec:
            return
        workflow = with_block_replaced(workflow, block_id, input=new_spec)
        self._save(workflow, keep_block_id=block_id)
