# gui/dialogs/metadata_editor_dialog.py
"""
Universal Agnostic Metadata Schema Editor Dialog framework.
Dynamically displays discovered metadata fields allowing runtime renames and visibility toggles.
All internal documentation strings and variable labels are standardly written in English.
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                               QTableWidgetItem, QPushButton, QLabel, QComboBox,
                               QHeaderView, QTabWidget, QWidget)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette

from gui.dialogs.dialog_state import remember_dialog_geometry
from gui.dialogs.channel_pairing_tab import ChannelPairingTab
from io_modules.metadata_schema import build_schema_field_choice, resolve_schema_field_kind
from io_modules.channel_pairing import PAIRING_FILE_NAME
from io_modules.measurement_files import is_simulated_result_file
from orchestration.channel_pairing import resolve_channel_pairing_path, write_project_channel_pairing
from selection.channel_identity import split_channel_base_and_direction


# Metadata Editor "Type" column -> schema kind. "Auto" leaves the kind to the
# inference over the actual values (ADR §1.1); any other choice pins it and
# sets kind_is_manual so a rescan will not override the user.
_KIND_CHOICES = (("Auto", None), ("Text", "str"), ("Integer", "int"),
                 ("Decimal", "float"), ("Date", "date"))

# Checkbox columns whose header click checks/unchecks the whole column.
_TOGGLE_ALL_COLUMNS = (0, 3)


class _TypeComboBox(QComboBox):
    """Type column combo that only takes the wheel once the user has focused it.

    Scrolling the table over an unfocused combo would otherwise silently
    re-type the field (list facet vs. range facet); the ignored event falls
    through to the table, which scrolls instead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class MetadataEditorDialog(QDialog):
    """
    Dynamic schema dialog box managing hardware UNV parameters and relational Excel columns.
    """

    def __init__(self, master_schema: dict, parent=None, settings=None, baseline_schema: dict = None,
                 project=None, project_path=None, channel_pairs=(), pairing_warnings=()):
        super().__init__(parent)
        self.setWindowTitle("Metadata and Filter Settings")
        self.setMinimumSize(880, 520)
        # Keep the system menu and the close button, drop only the "?" help
        # button -- rebuilding the flag set explicitly (rather than masking one
        # bit off the inherited set) is what guarantees the X in the title bar
        # is actually there and wired to reject().
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        self.master_schema = master_schema
        self.baseline_schema = baseline_schema or {}
        self.updated_schema = {}
        self.project = project
        self.project_path = project_path
        self.settings = settings
        # channel_pairing.xlsx as read off the GUI thread just before this opening (#511, #513).
        self.channel_pairs = list(channel_pairs)
        self.pairing_warnings = list(pairing_warnings)
        self.init_ui()

        # Remembered across restarts; cleared by Settings > Reset Layout / Reset All.
        remember_dialog_geometry(self, settings, "metadata_editor", default_size=(940, 640))

    def closeEvent(self, event):
        """The title-bar X is an explicit cancel, same as the Cancel button."""
        self.reject()
        event.accept()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setObjectName("MetadataTabBar")  # help figure target
        layout.addWidget(self.tabs)
        fields_tab = QWidget()
        fields_layout = QVBoxLayout(fields_tab)
        self.tabs.addTab(fields_tab, "Fields")
        self.tabs.addTab(self._build_pairing_tab(), "Pairing")

        fields_layout.addWidget(QLabel("Dynamic Metadata Schema Configuration (Rename fields or toggle visibility flags):"))

        # Initialize adaptive 4-column data grid panel
        self.table = QTableWidget()
        self.table.setObjectName("MetadataFieldsTable")  # help figure target
        self.table.horizontalHeader().setObjectName("MetadataFieldsHeader")
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Active Status", "Original Metadata Key", "Custom Display Label Override",
             "Use as Filter", "Type"])

        # The two middle columns (original key, custom label) are the ones the
        # user reads and edits, so they get the room: key sized to its content,
        # label taking the slack. The three checkbox/combo columns only need to
        # fit their header text.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(1, 220)

        # A real Excel sheet brings ~20 columns; clicking the checkbox header
        # flips the whole column instead of one row at a time.
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._toggle_whole_column)
        for column in _TOGGLE_ALL_COLUMNS:
            self.table.horizontalHeaderItem(column).setToolTip("Click to check / uncheck all rows")

        self.populate_dynamic_grid()
        fields_layout.addWidget(self.table)

        # Bottom interaction controls
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Save & Apply Schema")
        self.btn_cancel = QPushButton("Cancel")

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.btn_save.clicked.connect(self.handle_save_action)
        self.btn_cancel.clicked.connect(self.reject)

    def _build_pairing_tab(self) -> QWidget:
        """Measured <-> simulated channel pairs, as stored in channel_pairing.xlsx (#511)."""
        measured, simulated = set(), set()
        for entry in (self.project.sources if self.project else []):
            if not entry.in_pool:
                continue
            side = simulated if is_simulated_result_file(entry.relpath) else measured
            # One identity per sensor, not per reader label: "Set #N" differs from file to file (#508).
            side.update(split_channel_base_and_direction(label) for label in entry.channels)
        path = resolve_channel_pairing_path(self.project_path) if self.project_path else ""
        self.pairing_tab = ChannelPairingTab(
            measured, simulated, self.channel_pairs, self.pairing_warnings, path, self.settings)
        return self.pairing_tab

    def populate_dynamic_grid(self):
        """Builds grid partitions splitting fields into File-level and Channel-level sections dynamically."""
        schema_fields = dict(self.master_schema)

        # --- THE LAYER DETECT FALLBACK FIX ---
        # Safely defaults to 'excel' layer if the tracking attribute missing from source RAM matrices
        channel_items = {k: v for k, v in schema_fields.items() if v.get("layer") == "channel"}
        excel_items = {k: v for k, v in schema_fields.items() if v.get("layer", "excel") == "excel"}

        total_rows = len(channel_items) + len(excel_items) + 2
        self.table.setRowCount(total_rows)

        current_row = 0

        # --- SECTION 1: CHANNEL LEVEL METADATA ---
        # Not UNV-specific (BUGS.md N1/N2): whichever reader produced the data
        # fills what it can (func_type/sampling_rate/... for both .unv and
        # .asc, id1..id5 only where the format has an equivalent), and a field
        # no loaded run has a value for is simply blank here, not hidden.
        self._insert_section_divider(current_row, "--- LEVEL 1: PER-CHANNEL PARAMETERS ---")
        current_row += 1

        for key, config in channel_items.items():
            self._insert_data_row(current_row, key, config, "channel")
            current_row += 1

        # --- SECTION 2: FILE LEVEL METADATA ---
        self._insert_section_divider(current_row, "--- LEVEL 2: RELATIONAL EXCEL FILE-LEVEL METADATA ---")
        current_row += 1

        for key, config in excel_items.items():
            self._insert_data_row(current_row, key, config, "excel")
            current_row += 1

    def _insert_section_divider(self, row_idx: int, section_title: str):
        """Helper inserting structural category boundary splits spans."""
        divider_item = QTableWidgetItem(section_title)
        divider_item.setFlags(Qt.ItemFlag.NoItemFlags)
        divider_item.setForeground(Qt.GlobalColor.black)
        divider_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        self.table.setItem(row_idx, 0, divider_item)
        self.table.setSpan(row_idx, 0, 1, 5)

        for c in range(5):
            cell = self.table.item(row_idx, c)
            if cell:
                cell.setBackground(Qt.GlobalColor.darkGray)

    def _insert_data_row(self, row_idx: int, original_key: str, config: dict, layer_type: str):
        """Injects a standardized interactive row entry line matching state markers."""
        cb_item = QTableWidgetItem()
        cb_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        cb_item.setCheckState(Qt.CheckState.Checked if config.get("is_active", True) else Qt.CheckState.Unchecked)
        self.table.setItem(row_idx, 0, cb_item)

        key_item = QTableWidgetItem(original_key)
        key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        # Read-only look from a matched palette pair: a fixed light grey under
        # the palette's text colour was white-on-grey in the dark Windows theme.
        palette = self.table.palette()
        key_item.setBackground(palette.color(QPalette.ColorRole.Window))
        key_item.setForeground(palette.color(QPalette.ColorRole.WindowText))
        self.table.setItem(row_idx, 1, key_item)

        label_item = QTableWidgetItem(config.get("custom_label", original_key))
        self.table.setItem(row_idx, 2, label_item)

        filter_item = QTableWidgetItem()
        filter_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        filter_item.setCheckState(
            Qt.CheckState.Checked if config.get("usable_as_filter", False) else Qt.CheckState.Unchecked
        )
        self.table.setItem(row_idx, 3, filter_item)

        # Securely lock the layer token explicitly inside user data role cell to guarantee mapping consistency on save
        self.table.item(row_idx, 1).setData(Qt.ItemDataRole.UserRole, layer_type)

        type_combo = _TypeComboBox()
        inferred = resolve_schema_field_kind(config, self.baseline_schema.get(original_key))
        for text, kind in _KIND_CHOICES:
            label = f"Auto ({inferred})" if kind is None else text
            type_combo.addItem(label, kind)
        if config.get("kind_is_manual"):
            manual = config.get("kind", "str")
            match = next((i for i, (_, k) in enumerate(_KIND_CHOICES) if k == manual), 0)
            type_combo.setCurrentIndex(match)
        self.table.setCellWidget(row_idx, 4, type_combo)

    def _toggle_whole_column(self, column: int):
        """Checks every data row in a checkbox column, or clears it when all are checked."""
        if column not in _TOGGLE_ALL_COLUMNS:
            return
        # Divider rows span the table and have no key cell; data rows do.
        items = [self.table.item(r, column) for r in range(self.table.rowCount())
                 if self.table.item(r, 1)]
        all_checked = all(item.checkState() == Qt.CheckState.Checked for item in items)
        target = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        for item in items:
            item.setCheckState(target)

    def handle_save_action(self):
        """Writes channel_pairing.xlsx first; only if that succeeds, harvests the edited schema and accepts."""
        pairs = self.pairing_tab.pairs
        if self.project_path:
            try:
                write_project_channel_pairing(self.project_path, pairs)
            except OSError as error:
                # Nothing is saved, schema included: fix the cause and click again.
                hint = (f"Close {PAIRING_FILE_NAME} and save again"
                        if isinstance(error, PermissionError)
                        else f"Could not write {PAIRING_FILE_NAME}")
                self.pairing_tab.show_message(f"! {hint} ({error})")
                self.tabs.setCurrentWidget(self.pairing_tab)
                return
        self.updated_schema = {}

        for row_idx in range(self.table.rowCount()):
            key_cell = self.table.item(row_idx, 1)
            if not key_cell:
                continue

            original_key = key_cell.text()
            cb_item = self.table.item(row_idx, 0)
            label_cell = self.table.item(row_idx, 2)
            filter_item = self.table.item(row_idx, 3)

            if cb_item and label_cell:
                is_active = (cb_item.checkState() == Qt.CheckState.Checked)
                custom_text = label_cell.text().strip()
                row_layer = key_cell.data(Qt.ItemDataRole.UserRole)
                usable_as_filter = bool(filter_item and filter_item.checkState() == Qt.CheckState.Checked)

                prior = self.master_schema.get(original_key) or {}
                type_combo = self.table.cellWidget(row_idx, 4)
                chosen_kind = type_combo.currentData() if type_combo else None
                entry = build_schema_field_choice(
                    prior, self.baseline_schema.get(original_key, {}), chosen_kind,
                )
                entry.update(
                    custom_label=custom_text or original_key,
                    is_active=is_active,
                    usable_as_filter=usable_as_filter,
                    layer=row_layer or "excel",
                )
                self.updated_schema[original_key] = entry

        self.channel_pairs = pairs
        self.accept()

    def get_finalized_schema(self) -> dict:
        return self.updated_schema












