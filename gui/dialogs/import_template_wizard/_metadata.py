"""
The third step: which texts metadata is taken from, how each is split into pieces and which
field each piece fills. The pieces are redrawn from the wizard state at once: it reads only
the head of one sheet.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.import_template import PICK_HEADER
from io_modules.import_template import resolve_metadata_source_label
from orchestration.import_template import WizardJobs
from view_models.import_template import WizardPreview

from ._choices import PICK_SOURCE_LABELS, fill_combo, select_data

_KIND_LABELS = (
    ("", "Auto"),
    ("str", "Text"),
    ("int", "Integer"),
    ("float", "Number"),
    ("date", "Date"),
)
# The columns of the pieces table.
_PIECE_TEXT, _PIECE_FIELD, _PIECE_KEY, _PIECE_UNIT, _PIECE_KIND, _PIECE_FROM_END = range(1, 7)


class MetadataStep(QWidget):
    """The metadata sources and their pieces; every edit is handed to `jobs`, which says the template changed."""

    def __init__(self, jobs: WizardJobs, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self._filling_pieces = False
        columns = QHBoxLayout(self)
        left = QVBoxLayout()
        columns.addLayout(left, 1)
        left.addWidget(QLabel("Texts metadata is taken from"))
        self.metadata_source_list = QListWidget()
        self.metadata_source_list.currentRowChanged.connect(lambda *_: self._fill_pieces())
        left.addWidget(self.metadata_source_list, 1)
        add = QHBoxLayout()
        self.new_source = QComboBox()
        fill_combo(self.new_source, PICK_SOURCE_LABELS)
        self.new_source_row = QSpinBox()
        self.new_source_row.setRange(0, 50)
        self.new_source_row.setToolTip("Header row counted up from the heading row (0 = the heading row)")
        self.new_source.currentIndexChanged.connect(
            lambda *_: self.new_source_row.setEnabled(self.new_source.currentData() == PICK_HEADER))
        add_button = QPushButton("+ Add")
        add_button.clicked.connect(self.add_metadata_source)
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_metadata_source)
        for widget in (self.new_source, QLabel("row"), self.new_source_row, add_button, remove_button):
            add.addWidget(widget)
        left.addLayout(add)

        right = QVBoxLayout()
        columns.addLayout(right, 3)
        options = QFormLayout()
        self.delimiters = QLineEdit()
        self.delimiters.setToolTip("Every character here splits the text into pieces, e.g. _,:\\-")
        self.delimiters.editingFinished.connect(self._on_delimiters)
        options.addRow("Split at", self.delimiters)
        self.drop_unknown = QCheckBox("Drop the pieces no row below names (a text with more pieces still fits)")
        self.drop_unknown.toggled.connect(self._on_drop_unknown)
        options.addRow("", self.drop_unknown)
        right.addLayout(options)
        self.pieces = QTableWidget(0, 7)
        self.pieces.setHorizontalHeaderLabels(
            ["#", "Piece", "Field (blank = drop)", "Key = value", "Split unit", "Kind", "From the end"])
        self.pieces.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.pieces.horizontalHeader().setSectionResizeMode(_PIECE_FIELD, QHeaderView.ResizeMode.Stretch)
        self.pieces.verticalHeader().setVisible(False)
        self.pieces.itemChanged.connect(self._on_piece_item)
        right.addWidget(self.pieces, 1)
        right.addWidget(QLabel("Metadata of each resulting channel"))
        self.metadata_table = QTableWidget(0, 0)
        self.metadata_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.metadata_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self.metadata_table, 1)

    def show_template(self, template) -> None:
        """The template's metadata sources, the first selected; `jobs` holds the same template."""
        self._fill_metadata_sources(0)

    def collect(self) -> dict:
        """Nothing: every edit here goes to `jobs` at once."""
        return {}

    def _fill_metadata_sources(self, current: int) -> None:
        self.metadata_source_list.blockSignals(True)
        self.metadata_source_list.clear()
        for source in self.jobs.wizard.template.metadata:
            self.metadata_source_list.addItem(resolve_metadata_source_label(source).capitalize())
        self.metadata_source_list.setCurrentRow(min(current, self.metadata_source_list.count() - 1))
        self.metadata_source_list.blockSignals(False)
        self._fill_pieces()

    def _fill_pieces(self) -> None:
        """The selected source's options and its pieces in the sample, with their rules."""
        number = self.metadata_source_list.currentRow()
        wizard = self.jobs.wizard
        chosen = wizard is not None and 0 <= number < len(wizard.template.metadata)
        for widget in (self.delimiters, self.drop_unknown, self.pieces):
            widget.setEnabled(chosen)
        self._filling_pieces = True
        try:
            self.pieces.setRowCount(0)
            if not chosen:
                return
            source = wizard.template.metadata[number]
            self.delimiters.setText(source.delimiters)
            self.drop_unknown.blockSignals(True)
            self.drop_unknown.setChecked(source.drop_unknown)
            self.drop_unknown.blockSignals(False)
            shown = wizard.resolve_metadata_source(number)
            self.pieces.setRowCount(len(shown.pieces))
            for row, piece in enumerate(shown.pieces):
                for column, text in ((0, str(piece.position + 1)), (_PIECE_TEXT, piece.text)):
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.pieces.setItem(row, column, item)
                self.pieces.setItem(row, _PIECE_FIELD, QTableWidgetItem(piece.field))
                for column, on in ((_PIECE_KEY, bool(piece.key)), (_PIECE_UNIT, piece.split_unit),
                                   (_PIECE_FROM_END, piece.from_end)):
                    item = QTableWidgetItem()
                    item.setFlags((item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
                    item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                    self.pieces.setItem(row, column, item)
                kind = QComboBox()
                fill_combo(kind, _KIND_LABELS)
                select_data(kind, piece.kind)
                kind.currentIndexChanged.connect(lambda *_, at=row: self._apply_piece_later(at))
                self.pieces.setCellWidget(row, _PIECE_KIND, kind)
        finally:
            self._filling_pieces = False

    def add_metadata_source(self) -> None:
        source = self.new_source.currentData()
        row_above = self.new_source_row.value() if source == PICK_HEADER else 0
        number = self.jobs.add_metadata_source(source, row_above=row_above)
        if number >= 0:
            self._fill_metadata_sources(number)

    def _remove_metadata_source(self) -> None:
        number = self.metadata_source_list.currentRow()
        if self._chosen(number):
            self.jobs.remove_metadata_source(number)
            self._fill_metadata_sources(max(0, number - 1))

    def _on_delimiters(self) -> None:
        number = self.metadata_source_list.currentRow()
        if self._chosen(number) and self.delimiters.text() != self.jobs.wizard.template.metadata[number].delimiters:
            self.jobs.change_metadata_source(number, delimiters=self.delimiters.text())
            self._fill_metadata_sources(number)

    def _on_drop_unknown(self, checked: bool) -> None:
        number = self.metadata_source_list.currentRow()
        if self._chosen(number):
            self.jobs.change_metadata_source(number, drop_unknown=checked)
            self._fill_metadata_sources(number)

    def _chosen(self, number: int) -> bool:
        return self.jobs.wizard is not None and 0 <= number < len(self.jobs.wizard.template.metadata)

    def _on_piece_item(self, item: QTableWidgetItem) -> None:
        if not self._filling_pieces and item.column() != _PIECE_TEXT:
            self._apply_piece_later(item.row())

    def _apply_piece_later(self, row: int) -> None:
        # Applying redraws the table, which must not happen inside its own signal.
        QTimer.singleShot(0, lambda: self.apply_piece(row))

    def apply_piece(self, row: int) -> None:
        """Hands one row of the pieces table to `jobs`; a refused choice is said there and undone here."""
        number = self.metadata_source_list.currentRow()
        if self._filling_pieces or not self._chosen(number):
            return

        def checked(column: int) -> bool:
            return self.pieces.item(row, column).checkState() == Qt.CheckState.Checked

        kind = self.pieces.cellWidget(row, _PIECE_KIND)
        self.jobs.assign_piece(
            number, row, self.pieces.item(row, _PIECE_FIELD).text(), key_value=checked(_PIECE_KEY),
            split_unit=checked(_PIECE_UNIT), kind=kind.currentData() if kind else "",
            from_end=checked(_PIECE_FROM_END))
        self._fill_metadata_sources(number)

    def show_preview(self, preview: WizardPreview) -> None:
        """The metadata of each channel the preview read, one column per field."""
        labels = ["Sheet", "Channel"] + [f"{field.label} ({dict(_KIND_LABELS)[field.kind].lower()})"
                                         for field in preview.metadata_fields]
        self.metadata_table.clear()
        self.metadata_table.setColumnCount(len(labels))
        self.metadata_table.setHorizontalHeaderLabels(labels)
        self.metadata_table.setRowCount(len(preview.channels) if preview.metadata_fields else 0)
        if not preview.metadata_fields:
            return
        for row, channel in enumerate(preview.channels):
            for column, text in enumerate((channel.sheet, channel.name, *channel.metadata)):
                self.metadata_table.setItem(row, column, QTableWidgetItem(text))
