"""
The preview under the steps: the sample as a grid with header, data and ignored cells
coloured, and the channels the template reads from it.
"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QSplitter, QTableView, QTableWidget, QTableWidgetItem

from gui.appearance import APP_TOKENS
from view_models.import_template import CELL_DATA, CELL_HEADER, WizardPreview

from ._choices import AMPLITUDE_LABELS


class _SampleGridModel(QAbstractTableModel):
    """The shown sheet's cells, coloured by the role the template gives them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cells = ()
        self._roles = ()
        self._header = QColor(APP_TOKENS.action_primary)
        self._header.setAlpha(110)
        self._data = QColor(APP_TOKENS.cursor_accent)
        self._data.setAlpha(80)
        self._ignored = QColor(APP_TOKENS.text_muted)

    def show(self, preview: WizardPreview) -> None:
        self.beginResetModel()
        self._cells, self._roles = preview.cells, preview.roles
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._cells)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() or not self._cells else len(self._cells[0])

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        cell_role = self._roles[index.row()][index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return self._cells[index.row()][index.column()]
        if role == Qt.ItemDataRole.BackgroundRole:
            return {CELL_HEADER: self._header, CELL_DATA: self._data}.get(cell_role)
        if role == Qt.ItemDataRole.ForegroundRole and cell_role not in (CELL_HEADER, CELL_DATA):
            return self._ignored
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        letters, number = "", section + 1
        while number:
            number, rest = divmod(number - 1, 26)
            letters = chr(ord("A") + rest) + letters
        return letters


class PreviewPane(QSplitter):
    """The sample grid next to the channels table; `show_preview` draws a computed preview."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.grid_model = _SampleGridModel(self)
        self.grid = QTableView()
        self.grid.setModel(self.grid_model)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.grid.horizontalHeader().setDefaultSectionSize(110)
        self.addWidget(self.grid)
        self.channels = QTableWidget(0, 6)
        self.channels.setHorizontalHeaderLabels(["Sheet", "Channel", "Order", "Unit", "Amplitude", "Points"])
        self.channels.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.channels.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.addWidget(self.channels)
        self.setSizes([700, 400])

    def show_preview(self, preview: WizardPreview) -> None:
        self.grid_model.show(preview)
        self.channels.setRowCount(len(preview.channels))
        for row, channel in enumerate(preview.channels):
            order = "" if channel.order is None else f"{channel.order:g}"
            amplitude = dict(AMPLITUDE_LABELS).get(channel.source_amplitude, channel.source_amplitude)
            points = f"{channel.points}" + (f" ({channel.lost_rows} lost)" if channel.lost_rows else "")
            for column, text in enumerate((channel.sheet, channel.name, order, channel.unit, amplitude, points)):
                item = QTableWidgetItem(text)
                if channel.problem:
                    item.setToolTip(channel.problem)
                    item.setForeground(QColor(APP_TOKENS.text_muted))
                self.channels.setItem(row, column, item)
