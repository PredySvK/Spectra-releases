"""
The wizard's preview at the bottom of steps 2-4: a tab for every file and
sheet of the samples (a skipped one red, with its reason), the shown sheet as a
grid and a legend. On step 2 the header rows, the heading row and the X columns
are tinted and a click on a row number offers "heading row" or "first data
row"; on the later steps only the selected channel's columns are marked. On
step 3 the chips with a role are marked inside the header cells and in the
sheet / file / folder texts above the grid, and a click on one of those texts
is `text_clicked` (an X/Y pair's header cells span both its columns). The
tints are laid over the theme, so the text stays readable on a dark theme too.
"""

from typing import Callable, Dict, Optional, Tuple

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMenu, QStyle, QStyledItemDelegate, QTabBar, QTableView, QVBoxLayout, QWidget,
)

from core.import_template import SOURCE_FILE_NAME, SOURCE_FOLDER, SOURCE_HEADER, SOURCE_SHEET, ChipRef
from view_models.import_template import (
    CHIP_ROLE_KINDS, SampleChips, SamplePreview, SampleRoles, SampleSheet, resolve_chip_kinds, resolve_chip_marks,
)

from ._role_chips import ROLE_LABELS, RoleTextButton, paint_role_chips, resolve_shifted_marks, role_tint_over_base

# Readable on a light and on a dark theme.
RED = "#e5534b"
_HEADER_TINT = (251, 188, 4, 32)
_HEADING_TINT = (79, 142, 247, 64)
_X_TINT = (63, 179, 122, 34)

MODE_TABLE = "table"        # step 2: header, heading row and X columns tinted; row numbers clickable
MODE_CHANNELS = "channels"  # step 4: the selected channel's columns marked
MODE_ROLES = "roles"        # step 3: the chips with a role marked, the texts clickable

# The marks (start, end, role kinds) of a header cell, for the delegate.
MARKS_ROLE = Qt.ItemDataRole.UserRole + 1
_OUTER_TEXTS = ((SOURCE_SHEET, "Sheet"), (SOURCE_FILE_NAME, "File"), (SOURCE_FOLDER, "Folder"))
# What the grid needs to know of a header cell on step 3: (channel, source key, marks, tooltip).
RoleCell = Tuple[int, Tuple[str, int], tuple, str]

# A sheet tab, and a channel on it: (path, sheet) and (x column, amplitude column).
SheetKey = Tuple[str, str]


def muted_color() -> QColor:
    """The theme's dimmed text colour (a light or a dark theme alike)."""
    return QApplication.palette().color(QPalette.ColorRole.PlaceholderText)


def over_base(tint: Tuple[int, int, int, int]) -> str:
    """A tint laid over the theme's base, as an opaque colour for rich text, which knows no alpha."""
    base = QApplication.palette().color(QPalette.ColorRole.Base)
    red, green, blue, alpha = tint
    share = alpha / 255
    return QColor(*(round(own * share + under * (1 - share))
                    for own, under in ((red, base.red()), (green, base.green()), (blue, base.blue())))).name()


def _column_letters(section: int) -> str:
    letters, number = "", section + 1
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return letters


class SampleGridModel(QAbstractTableModel):
    """One sheet of the samples, coloured as the mode says."""

    def __init__(self, mode: str = MODE_TABLE):
        super().__init__()
        self.mode = mode
        self.sheet: Optional[SampleSheet] = None
        self.selected_columns: Tuple[int, ...] = ()
        self._width = 0
        self.role_cells: Dict[Tuple[int, int], RoleCell] = {}
        self.channel_at: Dict[int, int] = {}        # step 3: a data column -> its channel

    def show_sheet(self, sheet: Optional[SampleSheet], selected_columns: Tuple[int, ...] = (),
                   role_cells: Optional[Dict[Tuple[int, int], RoleCell]] = None,
                   channel_at: Optional[Dict[int, int]] = None) -> None:
        self.beginResetModel()
        self.sheet, self.selected_columns = sheet, selected_columns
        self.role_cells, self.channel_at = role_cells or {}, channel_at or {}
        self._width = max((len(row) for row in sheet.cells), default=0) if sheet is not None else 0
        self.endResetModel()

    def set_mode(self, mode: str) -> None:
        self.beginResetModel()
        self.mode = mode
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if self.sheet is None or parent.isValid() else len(self.sheet.cells)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._width

    def _is_read(self, row: int, column: int) -> bool:
        sheet = self.sheet
        if sheet.skipped or sheet.heading_row < 0:
            return False
        if row <= sheet.heading_row:
            return True
        return row >= sheet.data_row and (column in sheet.x_columns or column in sheet.channel_columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.sheet is None:
            return None
        row, column = index.row(), index.column()
        cells = self.sheet.cells[row]
        text = cells[column] if column < len(cells) else ""
        if role == Qt.ItemDataRole.DisplayRole:
            return text
        cell = self.role_cells.get((row, column)) if self.mode == MODE_ROLES else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{text}\n{cell[3]}" if cell is not None and cell[3] else text
        if role == MARKS_ROLE:
            return cell[2] if cell is not None else None
        if role == Qt.ItemDataRole.ForegroundRole and not self._is_read(row, column):
            return QBrush(muted_color())
        heading = self.sheet.heading_row
        if role == Qt.ItemDataRole.FontRole and self.mode == MODE_TABLE and row == heading and heading >= 0:
            font = QFont()
            font.setBold(True)
            return font
        if role != Qt.ItemDataRole.BackgroundRole or heading < 0 or self.sheet.skipped:
            return None
        if self.mode in (MODE_CHANNELS, MODE_ROLES):
            if column in self.selected_columns and row >= heading:
                highlight = QApplication.palette().color(QPalette.ColorRole.Highlight)
                highlight.setAlpha(50)
                return QBrush(highlight)
            return None
        if row < heading:
            return QBrush(QColor(*_HEADER_TINT))
        if row == heading:
            return QBrush(QColor(*_HEADING_TINT))
        if row >= self.sheet.data_row and column in self.sheet.x_columns:
            return QBrush(QColor(*_X_TINT))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        sheet = self.sheet
        if orientation == Qt.Orientation.Vertical:
            label = str(section + 1)
            if self.mode == MODE_TABLE and sheet is not None and sheet.heading_row >= 0:
                if section == sheet.heading_row:
                    label += "  headings ▸"
                elif section == sheet.data_row:
                    label += "  data ▸"
            return label
        return _column_letters(section)     # X / channel are told by the cells' tint and dimming, not here


class _RoleChipsDelegate(QStyledItemDelegate):
    """A header cell's text with its chips with a role marked; the other cells as usual."""

    def paint(self, painter, option, index) -> None:
        marks = index.data(MARKS_ROLE)
        if not marks:
            super().paint(painter, option, index)
            return
        self.initStyleOption(option, index)
        text, option.text = option.text, ""
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)
        paint_role_chips(painter, option.rect, text, marks, option.font, option.palette.color(QPalette.ColorRole.Text))


def _chips_tooltip(chips: SampleChips, roles: SampleRoles, channel: int, key: Tuple[str, int],
                   describe: Callable[[ChipRef], str]) -> str:
    """Every chip of one channel's text: its roles and how it changes across the samples."""
    lines = []
    for found in chips.resolve_chips(channel, key).chips:
        ref = ChipRef(key[0], key[1], found.chip, found.piece)
        held = " + ".join(ROLE_LABELS[kind] for kind in resolve_chip_kinds(chips, roles, channel, ref)) or "no role"
        lines.append(f"'{found.text}' → {held}  ({describe(ref)})")
    return "\n".join(lines)


class SampleGridPane(QWidget):
    """
    Sheet tabs, the grid and a legend. `heading_clicked` / `data_start_clicked`:
    (path, sheet, row from 0). On step 3 `text_clicked(channel, source key)` is
    a click on a text with chips and `channel_clicked(channel)` one on a
    channel's data or on another sheet's tab (its first channel).
    """

    heading_clicked = Signal(str, str, int)
    data_start_clicked = Signal(str, str, int)
    text_clicked = Signal(int, object)
    channel_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.preview: Optional[SamplePreview] = None
        self.shown: Optional[SheetKey] = None
        self.selected_columns: Tuple[int, ...] = ()
        self.chips: Optional[SampleChips] = None
        self.roles = SampleRoles()
        self.selected_channel = -1
        self.describe: Callable[[ChipRef], str] = lambda _ref: ""
        self.role_kinds: Tuple[str, ...] = CHIP_ROLE_KINDS
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabBar()
        self.tabs.setObjectName("WizardSheetTabs")  # Help figure target
        self.tabs.setExpanding(False)
        self.tabs.currentChanged.connect(self._on_tab)
        layout.addWidget(self.tabs)
        self.text_bar = QHBoxLayout()
        layout.addLayout(self.text_bar)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(f"color:{RED}; font-weight:bold; padding:2px;")
        self.banner.setVisible(False)
        layout.addWidget(self.banner)
        self.model = SampleGridModel()
        self.view = QTableView()
        self.view.setObjectName("WizardPreview")  # Help figure target
        self.view.verticalHeader().setObjectName("WizardRowNumbers")
        self.view.setModel(self.model)
        self.view.setItemDelegate(_RoleChipsDelegate(self.view))
        self.view.horizontalHeader().setDefaultSectionSize(130)
        self.view.verticalHeader().sectionClicked.connect(self._on_row_number)
        self.view.clicked.connect(self._on_cell)
        layout.addWidget(self.view, 1)
        self.legend = QLabel()
        self.legend.setObjectName("WizardRoleLegend")  # Help figure target
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        self.set_mode(MODE_TABLE)

    @property
    def shown_sheet(self) -> Optional[SampleSheet]:
        return self.model.sheet

    def set_mode(self, mode: str) -> None:
        self.model.set_mode(mode)
        if self.preview is not None:
            self._show(self.shown)      # the step 3 marks, spans and texts come and go with the mode
        self._show_legend()

    def _show_legend(self) -> None:
        mode = self.model.mode
        muted = muted_color().name()
        if mode == MODE_ROLES:
            highlight = QApplication.palette().color(QPalette.ColorRole.Highlight).name()
            self.legend.setText(
                "Only a chip with a role is marked in its cell (two roles: two bands):  "
                + "  ".join(f"<span style='background:{role_tint_over_base(kind)}'>&nbsp;{ROLE_LABELS[kind]}"
                            f"&nbsp;</span>" for kind in self.role_kinds)
                + f"  ·  <span style='color:{highlight}'>■</span> the selected channel"
                + f"  ·  <span style='color:{muted}'>dimmed = not read</span>  ·  hover a header cell for its chips")
        elif mode == MODE_TABLE:
            self.legend.setText(
                f"<span style='background:{over_base(_HEADER_TINT)}'>&nbsp;header texts&nbsp;</span>  "
                f"<span style='background:{over_base(_HEADING_TINT)}'>&nbsp;<b>heading row</b>&nbsp;</span>  "
                f"<span style='background:{over_base(_X_TINT)}'>&nbsp;X column&nbsp;</span>  "
                f"<span style='color:{muted}'>dimmed = not read</span>  ·  "
                "<b>click a row number</b> = heading row / first data row")
        else:
            highlight = QApplication.palette().color(QPalette.ColorRole.Highlight).name()
            self.legend.setText(f"<span style='color:{highlight}'>■</span> the selected channel  ·  "
                                f"<span style='color:{muted}'>dimmed = not read</span>")

    def show_preview(self, preview: SamplePreview) -> None:
        """Draws the tabs of a new preview, keeping the shown sheet when it is still there."""
        self.preview = preview
        keys = [(sheet.path, sheet.sheet) for sheet in preview.sheets]
        shown = self.shown if self.shown in keys else (keys[0] if keys else None)
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        for sheet in preview.sheets:
            index = self.tabs.addTab(sheet.label + ("  (skipped)" if sheet.skipped else ""))
            if sheet.skipped:
                self.tabs.setTabTextColor(index, QColor(RED))
                self.tabs.setTabToolTip(index, f"Not read: {sheet.skipped}")
        if shown is not None:
            self.tabs.setCurrentIndex(keys.index(shown))
        self.tabs.blockSignals(False)
        self._show(shown)

    def show_sheet(self, key: SheetKey, columns: Tuple[int, ...] = ()) -> None:
        """Shows a sheet's tab, with these columns marked (the selected channel's)."""
        self.selected_columns = columns
        keys = [(sheet.path, sheet.sheet) for sheet in self.preview.sheets] if self.preview is not None else []
        if key in keys:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(keys.index(key))
            self.tabs.blockSignals(False)
            self._show(key)

    def show_roles(self, chips: Optional[SampleChips], roles: SampleRoles, selected: int,
                   describe: Callable[[ChipRef], str], kinds: Tuple[str, ...] = CHIP_ROLE_KINDS) -> None:
        """
        Step 3: the chips with a role marked; `selected` is the selected channel,
        `describe(ref)` how a chip changes, `kinds` the roles step 3 offers (the legend's).
        """
        self.chips, self.roles, self.selected_channel, self.describe = chips, roles, selected, describe
        if kinds != self.role_kinds:
            self.role_kinds = kinds
            self._show_legend()
        self._show(self.shown)

    def _on_tab(self, index: int) -> None:
        if self.preview is not None and 0 <= index < len(self.preview.sheets):
            sheet = self.preview.sheets[index]
            self.selected_columns = ()
            self._show((sheet.path, sheet.sheet))
            if self.model.mode == MODE_ROLES and self.chips is not None:
                first = next((number for number, channel in enumerate(self.chips.channels)
                              if (channel.path, channel.sheet) == (sheet.path, sheet.sheet)), None)
                if first is not None:
                    self.channel_clicked.emit(first)

    def _show(self, key: Optional[SheetKey]) -> None:
        self.shown = key
        sheet = next((sheet for sheet in self.preview.sheets if (sheet.path, sheet.sheet) == key), None) \
            if self.preview is not None and key is not None else None
        role_cells, channel_at = self._role_cells(sheet) if self.model.mode == MODE_ROLES else ({}, {})
        self.model.show_sheet(sheet, self.selected_columns, role_cells, channel_at)
        self._show_spans(sheet)
        self._show_text_bar()
        self.banner.setVisible(sheet is not None and bool(sheet.skipped))
        if sheet is not None and sheet.skipped:
            self.banner.setText(f"Sheet '{sheet.sheet}' is not read: {sheet.skipped}.")

    def _on_row_number(self, row: int) -> None:
        sheet = self.model.sheet
        if sheet is None or self.model.mode != MODE_TABLE:
            return
        menu = QMenu(self)
        heading = menu.addAction(f"Row {row + 1} is the heading row")
        start = menu.addAction(f"The data starts in row {row + 1}")
        start.setEnabled(sheet.heading_row >= 0 and row > sheet.heading_row)
        header = self.view.verticalHeader()
        chosen = menu.exec(header.mapToGlobal(QPoint(header.width(), self.view.rowViewportPosition(row))))
        if chosen is heading:
            self.heading_clicked.emit(sheet.path, sheet.sheet, row)
        elif chosen is start:
            self.data_start_clicked.emit(sheet.path, sheet.sheet, row)

    # ---- step 3 ----------------------------------------------------------------------------

    def _role_cells(self, sheet: Optional[SampleSheet]) -> Tuple[Dict[Tuple[int, int], RoleCell], Dict[int, int]]:
        """The header cells of the shown sheet's channels, and which channel each data column is."""
        cells: Dict[Tuple[int, int], RoleCell] = {}
        channel_at: Dict[int, int] = {}
        chips = self.chips
        if sheet is None or chips is None or sheet.skipped:
            return cells, channel_at
        for number, channel in enumerate(chips.channels):
            if (channel.path, channel.sheet) != (sheet.path, sheet.sheet):
                continue
            for column in (channel.x_column, channel.y_column):
                if column >= 0:
                    channel_at.setdefault(column, number)
            for key, text in channel.texts:
                if key[0] != SOURCE_HEADER:
                    continue
                row = channel.heading_row - key[1]
                column = channel.y_column if key[1] == 0 else channel.header_column
                if not 0 <= row < len(sheet.cells) or column >= len(sheet.cells[row]):
                    continue
                marks = resolve_shifted_marks(sheet.cells[row][column], text,
                                              resolve_chip_marks(chips, self.roles, number, key))
                cells[(row, column)] = (number, key, marks or (),
                                        _chips_tooltip(chips, self.roles, number, key, self.describe))
        return cells, channel_at

    def _show_spans(self, sheet: Optional[SampleSheet]) -> None:
        """On step 3 an X/Y pair's header cells above the heading row span both its columns."""
        self.view.clearSpans()
        if self.model.mode != MODE_ROLES or sheet is None or self.chips is None or sheet.skipped:
            return
        for channel in self.chips.channels:
            if ((channel.path, channel.sheet) == (sheet.path, sheet.sheet) and channel.x_column >= 0
                    and channel.header_column == channel.x_column and channel.y_column == channel.x_column + 1):
                for row in range(channel.heading_row):
                    self.view.setSpan(row, channel.x_column, 1, 2)

    def _show_text_bar(self) -> None:
        """The selected channel's sheet, file and folder texts above the grid, on step 3."""
        while self.text_bar.count():
            widget = self.text_bar.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        chips, selected = self.chips, self.selected_channel
        if self.model.mode != MODE_ROLES or chips is None or not 0 <= selected < len(chips.channels):
            return
        channel = chips.channels[selected]
        for source, label in _OUTER_TEXTS:
            key = (source, 0)
            text = channel.resolve_text(key)
            if text is None or chips.resolve_source(key) is None:
                continue
            button = RoleTextButton(label, text, resolve_chip_marks(chips, self.roles, selected, key), False)
            button.setToolTip(_chips_tooltip(chips, self.roles, selected, key, self.describe))
            button.clicked.connect(lambda _=False, key=key: self.text_clicked.emit(self.selected_channel, key))
            self.text_bar.addWidget(button)
        self.text_bar.addStretch(1)

    def _on_cell(self, index) -> None:
        if self.model.mode != MODE_ROLES:
            return
        cell = self.model.role_cells.get((index.row(), index.column()))
        if cell is not None:
            self.text_clicked.emit(cell[0], cell[1])
        elif index.column() in self.model.channel_at:
            self.channel_clicked.emit(self.model.channel_at[index.column()])
