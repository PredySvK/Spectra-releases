"""Pairing tab of the metadata editor: two channel lists and the table of pairs (#511)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from selection.channel_pairing import (
    resolve_channel_pair_rejection, filter_channel_identities, resolve_channel_offer)
from selection.channel_identity import format_channel_identity

REMAINING_ONLY_KEY = "metadata_editor_pairing_remaining_only"
LINK_KEY = "metadata_editor_pairing_link"
_NOT_IN_POOL = "⚠ "


def _flag(settings, key: str, default: bool) -> bool:
    if settings is None:
        return default
    return settings.value(key, default, type=bool)


class ChannelPairingTab(QWidget):
    """Edits the channel pairs of channel_pairing.xlsx; `pairs` is the table as shown."""

    def __init__(self, measured, simulated, pairs, warnings, pairing_path="", settings=None,
                 parent=None):
        super().__init__(parent)
        self._measured = set(measured)
        self._simulated = set(simulated)
        self._settings = settings
        self.pairs = list(pairs)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        file_label = QLabel(f"Pairing file: {pairing_path}" if pairing_path else "Pairing file: -")
        file_label.setObjectName("PairingFileLabel")  # help figure target
        top.addWidget(file_label, 1)
        self.remaining_only = QCheckBox("Remaining only")
        self.remaining_only.setObjectName("PairingRemainingOnly")  # help figure target
        self.remaining_only.setChecked(_flag(settings, REMAINING_ONLY_KEY, True))
        top.addWidget(self.remaining_only)
        layout.addLayout(top)

        grid = QGridLayout()
        self.measured_search, self.measured_list = self._add_column(grid, "Measured", 0)
        self.simulated_search, self.simulated_list = self._add_column(grid, "Simulated", 2)
        for side, search, channels in (("Measured", self.measured_search, self.measured_list),
                                       ("Simulated", self.simulated_search, self.simulated_list)):
            search.setObjectName(f"Pairing{side}Search")  # help figure targets
            channels.setObjectName(f"Pairing{side}List")

        self.link = QCheckBox("Link")
        self.link.setObjectName("PairingLink")  # help figure target
        self.link.setToolTip("Search both lists with the left text")
        self.link.setChecked(_flag(settings, LINK_KEY, False))
        grid.addWidget(self.link, 1, 1, Qt.AlignmentFlag.AlignCenter)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(2, 1)
        layout.addLayout(grid, 1)

        self.pair_button = QPushButton("Pair ↓")
        self.pair_button.setObjectName("PairingPairButton")  # help figure target
        self.pair_button.setEnabled(False)
        layout.addWidget(self.pair_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.pairs_label = QLabel()
        layout.addWidget(self.pairs_label)
        self.pairs_table = QTableWidget(0, 2)
        self.pairs_table.setObjectName("PairingPairsTable")  # help figure target
        self.pairs_table.setHorizontalHeaderLabels(["Measured channel", "Simulated channel"])
        self.pairs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pairs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pairs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.pairs_table, 1)
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.setObjectName("PairingRemoveButton")  # help figure target
        layout.addWidget(self.remove_button, 0, Qt.AlignmentFlag.AlignRight)

        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        # Skipped rows stay in view until the dialog closes: they tell what to fix in the workbook.
        self.warnings_label = QLabel(
            f"! {len(warnings)} row(s) skipped: " + "; ".join(warnings) if warnings else "")
        self.warnings_label.setWordWrap(True)
        layout.addWidget(self.warnings_label)

        self.remaining_only.toggled.connect(self._on_remaining_only)
        self.link.toggled.connect(self._on_link)
        self.measured_search.textChanged.connect(self.refresh)
        self.simulated_search.textChanged.connect(self.refresh)
        for widget in (self.measured_list, self.simulated_list):
            widget.itemSelectionChanged.connect(self._update_pair_button)
        self.pair_button.clicked.connect(self.pair_selected)
        self.remove_button.clicked.connect(self.remove_selected)
        self.simulated_search.setEnabled(not self.link.isChecked())
        self.refresh()

    def show_message(self, text: str) -> None:
        self.message.setText(text)

    def _on_remaining_only(self, checked: bool) -> None:
        if self._settings is not None:
            self._settings.setValue(REMAINING_ONLY_KEY, checked)
        self.refresh()

    def _on_link(self, checked: bool) -> None:
        if self._settings is not None:
            self._settings.setValue(LINK_KEY, checked)
        self.simulated_search.setEnabled(not checked)
        self.refresh()

    def refresh(self, *_) -> None:
        measured, simulated = resolve_channel_offer(
            self._measured, self._simulated, self.pairs, self.remaining_only.isChecked())
        left_text = self.measured_search.text()
        right_text = left_text if self.link.isChecked() else self.simulated_search.text()
        self._fill(self.measured_list, filter_channel_identities(measured, left_text))
        self._fill(self.simulated_list, filter_channel_identities(simulated, right_text))
        known = self._measured | self._simulated
        self.pairs_label.setText(f"Pairs ({len(self.pairs)})")
        self.pairs_table.setRowCount(len(self.pairs))
        for row, pair in enumerate(self.pairs):
            for column, identity in enumerate(pair):
                mark = "" if identity in known else _NOT_IN_POOL
                item = QTableWidgetItem(mark + format_channel_identity(identity))
                self.pairs_table.setItem(row, column, item)
        self._update_pair_button()

    @staticmethod
    def _add_column(grid: QGridLayout, title: str, column: int):
        grid.addWidget(QLabel(title), 0, column)
        search = QLineEdit()
        search.setPlaceholderText("search")
        search.setClearButtonEnabled(True)
        grid.addWidget(search, 1, column)
        channels = QListWidget()
        channels.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        grid.addWidget(channels, 2, column)
        return search, channels

    @staticmethod
    def _fill(widget: QListWidget, identities) -> None:
        widget.blockSignals(True)
        widget.clear()
        for identity in identities:
            item = QListWidgetItem(format_channel_identity(identity))
            item.setData(Qt.ItemDataRole.UserRole, identity)
            widget.addItem(item)
        widget.blockSignals(False)

    def _update_pair_button(self) -> None:
        self.pair_button.setEnabled(
            bool(self.measured_list.selectedItems() and self.simulated_list.selectedItems()))

    def pair_selected(self) -> None:
        if not (self.measured_list.selectedItems() and self.simulated_list.selectedItems()):
            return
        pair = tuple(widget.selectedItems()[0].data(Qt.ItemDataRole.UserRole)
                     for widget in (self.measured_list, self.simulated_list))
        reason = resolve_channel_pair_rejection(pair, self.pairs)
        if reason:
            self.show_message(f"! Not paired: {reason}")
            return
        self.pairs.append(pair)
        self.show_message("")
        self.refresh()

    def remove_selected(self) -> None:
        rows = {index.row() for index in self.pairs_table.selectionModel().selectedRows()}
        self.pairs = [pair for row, pair in enumerate(self.pairs) if row not in rows]
        self.refresh()
