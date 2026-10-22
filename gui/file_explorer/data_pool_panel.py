# =====================================================================
# FILE: gui/file_explorer/data_pool_panel.py
# =====================================================================
"""
The Data Pool: the measurements this session is actually working with.

Browsing a disk and analysing data are two different activities, and mixing
them meant every folder the user opened replaced everything they had lined up.
The pool is the other half of that split (see file_browser.py for the first):
files are added to it deliberately, they stay until they are removed, and they
may come from several folders at once.

Three levels, top to bottom: the test setup a measurement belongs to, the
measurement itself, and its channels. What the rows are -- their text,
tooltip and marker -- is decided by the Qt-free Data Pool tree model
(view_models.data_pool, ADR §1.196); this panel only draws its nodes, and
every row carries the node it was drawn from.

All internal documentation strings and variable labels are standardly written
in English.
"""

import json
import os

from PySide6.QtCore import Qt, QMimeData, QPoint
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLineEdit,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.file_explorer.actions.edit_unit import (
    execute_fix_unit,
    execute_bulk_fix_unit,
    execute_selected_fix_unit,
)
from core.channel_drop import build_drop_descriptor
from io_modules.measurement_files import canonical_path
from view_models.data_pool import (
    MARKER_MISSING,
    MARKER_UNASSIGNED,
    MARKER_UNREADABLE,
    NODE_CHANNEL,
    NODE_MEASUREMENT,
    NODE_UNREADABLE_FILE,
    PoolTree,
    PoolTreeNode,
    build_pool_tree,
    resolve_pool_tree_visibility,
)
from gui.appearance import APP_TOKENS


class ProtectedTreeWidget(QTreeWidget):
    """
    The pool's QTreeWidget: drags channel rows out to the graphs, takes file
    drops in from the OS, and lets a double click open a whole multi-selection.
    """

    def __init__(self, app_context, explorer_parent, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.explorer_parent = explorer_parent

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        # Drops are accepted only from outside the application -- files thrown
        # in from Windows Explorer. Rows dragged out of this tree are still
        # meant for the graphs, so an internal drag is refused below rather
        # than turning the tree into a place you can rearrange.
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(False)

        self._multi_selection_cache = []

    def mimeTypes(self):
        return ["application/x-nvh-channels"]

    # ---- drops from outside the application ---------------------------

    def _dropped_paths(self, mime_data) -> list:
        """
        Local files and folders in a drop from the OS, or [] for anything else.

        Only local paths: a URL dragged out of a browser also arrives as a
        text/uri-list, and toLocalFile() gives an empty string for it rather
        than something that could be mistaken for a folder.
        """
        if not mime_data.hasUrls():
            return []
        paths = [url.toLocalFile() for url in mime_data.urls()]
        return [path for path in paths if path and os.path.exists(path)]

    def dragEnterEvent(self, event):
        if self._dropped_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if self._dropped_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        paths = self._dropped_paths(event.mimeData())
        if not paths:
            event.ignore()
            return

        event.acceptProposedAction()

        self.explorer_parent.data_pool.add_paths(paths)

    def _missing_paths(self) -> frozenset:
        return self.app_context.pool.missing_paths

    def mimeData(self, items):
        """The drag payload for the selected rows; Qt calls this to start every drag."""
        mime_data = QMimeData()
        payload_list = _channel_payload(items, self._missing_paths())
        if payload_list:
            mime_data.setData("application/x-nvh-channels", json.dumps(payload_list).encode("utf-8"))
        return mime_data

    def mousePressEvent(self, event):
        # Qt itself keeps a multi-selection alive while a press on one of its
        # rows turns into a drag (it collapses the selection only on release),
        # so the drag needs nothing from us. What Qt does not keep is the set
        # for a double click: its first click collapses the selection to one
        # row. Remember the set here; every press still goes to Qt, because a
        # press Qt never sees leaves it with a stale pressed row and position,
        # which made the next move start a second drag and wedged the view in
        # drag-selecting until some unrelated click reset it.
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            selected = self.selectedItems()
            if item and item in selected and len(selected) > 1:
                self._multi_selection_cache = selected
            else:
                # The selection is moving on. Drop the cache so a later double
                # click cannot open a stale set -- or touch rows a pool
                # rebuild deleted meanwhile.
                self._multi_selection_cache = []
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Retrieve the safely preserved selection list, dropping any rows a
        # tree rebuild deleted since the cache was taken (see _live_items).
        cached = _live_items(self._multi_selection_cache)
        items_to_process = cached if len(cached) > 1 else self.selectedItems()

        missing = self._missing_paths()
        validated_channels_data = []
        skipped = 0
        unreadable = 0
        for item in items_to_process:
            node = _node(item)
            if node.kind != NODE_CHANNEL:
                continue
            if canonical_path(node.run.file_path) in missing:
                skipped += 1
                continue
            if node.marker == MARKER_UNREADABLE:
                unreadable += 1
                continue
            validated_channels_data.append(_channel_triple(node))

        if skipped:
            self.app_context.log(
                f"WARNING: {skipped} channel(s) skipped -- their measurement file is "
                f"no longer on disk. Use 'Locate missing file…' to re-point it."
            )

        if unreadable:
            self.app_context.log(
                f"WARNING: {unreadable} channel(s) skipped -- not a time-domain "
                "waveform (UNV func_type != 1). This tool only analyses time responses."
            )

        if not validated_channels_data:
            super().mouseDoubleClickEvent(event)
            return

        # Same call a drop on the Home Workspace makes.
        self.explorer_parent.workspace.open_channels_tab(validated_channels_data)
        event.accept()

        self._multi_selection_cache = []


def _node(item) -> PoolTreeNode:
    """The Data Pool tree node a row was drawn from; every row carries one."""
    return item.data(0, Qt.ItemDataRole.UserRole)


def _channel_triple(node) -> tuple:
    """(run, channel metadata, unique label): what tabs and the unit-fix actions take."""
    return node.run, node.channel, node.unique_label


def _channel_payload(items, missing_paths=None) -> list:
    """
    The drop descriptors of a set of tree rows; non-channel rows are skipped.

    Channels of a measurement that is no longer on disk are skipped too. The
    alternative is letting the drag land and fail on read, which reports a
    file-not-found from inside a plot instead of from the file that is
    actually gone -- and the tree has already said which one that is.
    """
    missing_paths = missing_paths or set()
    payload_list = []
    for item in items:
        node = _node(item)
        if node.kind != NODE_CHANNEL:
            continue
        if canonical_path(node.run.file_path) in missing_paths:
            continue
        if node.marker == MARKER_UNREADABLE:
            continue
        payload_list.append(build_drop_descriptor(node.run, node.channel))
    return payload_list


def _add_row(parent, node, expanded: set):
    """Draws `node` and its children under `parent`, re-opening the open ones by key."""
    item = QTreeWidgetItem(parent)
    item.setText(0, node.text)
    item.setData(0, Qt.ItemDataRole.UserRole, node)
    if node.tooltip:
        item.setToolTip(0, node.tooltip)
    _style_row(item, node)
    for child in node.children:
        _add_row(item, child, expanded)
    if node.key in expanded:
        item.setExpanded(True)


def _style_row(item, node):
    """A marker kind as colour, strike-out and disabled dragging or selection."""
    if node.marker == MARKER_MISSING:
        item.setForeground(0, QBrush(QColor(APP_TOKENS.item_missing)))
        font = item.font(0)
        font.setStrikeOut(True)
        item.setFont(0, font)
    elif node.marker == MARKER_UNASSIGNED:
        item.setForeground(0, QBrush(QColor(APP_TOKENS.text_muted)))
    elif node.marker == MARKER_UNREADABLE:
        item.setForeground(0, QBrush(QColor(APP_TOKENS.item_unreadable)))
        if node.kind == NODE_UNREADABLE_FILE:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsSelectable)
        elif node.kind == NODE_CHANNEL:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)


def _live_items(items) -> list:
    """
    The subset of `items` whose underlying C++ QTreeWidgetItem is still alive.

    _multi_selection_cache holds item references that a tree rebuild (a pool
    rescan clears and repopulates the whole tree) can delete underneath us.
    Touching a deleted item raises RuntimeError rather than returning None, so
    the check has to be a probe, not a truthiness test.
    """
    live = []
    for item in items:
        try:
            item.data(0, Qt.ItemDataRole.UserRole)
        except RuntimeError:
            continue
        live.append(item)
    return live


class DataPoolPanel(QWidget):
    """
    The pool's tree, and everything the user can do to it from a right click.

    Holds the same public surface the old single-folder explorer did --
    `tree` and `rebuild_tree_view()` -- because the unit-fix actions, the
    metadata editor and the synthetic-signal generator all reach for those by
    name after they change something.
    """

    def __init__(self, app_context, filter_panel, data_pool, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.filter_panel = filter_panel
        self.data_pool = data_pool
        # Set by the composition root once Workspace exists -- a double
        # click here opens a tab, and this panel is built well before the thing
        # that owns tabs (#241).
        self.workspace = None
        # The tree last drawn; search and Filter changes resolve against it.
        self._pool_tree = PoolTree()

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("Search setups, measurements, channels…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_search)
        layout.addWidget(self.search_box)

        self.tree = ProtectedTreeWidget(app_context=self.app_context, explorer_parent=self)
        self.tree.setHeaderLabels(["Test Setup / Measurement / Channels"])
        self.tree.setAnimated(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.slot_show_context_menu)

        layout.addWidget(self.tree)

    # ---- building -----------------------------------------------------

    def rebuild_tree_view(self):
        """
        Redraws the whole tree from the pool.

        Rebuilt wholesale rather than patched, for the same reason the filter
        panel is: every path that changes the pool -- a folder added, a unit
        corrected, a setup assigned -- would otherwise need its own incremental
        update, and one of them would eventually be missed. What is preserved
        by hand is which nodes were open, because that is the user's place in
        the tree and losing it on every refresh is maddening.
        """
        expanded = self._expanded_keys()
        self.tree.clear()
        self._pool_tree = PoolTree()

        pool = self.app_context.pool
        unreadable_folders = [(directory, pool.unreadable_in(directory))
                              for directory in pool.pool_directories if pool.unreadable_in(directory)]
        if not pool.has_data() and not unreadable_folders:
            return

        session = self.app_context.project_session
        self._pool_tree = pool_tree = build_pool_tree(
            setup_labels=session.project.setup_labels(),
            runs=pool.loaded_runs,
            entries_by_path=session.source_location.entries_by_path,
            unreadable_by_folder=unreadable_folders,
            # The pool remembers which are missing; its background check is the
            # only thing that asks the disk.
            missing_paths=pool.missing_paths,
        )
        for node in pool_tree.roots:
            _add_row(self.tree, node, expanded)

        self.apply_visibility()

    # ---- searching and filtering --------------------------------------

    def _apply_search(self, _text: str = ""):
        """Slot for the search box; the text is read back in apply_visibility."""
        self.apply_visibility()

    def _facet_filter(self):
        """
        What the Filter panel currently lets through, or None when it is not
        filtering the pool.

        Read here, on every visibility pass, rather than pushed in when the user
        touches a checkbox: a folder added while the filter is on has to come
        in already filtered, and pulling the state at draw time is the only
        version of that which cannot be forgotten at one of the call sites.
        """
        panel = self.filter_panel
        if panel is None or not panel.filters_data_pool() or panel.showing_all():
            return None

        from selection.source_facets import visible_pool_channels

        query = panel.pool_query()
        return visible_pool_channels(
            self.app_context.pool.loaded_runs,
            self.app_context.project_session.source_location.entries_by_path,
            self.app_context.pool.schema().master,
            query.metadata_values,
            query.channel_identities,
            selected_ranges=query.ranges,
            selected_identity_values=query.identity_values,
        )

    def apply_visibility(self):
        """
        Hides the rows the search text and the Filter panel do not reach, and
        opens the ones a hit is hidden inside, without rebuilding the tree.

        What to hide is the model's decision (resolve_pool_tree_visibility);
        rows are hidden rather than left out of the rebuild, because both are
        views of the pool and not changes to it -- clearing the box or the
        filter has to bring everything straight back, and the payload the
        graphs read must not depend on either.
        """
        visibility = resolve_pool_tree_visibility(
            self._pool_tree, self.search_box.text(), self._facet_filter())
        for item in self._rows():
            key = _node(item).key
            item.setHidden(key in visibility.hidden)
            if key in visibility.expanded:
                item.setExpanded(True)

    def _rows(self):
        """Every row of the tree, parents before their children."""
        pending = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while pending:
            item = pending.pop()
            yield item
            pending.extend(item.child(j) for j in range(item.childCount()))

    def _expanded_keys(self) -> set:
        """The expansion keys of the nodes currently open."""
        return {_node(item).key for item in self._rows() if item.isExpanded()}

    # ---- context menu -------------------------------------------------

    def slot_show_context_menu(self, position: QPoint):
        # Nodes, not items: a rebuild during the menu or a dialog deletes the
        # items, and the actions used to read them back afterwards (finding 4.2).
        selected = [_node(item) for item in self.tree.selectedItems()]
        channels = [node for node in selected if node.kind == NODE_CHANNEL]
        measurements = [node for node in selected if node.kind == NODE_MEASUREMENT]

        if channels:
            self._show_channel_menu(position, channels)
        elif measurements:
            self._show_run_menu(position, [node.run for node in measurements])

    def _show_channel_menu(self, position: QPoint, channels: list):
        menu = QMenu(self)

        if len(channels) > 1:
            payloads = [_channel_triple(node) for node in channels]
            fix_selected_action = menu.addAction(f"🔧 Fix Unit for all {len(channels)} selected channels...")
            selected_action = menu.exec(self.tree.mapToGlobal(position))

            if selected_action == fix_selected_action:
                execute_selected_fix_unit(self.app_context, self, payloads)
            return

        run_index, channel_meta = channels[0].run, channels[0].channel

        fix_action = menu.addAction("🔧 Fix Unit (This Channel Only)...")
        bulk_label = f"📦 Fix Unit for all {channel_meta.type}s in this file..."
        bulk_action = menu.addAction(bulk_label)

        selected_action = menu.exec(self.tree.mapToGlobal(position))

        if not selected_action:
            return

        if selected_action == fix_action:
            execute_fix_unit(self.app_context, self, run_index, channel_meta)
        elif selected_action == bulk_action:
            execute_bulk_fix_unit(self.app_context, self, run_index, channel_meta.type, channel_meta.unit)

    def _show_run_menu(self, position: QPoint, runs: list):
        from gui.file_explorer.actions.assign_test_setup import execute_assign_test_setup
        from gui.file_explorer.actions.locate_missing_file import execute_locate_missing_file

        missing = [run for run in runs if self.app_context.pool.is_missing(run.file_path)]

        menu = QMenu(self)
        locate_action = None
        if len(missing) == 1:
            locate_action = menu.addAction(f"🔍 Locate '{missing[0].file_name}'...")
            menu.addSeparator()

        assign_action = menu.addAction(f"🧪 Assign {len(runs)} measurement(s) to Test Setup...")
        menu.addSeparator()

        reveal_action = None
        if len(runs) == 1 and os.path.exists(runs[0].file_path):
            reveal_action = menu.addAction("📂 Show in File Explorer")
        copy_path_action = menu.addAction(
            "📋 Copy path" if len(runs) == 1 else f"📋 Copy {len(runs)} paths"
        )
        menu.addSeparator()
        remove_action = menu.addAction(f"🗑 Remove {len(runs)} measurement(s) from Data Pool")

        selected_action = menu.exec(self.tree.mapToGlobal(position))
        if locate_action is not None and selected_action == locate_action:
            execute_locate_missing_file(self.app_context, self, missing[0], self.data_pool)
        elif selected_action == assign_action:
            execute_assign_test_setup(self.app_context, self, [run.file_path for run in runs])
        elif reveal_action is not None and selected_action == reveal_action:
            from gui.file_explorer.reveal import show_in_file_manager
            show_in_file_manager(runs[0].file_path)
        elif selected_action == copy_path_action:
            from gui.file_explorer.reveal import copy_paths_to_clipboard
            copy_paths_to_clipboard([run.file_path for run in runs])
        elif selected_action == remove_action:
            self.data_pool.remove_measurements([run.file_path for run in runs])
