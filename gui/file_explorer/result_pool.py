# =====================================================================
# FILE: gui/file_explorer/result_pool.py
# =====================================================================
"""
The Result Pool: every computed h5 result set in the project, with a checkbox
per set whose state belongs to the focused graph.

It sits in the Explorer next to the File Browser and the Data Pool because it
does the same job those two do -- it is a browser of project content the user
picks from to fill a workspace. (The Block Pool lives in gui/workspace/ instead
because it belongs to the workflow editor, not to data.)

This panel holds no per-dock state of its own. Membership already lives on the
dock (dock.curves.loaded_result_set_ids, persisted via TabSpec); a second dict
here keyed by dock_id would drift the moment content changed
by any path other than this panel. set_current_dock() reads the dock's own set
and repaints the checkboxes from it.

Checking a box loads that set onto the focused graph
(ResultContentHandler.load_into_dock), unchecking it
removes it again (unload_result_sets_from_dock) -- the panel calls the actions
directly, the same way the Data Pool panel calls `DataPoolHandler.add_paths`,
rather than routing through a signal. The focused dock is pulled at draw time
(showEvent / set_current_dock), never cached, for the same reason the panel
holds no per-dock check state.

All internal documentation strings and variable labels are standardly written
in English.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from gui.handlers.result_content import unload_result_sets_from_dock
from selection.trace_filter import format_result_kind
from selection.parameter_sets import build_parameter_sets
from io_modules.project_store import project_folder

# A result set the project still lists but whose h5 file is gone from disk.
GHOST_COLOR = "#9e9e9e"

# Marks a top-level row as a Result Kind heading rather than a set. A 2-tuple,
# so a set row's plain string id can never be mistaken for one.
_KIND_ROLE = "__result_kind__"


class ResultPoolPanel(QWidget):
    def __init__(self, app_context, focused_dock, parent=None, *,
                 result_content_handler=None,
                 # FilterRoutingHandler.refresh_and_apply_for_focused_dock,
                 # handed down by the composition root as a zero-argument
                 # callable: the handler needs the explorer panel this widget
                 # lives in, so it cannot exist yet when this is built (#234).
                 # None in a window that has no Filter panel, and in tests.
                 refresh_and_apply_for_focused_dock=None):
        super().__init__(parent)
        self.app_context = app_context
        # Which graph the checkboxes act on, as a zero-argument callable bound
        # to the workspace tab widget by the composition root (#241). The same
        # shape ResultContentHandler already gets its dock lookup in (§1.75):
        # the tab widget exists long before this panel, Workspace does
        # not. None in a window with no workspace, and in tests.
        self._focused_dock = focused_dock
        self.result_content_handler = result_content_handler
        self._refresh_and_apply_for_focused_dock = refresh_and_apply_for_focused_dock

        self._current_dock = None
        # Result sets whose h5 file was missing at the last rebuild. Worked out
        # once per rebuild and kept, so _apply_check_states does not re-stat.
        self._missing_ids: set = set()
        self._suppress_item_changed = False

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.header = QLabel(self)
        self.header.setWordWrap(True)
        layout.addWidget(self.header)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Result Kind / Result Set"])
        self.tree.setAnimated(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.tree)

        self.rebuild()

    # ---- public API --------------------------------------------------

    def rebuild(self):
        """
        Redraws the whole tree from `project.result_sets`.

        Rebuilt wholesale rather than patched, for the same reason the Data
        Pool tree is: every path that changes the set list would otherwise
        need its own incremental update. Which Result Kind rows were open is
        preserved by hand.
        """
        expanded = self._expanded_kinds()

        self._suppress_item_changed = True
        self.tree.clear()
        self._missing_ids = set()

        session = getattr(self.app_context, "project_session", None)
        project = getattr(session, "project", None) if session is not None else None
        result_sets = list(project.result_sets) if project is not None else []

        # One existence probe per set per rebuild, synchronous. Same rationale
        # as DataPoolPanel.rebuild_tree_view's per-measurement stat: a file
        # that vanished must read as gone before the user reaches for it, and
        # this is tens of sets, not the hundreds of measurements that scan is.
        folder = project_folder(session.path) if session is not None and session.path else None
        if folder is not None:
            for ref in result_sets:
                if not os.path.exists(os.path.join(folder, ref.file)):
                    self._missing_ids.add(ref.id)

        ps_index_by_ref = {}
        for ps in build_parameter_sets(project, [r.id for r in result_sets]) if project else []:
            for rid in ps.result_set_ids:
                ps_index_by_ref[rid] = ps.index

        by_kind: dict = {}
        for ref in result_sets:
            by_kind.setdefault(ref.kind, []).append(ref)

        for kind, refs in by_kind.items():
            kind_item = QTreeWidgetItem(self.tree)
            kind_item.setText(0, f"{format_result_kind(kind)}  ({len(refs)})")
            kind_item.setData(0, Qt.ItemDataRole.UserRole, (_KIND_ROLE, kind))
            kind_item.setFlags(
                kind_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            kind_item.setCheckState(0, Qt.CheckState.Unchecked)

            for ref in refs:
                child = QTreeWidgetItem(kind_item)
                ps_index = ps_index_by_ref.get(ref.id)
                ps_label = f"Parameter Set {ps_index}" if ps_index else "Parameter Set —"
                label = f"{ref.label}  ·  {ps_label}  ·  {len(ref.source_ids)} source(s)"
                child.setData(0, Qt.ItemDataRole.UserRole, ref.id)

                if ref.id in self._missing_ids:
                    child.setText(0, f"⚠ {label}")
                    child.setForeground(0, QBrush(QColor(GHOST_COLOR)))
                    child.setFlags(child.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                    child.setToolTip(
                        0,
                        "This result set's h5 file is missing on disk. Recompute the "
                        "set to load it again.",
                    )
                else:
                    child.setText(0, label)
                    child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)

            if kind in expanded:
                kind_item.setExpanded(True)

        self._suppress_item_changed = False
        self._apply_check_states()
        self._update_header()

    def set_current_dock(self, dock):
        """Repaint the checkboxes from `dock`'s own loaded set. The panel keeps
        no state -- this is the whole of 'which sets are in this graph'."""
        self._current_dock = dock
        self._apply_check_states()
        self._update_header()

    # ---- Qt ----------------------------------------------------------

    def showEvent(self, event):
        """Rebuild whenever the tab becomes visible.

        Pulling the set list and the focused dock at draw time is the one
        version that cannot be forgotten on some caller -- switching to this
        tab is exactly when a set may have been computed, or the focused graph
        changed, while the panel was hidden and not being told.
        """
        super().showEvent(event)
        self._current_dock = self._focused_graph_dock()
        self.rebuild()

    # ---- internals --------------------------------------------------

    def _focused_graph_dock(self):
        return self._focused_dock() if self._focused_dock is not None else None

    def _toggle_sets(self, ref_ids: list[str], checked: bool) -> None:
        """Load or unload a batch of result sets on the focused graph."""
        from gui.workspace.graph_dock import GraphDock

        dock = self._current_dock
        if not isinstance(dock, GraphDock):
            return

        valid_ids = [rid for rid in ref_ids if rid not in self._missing_ids]
        if not valid_ids:
            self._apply_check_states()
            return

        if checked:
            if self.result_content_handler is not None:
                self.result_content_handler.load_into_dock(dock, valid_ids)
        else:
            unload_result_sets_from_dock(dock, valid_ids)
        # The graph's result sets are part of what a Save writes for it.
        session = getattr(self.app_context, "project_session", None)
        if session is not None:
            session.mark_dirty()

        self._apply_check_states()

        # The dock's content is the source of the Local filter facets
        # (facets_from_traces), so a load/unload has to rebuild what the Filter
        # panel offers -- otherwise the new curve is drawn but invisible to the
        # panel until the tab is switched.
        if self._refresh_and_apply_for_focused_dock is not None:
            self._refresh_and_apply_for_focused_dock()

    def _apply_check_states(self):
        from gui.workspace.graph_dock import GraphDock

        dock = self._current_dock
        is_graph = isinstance(dock, GraphDock)
        # Pending ids (a read queued behind Calculate & Save, or another
        # checked set) count as checked too -- otherwise switching tabs away
        # and back unticks a set that is still on its way in (#371).
        loaded = set(dock.curves.loaded_or_pending_result_set_ids) if is_graph else set()

        self._suppress_item_changed = True
        for i in range(self.tree.topLevelItemCount()):
            kind_item = self.tree.topLevelItem(i)
            readable_count = 0
            checked_count = 0
            for j in range(kind_item.childCount()):
                child = kind_item.child(j)
                ref_id = child.data(0, Qt.ItemDataRole.UserRole)
                if ref_id in self._missing_ids:
                    child.setCheckState(0, Qt.CheckState.Unchecked)
                    continue
                is_checked = ref_id in loaded
                child.setCheckState(
                    0,
                    Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked,
                )
                readable_count += 1
                if is_checked:
                    checked_count += 1

            if readable_count == 0 or checked_count == 0:
                kind_item.setCheckState(0, Qt.CheckState.Unchecked)
            elif checked_count == readable_count:
                kind_item.setCheckState(0, Qt.CheckState.Checked)
            else:
                kind_item.setCheckState(0, Qt.CheckState.PartiallyChecked)
        self._suppress_item_changed = False

        # Never silently empty (ADR §1.25): when the focused widget is not a
        # graph (a spectrogram, the startup placeholder) the tree still shows
        # the sets, but disabled, and the header says why.
        self.tree.setEnabled(is_graph)

    def _update_header(self):
        from gui.workspace.graph_dock import GraphDock

        dock = self._current_dock
        if isinstance(dock, GraphDock):
            model = dock.curves.model
            view = getattr(model, "view", None) if model is not None else None
            title = getattr(view, "title", None) or getattr(dock, "dock_id", "graph")
            self.header.setText(f"Checked sets load into: {title}")
        else:
            self.header.setText("Focus a graph tab to choose its result sets.")

    def _on_item_changed(self, item, column):
        if self._suppress_item_changed or column != 0:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        # A Result Kind heading carries a 2-tuple, not an id. Checking or unchecking
        # a heading loads or unloads all of its readable sets in a single call (#389).
        if isinstance(data, tuple) and len(data) == 2 and data[0] == _KIND_ROLE:
            checked = item.checkState(0) == Qt.CheckState.Checked
            ref_ids = [
                item.child(j).data(0, Qt.ItemDataRole.UserRole)
                for j in range(item.childCount())
                if isinstance(item.child(j).data(0, Qt.ItemDataRole.UserRole), str)
            ]
            self._toggle_sets(ref_ids, checked)
            return

        if not isinstance(data, str):
            return
        ref_id = data
        if ref_id in self._missing_ids:
            self._apply_check_states()
            return
        self._toggle_sets([ref_id], item.checkState(0) == Qt.CheckState.Checked)

    def _expanded_kinds(self) -> set:
        keys = set()
        for i in range(self.tree.topLevelItemCount()):
            kind_item = self.tree.topLevelItem(i)
            data = kind_item.data(0, Qt.ItemDataRole.UserRole)
            if kind_item.isExpanded() and isinstance(data, tuple) and len(data) == 2:
                keys.add(data[1])
        return keys
