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
measurement itself, and its channels. Only the setup level is new -- the
channel rows carry exactly the payload they always did, which is why the drag
and drop into graphs, the multi-select behaviour and the unit-fix menu came
across unchanged.

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
from core.units import strip_channel_name_prefix
from core.models import is_time_response, resolve_channel_block_kind
from core.block_kinds import KIND_ORDER_CUT, KIND_TIME_RESPONSE
from io_modules.measurement_files import canonical_path
from view_models.data_pool import UNASSIGNED_SETUP, group_by_setup

# Marks a tree row as a setup heading. A 2-tuple on purpose: every consumer of
# a channel row's payload already tests for a tuple of at least three, so a
# heading can never be mistaken for something draggable.
SETUP_ROLE = "__setup__"

# A measurement the project still lists but that is not on disk any more.
MISSING_COLOR = "#c62828"
UNREADABLE_COLOR = "#9e9e9e"


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

    def _missing_paths(self) -> set:
        return getattr(self.explorer_parent, "missing_paths", set())

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
            user_data = item.data(0, Qt.ItemDataRole.UserRole)
            if not _is_channel_payload(user_data):
                continue
            if canonical_path(user_data[0].file_path) in missing:
                skipped += 1
                continue
            if resolve_channel_block_kind(user_data[1]) not in (KIND_TIME_RESPONSE, KIND_ORDER_CUT):
                unreadable += 1
                continue
            validated_channels_data.append(user_data)

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


def _is_channel_payload(user_data) -> bool:
    return bool(user_data) and isinstance(user_data, tuple) and len(user_data) >= 3


def _channel_payload(items, missing_paths=None) -> list:
    """
    The drag block for a set of tree rows; non-channel rows are skipped.

    Channels of a measurement that is no longer on disk are skipped too. The
    alternative is letting the drag land and fail on read, which reports a
    file-not-found from inside a plot instead of from the file that is
    actually gone -- and the tree has already said which one that is.
    """
    missing_paths = missing_paths or set()
    payload_list = []
    for item in items:
        user_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not _is_channel_payload(user_data):
            continue
        run_idx, ch_meta, _ = user_data
        if canonical_path(run_idx.file_path) in missing_paths:
            continue
        if resolve_channel_block_kind(ch_meta) is None:
            continue
        payload_list.append({
            "file_path": str(run_idx.file_path),
            "file_name": str(run_idx.file_name),
            "channel_index": int(ch_meta.index),
            "channel_name": str(ch_meta.name),
            "channel_type": str(ch_meta.type),
            "unit": str(ch_meta.unit),
            "block_kind": resolve_channel_block_kind(ch_meta),
            "func_type": ch_meta.func_type,
        })
    return payload_list


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

        # Measurements the pool holds that are no longer on disk. Worked out
        # once per rebuild and kept, because the drag and the double click
        # both have to consult it and neither is a good moment to stat several
        # hundred files.
        self.missing_paths: set = set()

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
        self.missing_paths = set()

        if not self.app_context.pool.has_data():
            return

        # One existence check per measurement, here, rather than per
        # interaction: a file that vanished has to be visible as such before
        # the user reaches for it, not only once they do.
        for run_index in self.app_context.pool.loaded_runs:
            if not os.path.isfile(run_index.file_path):
                self.missing_paths.add(canonical_path(run_index.file_path))

        by_path = self.app_context.project_session.sources_by_path()
        labels_in_order = self.app_context.project_session.project.setup_labels()
        grouped = group_by_setup(
            labels_in_order,
            self.app_context.pool.loaded_runs,
            by_path,
        )

        for setup_label, runs in grouped.items():
            setup_item = QTreeWidgetItem(self.tree)
            setup_item.setText(0, f"🧪 {setup_label}  ({len(runs)})")
            setup_item.setData(0, Qt.ItemDataRole.UserRole, (SETUP_ROLE, setup_label))
            if setup_label == UNASSIGNED_SETUP:
                setup_item.setForeground(0, QBrush(QColor("#808080")))
            if ("setup", setup_label) in expanded:
                setup_item.setExpanded(True)

            for run_index in runs:
                self._add_run_node(setup_item, run_index, setup_label, expanded)

        self._apply_visibility()

    # ---- searching and filtering --------------------------------------

    def _apply_search(self, _text: str = ""):
        """Slot for the search box; the text is read back in _apply_visibility."""
        self._apply_visibility()

    def _facet_filter(self):
        """
        What the Filter panel currently lets through, or None when it is not
        filtering the pool.

        Read here, on every rebuild, rather than pushed in when the user
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
            self.app_context.project_session.sources_by_path(),
            self.app_context.pool.schema().master,
            query.metadata_values,
            query.channel_identities,
            selected_ranges=query.ranges,
            selected_identity_values=query.identity_values,
        )

    def _apply_visibility(self):
        """
        Hides everything the search text and the filter panel do not reach.

        Rows are hidden rather than left out of the rebuild, because both are
        views of the pool and not changes to it -- clearing the box or the
        filter has to bring everything straight back, and the payload the
        graphs read must not depend on either.

        A measurement matches the search on its own name or on any of its
        channels, and a setup on any of its measurements: searching for a
        channel should find the measurement it is in, not an empty heading.
        The two narrow independently, so a row has to survive both.
        """
        needle = self.search_box.text().strip().lower()
        allowed = self._facet_filter()

        for i in range(self.tree.topLevelItemCount()):
            setup_item = self.tree.topLevelItem(i)
            setup_matches = not needle or needle in setup_item.text(0).lower()
            any_run_visible = False

            for j in range(setup_item.childCount()):
                run_item = setup_item.child(j)
                run_index = run_item.data(0, Qt.ItemDataRole.UserRole)
                allowed_labels = None if allowed is None else allowed.get(run_index.file_path)

                if allowed is not None and allowed_labels is None:
                    run_item.setHidden(True)
                    continue

                run_matches = setup_matches or needle in run_item.text(0).lower()
                any_channel_visible = False

                for k in range(run_item.childCount()):
                    channel_item = run_item.child(k)
                    passes_filter = (
                        allowed_labels is None
                        or channel_item.data(0, Qt.ItemDataRole.UserRole)[2] in allowed_labels
                    )
                    visible = passes_filter and (run_matches or needle in channel_item.text(0).lower())
                    channel_item.setHidden(not visible)
                    any_channel_visible = any_channel_visible or visible

                run_visible = any_channel_visible or (run_matches and not run_item.childCount())
                run_item.setHidden(not run_visible)
                any_run_visible = any_run_visible or run_visible

                # A hit on a channel is only useful if it can be seen.
                if (needle or allowed is not None) and any_channel_visible and not run_matches:
                    run_item.setExpanded(True)

            setup_item.setHidden(not any_run_visible)
            if (needle or allowed is not None) and any_run_visible and not setup_matches:
                setup_item.setExpanded(True)

    def _add_run_node(self, setup_item, run_index, setup_label, expanded):
        file_item = QTreeWidgetItem(setup_item)
        is_missing = canonical_path(run_index.file_path) in self.missing_paths

        file_item.setText(0, f"⚠ {run_index.file_name}" if is_missing else run_index.file_name)
        file_item.setData(0, Qt.ItemDataRole.UserRole, run_index)

        if is_missing:
            file_item.setForeground(0, QBrush(QColor(MISSING_COLOR)))
            font = file_item.font(0)
            font.setStrikeOut(True)
            file_item.setFont(0, font)
            file_item.setToolTip(
                0,
                f"Not found on disk:\n{run_index.file_path}\n\n"
                f"Right-click to locate it. Its metadata and results are still in the project.",
            )

        if (setup_label, run_index.file_name) in expanded:
            file_item.setExpanded(True)

        for unique_label, channel_meta in run_index.available_channels.items():
            channel_item = QTreeWidgetItem(file_item)

            icon_prefix = "📊"
            if channel_meta.type == "tacho":
                icon_prefix = "🔄"
            elif channel_meta.type == "voltage":
                icon_prefix = "⚡"
            elif channel_meta.type == "microphone":
                icon_prefix = "🔊"
            elif channel_meta.type == "general_dynamic":
                icon_prefix = "📐"

            display_name = strip_channel_name_prefix(channel_meta.name)
            display_unit = channel_meta.unit if channel_meta.unit else "unassigned"

            channel_item.setText(0, f"{icon_prefix} {display_name} [{display_unit}]")
            channel_item.setData(0, Qt.ItemDataRole.UserRole, (run_index, channel_meta, unique_label))

            # A non-time-response UNV dataset (func_type != 1) is listed so the
            # file's contents stay visible, but no reader can turn it into a
            # waveform -- mark it rather than let a drop fail from inside a plot.
            if resolve_channel_block_kind(channel_meta) == KIND_ORDER_CUT:
                channel_item.setToolTip(0, "Imported result. Drag or double-click to open in Order Tracking.")
            elif not is_time_response(channel_meta.func_type):
                channel_item.setFlags(channel_item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
                channel_item.setForeground(0, QBrush(QColor(UNREADABLE_COLOR)))
                channel_item.setToolTip(
                    0,
                    "Not a time-domain waveform (UNV func_type != 1, e.g. a spectrum "
                    "or cross-spectrum). Listed so you can see the file contains it, "
                    "but it cannot be dropped onto a plot.",
                )

    def _expanded_keys(self) -> set:
        """Which setups and measurements are currently open, by name."""
        keys = set()
        for i in range(self.tree.topLevelItemCount()):
            setup_item = self.tree.topLevelItem(i)
            data = setup_item.data(0, Qt.ItemDataRole.UserRole)
            label = data[1] if isinstance(data, tuple) and len(data) == 2 else setup_item.text(0)

            if setup_item.isExpanded():
                keys.add(("setup", label))
            for j in range(setup_item.childCount()):
                run_item = setup_item.child(j)
                if run_item.isExpanded():
                    # Key by the run's file_name, not the row text: a missing
                    # measurement's row carries a "⚠ " prefix that _add_run_node
                    # strips when it looks the key back up, so it never re-opened
                    # (finding 4.3).
                    run_data = run_item.data(0, Qt.ItemDataRole.UserRole)
                    name = run_data.file_name if run_data is not None else run_item.text(0)
                    keys.add((label, name))
        return keys

    # ---- context menu -------------------------------------------------

    def slot_show_context_menu(self, position: QPoint):
        selected_items = self.tree.selectedItems()
        channel_items = []
        run_items = []

        for item in selected_items:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if _is_channel_payload(data):
                channel_items.append(item)
            elif data is not None and not isinstance(data, tuple):
                run_items.append(item)

        if channel_items:
            self._show_channel_menu(position, channel_items)
        elif run_items:
            self._show_run_menu(position, run_items)

    def _show_channel_menu(self, position: QPoint, channel_items: list):
        menu = QMenu(self)

        if len(channel_items) > 1:
            # Pulled before menu.exec: a rebuild during the menu or the unit
            # dialog deletes these items, and execute_selected_fix_unit used to
            # read them back afterwards (finding 4.2).
            payloads = [item.data(0, Qt.ItemDataRole.UserRole) for item in channel_items]
            fix_selected_action = menu.addAction(f"🔧 Fix Unit for all {len(channel_items)} selected channels...")
            selected_action = menu.exec(self.tree.mapToGlobal(position))

            if selected_action == fix_selected_action:
                execute_selected_fix_unit(self.app_context, self, payloads)
            return

        target_item = channel_items[0]
        run_index, channel_meta, _ = target_item.data(0, Qt.ItemDataRole.UserRole)

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

    def _show_run_menu(self, position: QPoint, run_items: list):
        from gui.file_explorer.actions.assign_test_setup import execute_assign_test_setup
        from gui.file_explorer.actions.locate_missing_file import execute_locate_missing_file

        runs = [item.data(0, Qt.ItemDataRole.UserRole) for item in run_items]
        missing = [run for run in runs if canonical_path(run.file_path) in self.missing_paths]

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
