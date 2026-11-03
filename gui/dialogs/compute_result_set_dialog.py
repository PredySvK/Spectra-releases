# =====================================================================
# FILE: gui/dialogs/compute_result_set_dialog.py
# =====================================================================
"""
"Compute Result Set" -- the dialog behind the button every analysis ribbon tab
ends with.

It answers one question in three parts before a batch runs:

  * Input -- either the whole Data Pool, narrowed by a sensor-type combo
    (All / Accelerometer / Microphone), or saved Selections ticked in a list,
    one result set each (§1.219). Each comes with the
    count the planner gives for it.
  * Orders -- one extra line, Order Tracking only, handed in by the tab.
  * Name -- optional; only for the Data Pool or a single Selection.

The counts are handed in by the caller (gui/handlers/batch_run.py), computed
by the same orchestration.batch functions the run uses, so the dialog only
shows them.

On accept it hands the whole answer back as `request`, a
CalculateAndSaveRequest that gui/handlers/batch_run.py passes straight to the
planner (#770). It does not run anything itself -- pressing Compute is the
caller's business, same split as the old inline section had.

QSettings only prefill the dialog the next time it opens; the batch never
reads them. The answer used to travel through them, and the contract was a key
name three files had to spell alike -- it drifted once
("order_order_save_targets") and the batch silently kept the old orders.

Lives in gui/dialogs/: it drives QSettings and Qt dialogs, so it cannot sit any
lower.
"""
import json
from typing import Mapping, Optional, Sequence, Tuple, Union

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QRadioButton, QVBoxLayout, QWidget,
)

from orchestration.batch import (
    CalculateAndSaveRequest, DataPoolInput, DataPoolScope, SelectionScope, SelectionsInput,
)
from view_models.batch import (
    DATA_POOL_TYPE_OPTIONS, DEFAULT_DATA_POOL_TYPE, resolve_data_pool_types,
)
from view_models.result_sets import build_label_preview

from gui.dialogs.dialog_state import remember_dialog_geometry
from view_models.evaluation import parse_orders_text
from gui.appearance import APP_TOKENS

INPUT_DATA_POOL = "data_pool"
INPUT_SELECTIONS = "selections"
NO_SELECTIONS_HINT = "No Selections \u2014 create one in the Selections tab"


def _count_text(measurements: int, channels: int) -> str:
    return (f"{measurements} measurement{'s' if measurements != 1 else ''}, "
            f"{channels} channel{'s' if channels != 1 else ''}")


class ComputeResultSetDialog(QDialog):
    def __init__(self, *, settings_prefix: str, settings=None,
                 data_pool_scopes: Optional[Mapping[str, DataPoolScope]] = None,
                 selection_scopes: Sequence[SelectionScope] = (),
                 extra_orders: bool = False, folder_count: int = 0,
                 parent: Optional[QWidget] = None):
        """
        `data_pool_scopes` is what each Data Pool combo label covers;
        `selection_scopes` every saved Selection, in the project's order.
        """
        super().__init__(parent)
        self.setWindowTitle("Compute Result Set")
        self.setMinimumWidth(440)
        self._prefix = settings_prefix
        self._settings = settings
        self._data_pool_scopes = dict(data_pool_scopes or {})
        self._selection_scopes = tuple(selection_scopes)

        # The answer, filled in on accept.
        self.request = CalculateAndSaveRequest()

        self._build_ui(extra_orders, folder_count)

        # Remembered across restarts; cleared by Settings > Reset Layout / Reset All.
        remember_dialog_geometry(self, self._settings, "compute_result_set", default_size=(460, 560))

    # ---- construction --------------------------------------------------

    def _build_ui(self, extra_orders: bool, folder_count: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_input_group(folder_count))
        orders_box = self._build_orders_group(extra_orders)
        if orders_box is not None:
            layout.addWidget(orders_box)
        layout.addWidget(self._build_name_group())
        layout.addWidget(self._build_buttons())

        # Signals are wired after each widget is filled, so the first state is set here.
        self._on_input_changed()
        self._on_name_changed()

    def _build_input_group(self, folder_count: int) -> QGroupBox:
        box_input = QGroupBox("Input Data")
        input_col = QVBoxLayout(box_input)
        self.lbl_folder = QLabel(self._folder_summary(folder_count))
        self.lbl_folder.setStyleSheet(f"color: {APP_TOKENS.text_hint};")
        input_col.addWidget(self.lbl_folder)

        self.radio_data_pool = QRadioButton("Data Pool")
        self.radio_data_pool.setToolTip(
            "The whole Data Pool is computed, whatever the Filter shows. "
            "The tacho is never a main input; it is still the rpm for Order Tracking."
        )
        self.radio_selections = QRadioButton("Selections")
        self.radio_selections.setToolTip(
            "Each ticked Selection becomes its own result set, over its "
            "accelerometer and microphone channels."
        )
        self._input_buttons = QButtonGroup(self)
        self._input_buttons.addButton(self.radio_data_pool)
        self._input_buttons.addButton(self.radio_selections)

        input_col.addWidget(self.radio_data_pool)
        type_row = QHBoxLayout()
        type_row.setContentsMargins(20, 0, 0, 0)
        type_row.addWidget(QLabel("Channels"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(list(DATA_POOL_TYPE_OPTIONS))
        saved = self._get_val("data_pool_type", DEFAULT_DATA_POOL_TYPE)
        self.combo_type.setCurrentText(
            saved if saved in DATA_POOL_TYPE_OPTIONS else DEFAULT_DATA_POOL_TYPE)
        self.combo_type.setToolTip(self.radio_data_pool.toolTip())
        self.combo_type.currentTextChanged.connect(self._on_input_changed)
        type_row.addWidget(self.combo_type, 1)
        input_col.addLayout(type_row)
        self.lbl_count = QLabel("")
        self.lbl_count.setContentsMargins(20, 0, 0, 0)
        input_col.addWidget(self.lbl_count)

        input_col.addWidget(self.radio_selections)
        self.list_selections = QListWidget()
        remembered = set(self._remembered_selections())
        for scope in self._selection_scopes:
            item = QListWidgetItem(
                f"{scope.name}  ({_count_text(scope.measurement_count, scope.channel_count)})")
            item.setData(Qt.ItemDataRole.UserRole, scope.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if scope.name in remembered else Qt.CheckState.Unchecked)
            self.list_selections.addItem(item)
        self.list_selections.itemChanged.connect(self._on_input_changed)
        input_col.addWidget(self.list_selections)
        # Overlapping Selections are each computed, so the totals add up.
        self.lbl_selections_count = QLabel("")
        self.lbl_selections_count.setContentsMargins(20, 0, 0, 0)
        input_col.addWidget(self.lbl_selections_count)
        self.lbl_selections_hint = QLabel(NO_SELECTIONS_HINT)
        self.lbl_selections_hint.setStyleSheet(f"color: {APP_TOKENS.text_hint};")
        input_col.addWidget(self.lbl_selections_hint)

        has_selections = bool(self._selection_scopes)
        self.radio_selections.setEnabled(has_selections)
        self.list_selections.setVisible(has_selections)
        self.lbl_selections_count.setVisible(has_selections)
        self.lbl_selections_hint.setVisible(not has_selections)
        use_selections = has_selections and self._get_val("input", INPUT_DATA_POOL) == INPUT_SELECTIONS
        (self.radio_selections if use_selections else self.radio_data_pool).setChecked(True)
        self.radio_data_pool.toggled.connect(self._on_input_changed)
        return box_input

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
        self.lbl_name_preview.setStyleSheet(f"color: {APP_TOKENS.text_hint}; font-size: 10px;")
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

    def _uses_selections(self) -> bool:
        return self.radio_selections.isChecked()

    def _checked_selections(self) -> Tuple[str, ...]:
        """The ticked Selections' names, in list order."""
        return tuple(
            self.list_selections.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.list_selections.count())
            if self.list_selections.item(row).checkState() == Qt.CheckState.Checked
        )

    def _channel_count(self) -> int:
        """Channels the run would compute: zero keeps Compute off."""
        if self._uses_selections():
            checked = set(self._checked_selections())
            return sum(scope.channel_count for scope in self._selection_scopes if scope.name in checked)
        return self._data_pool_scope().channel_count

    def _data_pool_scope(self) -> DataPoolScope:
        return self._data_pool_scopes.get(self.combo_type.currentText(), DataPoolScope())

    def _on_input_changed(self, *_) -> None:
        uses_selections = self._uses_selections()
        self.combo_type.setEnabled(not uses_selections)
        self.list_selections.setEnabled(uses_selections)
        scope = self._data_pool_scope()
        self.lbl_count.setText(_count_text(scope.measurement_count, scope.channel_count))
        checked = set(self._checked_selections())
        ticked = [scope for scope in self._selection_scopes if scope.name in checked]
        self.lbl_selections_count.setText(
            f"{len(ticked)} result set{'s' if len(ticked) != 1 else ''}: " + _count_text(
                sum(scope.measurement_count for scope in ticked),
                sum(scope.channel_count for scope in ticked)))
        # One name for several result sets would only end in "_2", "_3".
        self.edit_name.setEnabled(not uses_selections or len(self._checked_selections()) <= 1)
        self._update_compute_button_state()

    def _input(self) -> Union[DataPoolInput, SelectionsInput]:
        if self._uses_selections():
            return SelectionsInput(self._checked_selections())
        return DataPoolInput(resolve_data_pool_types(self.combo_type.currentText()))

    def _on_orders_changed(self, *_) -> None:
        self._update_compute_button_state()

    def _on_name_changed(self, *_) -> None:
        preview = build_label_preview(self.edit_name.text())
        if preview.kind == "unusable":
            self.lbl_name_preview.setText("This name has no usable characters -- pick another.")
        elif preview.kind == "changed":
            self.lbl_name_preview.setText(f"Saved as folder: {preview.clean}")
        else:
            self.lbl_name_preview.setText("")
        self._update_compute_button_state()

    def _update_compute_button_state(self) -> None:
        name_valid = (not self.edit_name.isEnabled()
                      or build_label_preview(self.edit_name.text()).kind != "unusable")

        orders_valid = True
        if self.edit_orders is not None:
            parsed = parse_orders_text(self.edit_orders.text())
            orders_valid = bool(parsed)
            if orders_valid:
                self.edit_orders.setStyleSheet("")
                self.edit_orders.setToolTip(self._default_orders_tooltip)
            else:
                self.edit_orders.setStyleSheet(f"border: 1px solid {APP_TOKENS.input_error};")
                self.edit_orders.setToolTip(
                    "Invalid orders: enter positive numbers with decimal dot (.), "
                    "separated by commas or semicolons."
                )

        self.btn_compute.setEnabled(name_valid and orders_valid and self._channel_count() > 0)

    # ---- accept ------------------------------------------------------

    def _on_accept(self) -> None:
        orders = (tuple(parse_orders_text(self.edit_orders.text()) or ())
                  if self.edit_orders is not None else ())

        # Remembered only to prefill the dialog next time.
        self._set_val("input", INPUT_SELECTIONS if self._uses_selections() else INPUT_DATA_POOL)
        self._set_val("data_pool_type", self.combo_type.currentText())
        self._set_val("selections", json.dumps(list(self._checked_selections())))
        if orders:
            # Unprefixed: the key predates the dialog and a renamed key would
            # forget the orders the user last asked for.
            self._settings_set("order_save_targets", self.edit_orders.text())

        self.request = CalculateAndSaveRequest(
            input=self._input(),
            orders=orders,
            # Blank = the planner derives a name from the parameters
            # (default_result_set_label). The preview's clean name, so the value
            # handed back is exactly the folder name on disk (finding 5.1);
            # begin_result_set sanitises again as a backstop.
            custom_label=(build_label_preview(self.edit_name.text()).clean
                          if self.edit_name.isEnabled() else ""),
        )

        self.accept()

    # ---- helpers -----------------------------------------------------

    def _batch_orders(self) -> str:
        """
        What to show in the Orders field: the batch orders asked for last time
        (`order_save_targets`, written only by this dialog), else the ribbon's
        live-plot orders (`order_targets`, TabAccOrderTracking's key) as the
        first-time seed, so the field is not stuck at a fixed default while the
        user dials orders into the ribbon.
        """
        if not self._settings:
            return "1, 2"
        saved = self._settings.value("order_save_targets", None)
        if saved not in (None, ""):
            return str(saved)
        return str(self._settings.value("order_targets", "1, 2"))

    def _remembered_selections(self) -> Tuple[str, ...]:
        """The Selections ticked last time; a name no longer saved simply matches no row."""
        try:
            names = json.loads(self._get_val("selections", "[]"))
        except (TypeError, ValueError):
            return ()
        return tuple(str(name) for name in names) if isinstance(names, list) else ()

    def _folder_summary(self, count: int) -> str:
        if count <= 0:
            return "No folder loaded in the File Explorer"
        return f"{count} measurement{'s' if count != 1 else ''} loaded in the File Explorer"

    def _get_val(self, suffix: str, default):
        if self._settings:
            return str(self._settings.value(f"{self._prefix}_{suffix}", default))
        return default

    def _set_val(self, suffix: str, value) -> None:
        self._settings_set(f"{self._prefix}_{suffix}", value)

    def _settings_set(self, key: str, value) -> None:
        if self._settings:
            self._settings.setValue(key, value)
