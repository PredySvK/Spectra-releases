# =====================================================================
# FILE: gui/dialogs/compute_result_set_dialog.py
# =====================================================================
"""
"Compute Result Set" -- the dialog behind the button every analysis ribbon tab
ends with (ARCHITECTURE_DECISIONS §1.6).

It answers one question in two parts before a batch runs:

  * Channels -- type (acceleration / sound) and all-vs-picked.
  * Orders -- one extra line, Order Tracking only, handed in by the tab.

On accept it writes the channel scope back to QSettings under the tab's prefix
(gui/ribbon/save_section.ComputeResultSetButton reads it there) and exposes
`custom_label` for gui/handlers/batch_run.py to read. It does not run
anything itself -- pressing Compute is the caller's business, same split as the
old inline section had.

Lives in gui/dialogs/: it drives QSettings and Qt dialogs, so it cannot sit any
lower.
"""
from typing import Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from io_modules.result_cache.cache_naming import sanitize_result_set_label
from selection.measurement_selection import channel_identities_by_type

from gui.dialogs.dialog_state import remember_dialog_geometry
from gui.ribbon.save_section import (
    SAVE_CHANNEL_TYPE_OPTIONS, identities_to_settings, read_selected_identities,
)
from view_models.evaluation import parse_orders_text

_DEFAULT_CHANNEL_TYPE = "Acceleration"


class ComputeResultSetDialog(QDialog):
    def __init__(self, *, settings_prefix: str, app_context,
                 extra_orders: bool = False, folder_count: int = 0,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Compute Result Set")
        self.setMinimumWidth(440)
        self._prefix = settings_prefix
        self._app_context = app_context
        self._settings = getattr(app_context, "settings", None)
        self._selected_identities = read_selected_identities(
            self._settings, self._prefix)

        # Blank = the caller derives a name from the parameters
        # (default_result_set_label); a non-empty value overrides that and is
        # what the result set folder is called on disk (sanitised on accept).
        self.custom_label: str = ""

        self._build_ui(extra_orders, folder_count)

        # Remembered across restarts; cleared by Settings > Reset Layout / Reset All.
        remember_dialog_geometry(self, self._settings, "compute_result_set", default_size=(460, 520))

    # ---- construction --------------------------------------------------

    def _build_ui(self, extra_orders: bool, folder_count: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_input_group(folder_count))
        layout.addWidget(self._build_channels_group())
        orders_box = self._build_orders_group(extra_orders)
        if orders_box is not None:
            layout.addWidget(orders_box)
        layout.addWidget(self._build_name_group())
        layout.addWidget(self._build_buttons())

        self._on_channel_mode_changed()
        self._on_name_changed()
        self._update_compute_button_state()

    def _build_input_group(self, folder_count: int) -> QGroupBox:
        box_input = QGroupBox("Input Data")
        input_col = QVBoxLayout(box_input)
        self.lbl_folder = QLabel(self._folder_summary(folder_count))
        self.lbl_folder.setStyleSheet("color: #9aa0a6;")
        input_col.addWidget(self.lbl_folder)
        return box_input

    def _build_channels_group(self) -> QGroupBox:
        self.box_channels = QGroupBox("Channels")
        chan_col = QVBoxLayout(self.box_channels)
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(list(SAVE_CHANNEL_TYPE_OPTIONS.keys()))
        self.combo_type.setCurrentText(self._get_val("save_channel_type", _DEFAULT_CHANNEL_TYPE))
        # A hand-picked list means a different thing once the type filter moves.
        self.combo_type.currentTextChanged.connect(lambda _: self._selected_identities.clear())
        type_row.addWidget(self.combo_type, 1)
        chan_col.addLayout(type_row)

        self.rb_all = QRadioButton("All channels")
        self.rb_selected = QRadioButton("Selected channels")
        if self._get_val("save_channel_mode", "all") == "selected":
            self.rb_selected.setChecked(True)
        else:
            self.rb_all.setChecked(True)
        self.rb_selected.toggled.connect(self._on_channel_mode_changed)
        chan_col.addWidget(self.rb_all)
        picked_row = QHBoxLayout()
        picked_row.addWidget(self.rb_selected)
        self.btn_choose = QPushButton("Choose…")
        self.btn_choose.clicked.connect(self._open_channel_picker)
        picked_row.addWidget(self.btn_choose)
        picked_row.addStretch()
        chan_col.addLayout(picked_row)
        return self.box_channels

    def _build_orders_group(self, extra_orders: bool) -> Optional[QGroupBox]:
        # Order Tracking only -- every other tab hands in extra_orders=False.
        self.edit_orders = None
        if not extra_orders:
            return None
        box_orders = QGroupBox("Orders to compute && save")
        orders_row = QHBoxLayout(box_orders)
        self._default_orders_tooltip = (
            "Orders this batch computes and saves, e.g. 1, 2, 4.5 or 1; 2; 4.5. "
            "Decimal separator must be a dot (.)."
        )
        self.edit_orders = QLineEdit(self._batch_orders())
        self.edit_orders.setToolTip(self._default_orders_tooltip)
        self.edit_orders.textChanged.connect(self._on_orders_changed)
        orders_row.addWidget(QLabel("Orders"))
        orders_row.addWidget(self.edit_orders, 1)
        return box_orders

    def _build_name_group(self) -> QGroupBox:
        box_name = QGroupBox("Result set name")
        name_col = QVBoxLayout(box_name)
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Optional -- auto-generated from the parameters if blank")
        self.edit_name.setToolTip(
            "The folder this result set is saved under. Leave blank to let the "
            "app name it (e.g. Order_Tracking_2x_All_Channels)."
        )
        name_col.addWidget(self.edit_name)
        # The typed name becomes a folder name, so it is sanitised (finding
        # 5.1); this line shows the result before the batch runs instead of
        # only in the Compare tab afterwards.
        self.lbl_name_preview = QLabel("")
        self.lbl_name_preview.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        name_col.addWidget(self.lbl_name_preview)
        self.edit_name.textChanged.connect(self._on_name_changed)
        return box_name

    def _build_buttons(self) -> QDialogButtonBox:
        buttons = QDialogButtonBox()
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.btn_compute = buttons.addButton("Compute", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        return buttons

    # ---- reactions -----------------------------------------------------

    def _on_channel_mode_changed(self, *_) -> None:
        self.btn_choose.setEnabled(self.rb_selected.isChecked())

    def _on_orders_changed(self, *_) -> None:
        self._update_compute_button_state()

    def _on_name_changed(self, *_) -> None:
        typed = self.edit_name.text().strip()
        clean = sanitize_result_set_label(typed)
        if not typed:
            self.lbl_name_preview.setText("")
        elif not clean:
            self.lbl_name_preview.setText("This name has no usable characters -- pick another.")
        elif clean != typed:
            self.lbl_name_preview.setText(f"Saved as folder: {clean}")
        else:
            self.lbl_name_preview.setText("")
        self._update_compute_button_state()

    def _update_compute_button_state(self) -> None:
        typed = self.edit_name.text().strip()
        clean = sanitize_result_set_label(typed)
        name_valid = not typed or bool(clean)

        orders_valid = True
        if self.edit_orders is not None:
            parsed = parse_orders_text(self.edit_orders.text())
            orders_valid = bool(parsed)
            if orders_valid:
                self.edit_orders.setStyleSheet("")
                self.edit_orders.setToolTip(self._default_orders_tooltip)
            else:
                self.edit_orders.setStyleSheet("border: 1px solid #d9534f;")
                self.edit_orders.setToolTip(
                    "Invalid orders: enter positive numbers with decimal dot (.), "
                    "separated by commas or semicolons."
                )

        self.btn_compute.setEnabled(name_valid and orders_valid)

    def _open_channel_picker(self) -> None:
        from gui.dialogs.channel_selection_dialog import ChannelSelectionDialog

        loaded_runs = list(getattr(self._app_context.pool, "loaded_runs", []))
        types = set(SAVE_CHANNEL_TYPE_OPTIONS.get(self.combo_type.currentText(), set()))
        identities = channel_identities_by_type(
            loaded_runs, types, self._app_context.project_session.sources_by_path()
        )
        dialog = ChannelSelectionDialog(
            identities, self._selected_identities, self, settings=self._settings
        )
        if dialog.exec():
            self._selected_identities = dialog.selected_identities()

    # ---- accept ------------------------------------------------------

    def _on_accept(self) -> None:
        self._set_val("save_channel_type", self.combo_type.currentText())
        self._set_val("save_channel_mode",
                      "selected" if self.rb_selected.isChecked() else "all")
        if self._settings:
            self._settings.setValue(
                f"{self._prefix}_save_selected_identities",
                identities_to_settings(self._selected_identities),
            )
        if self.edit_orders is not None and self._settings:
            # Unprefixed on purpose: TabAccOrderTracking.get_save_dsp_config()
            # reads this exact key back when the batch runs. Going through
            # _set_val() would prefix it ("order_order_save_targets") and the
            # batch would silently keep computing the old orders -- which is
            # how a re-compute at a different order still hit the "already
            # exists" prompt.
            parsed = parse_orders_text(self.edit_orders.text())
            if parsed:
                self._settings.setValue("order_save_targets", self.edit_orders.text())

        # Sanitised here so the value handed back is exactly the folder name
        # on disk (finding 5.1); begin_result_set sanitises again as a backstop.
        self.custom_label = sanitize_result_set_label(self.edit_name.text())

        self.accept()

    # ---- helpers -----------------------------------------------------

    def _batch_orders(self) -> str:
        """
        What to show in the Orders field. Both keys are unprefixed because both
        are shared with TabAccOrderTracking: `order_save_targets` is the batch
        value it reads at run time, `order_targets` its live-plot value used
        only as the first-time seed so the field is not stuck at a fixed
        default while the user dials orders into the ribbon.
        """
        if not self._settings:
            return "1, 2"
        saved = self._settings.value("order_save_targets", None)
        if saved not in (None, ""):
            return str(saved)
        return str(self._settings.value("order_targets", "1, 2"))

    def _folder_summary(self, count: int) -> str:
        if count <= 0:
            return "No folder loaded in the File Explorer"
        return f"{count} measurement{'s' if count != 1 else ''} loaded in the File Explorer"

    def _get_val(self, suffix: str, default):
        if self._settings:
            return str(self._settings.value(f"{self._prefix}_{suffix}", default))
        return default

    def _set_val(self, suffix: str, value) -> None:
        if self._settings:
            self._settings.setValue(f"{self._prefix}_{suffix}", value)
