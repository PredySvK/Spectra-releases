# =====================================================================
# FILE: gui/bottom_panels/evaluation_panel.py
# =====================================================================
"""
The Evaluation card of the bottom Output panel (ADR Â§1.64, issues #135/#136/#137/#139/#140/#141/#142):
Single values pulled out of the focused dock's curves, one Evaluation table.

Recomputes on four events -- a dock-focus change (the same event the Filter
panel listens to), the focused dock's own content or Trace-filter mask
changing (GraphDock.sig_content_or_mask_changed), the "Respect Trace filter"
toggle, and the card itself becoming visible.

Display switches (RMS / Peak amplitude, Linear / Power / PSD format for
spectra, and global engineering units) rescale the Single values instantly
without recomputing the evaluation (ADR Â§1.64 point 4, Â§1.60, Â§1.61).

Toolbar includes "Columnsâ€¦" (Issue #139) to configure metadata columns shown
in the table, persisted per dock in EvaluationConfig.metadata_columns.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QSpinBox,
    QStackedLayout, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from core.evaluation import EvaluationConfig, EvaluationTable
from core.units import UnitPreferences
from view_models.evaluation import (
    COLUMNS, has_spectra, parse_orders_text, rows_for_table, table_headers, to_clipboard_string, to_csv_string,
)
from gui.dialogs.evaluation_column_selection_dialog import EvaluationColumnSelectionDialog
from gui.workspace.evaluation_adapter import curves_for_evaluation
from orchestration.dock_tasks import PURPOSE_EVALUATION
from signal_processing.evaluation.dominant_orders_eval import (
    DEFAULT_MIN_ORDER_DISTANCE, DEFAULT_ORDER_MAX, DEFAULT_ORDER_MIN, DEFAULT_ORDER_RESOLUTION,
    DEFAULT_N as DEFAULT_DOMINANT_N,
)
from signal_processing.evaluation.registry import EVALUATIONS
from signal_processing.evaluation.runner import evaluate
from signal_processing.evaluation.topn_eval import DEFAULT_MIN_PROMINENCE_DB, DEFAULT_N
from signal_processing.evaluation.typed_orders_eval import DEFAULT_ORDER_WIDTH

_NO_DOCK_MESSAGE = "No graph is open."
_UNSUPPORTED_MESSAGE = "This dock has no curves Evaluation supports."


def _normalize_sort_key(k: Any) -> Any:
    if isinstance(k, (int, float)):
        return (float(k),)
    return k


class EvaluationTableItem(QTableWidgetItem):
    """
    QTableWidgetItem with numerical sorting and invariant bottom placement
    for empty/NaN rows ("â€”") and empty string cells ("").

    In both ascending and descending sorts, dash rows and empty cells are always
    placed at the bottom of the table. Numeric values are compared by their float sort_key.
    """
    def __init__(self, text: str, sort_key: Any = None, is_dash: bool = False):
        super().__init__(text)
        self.sort_key = sort_key
        self.is_dash = is_dash

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if not isinstance(other, EvaluationTableItem):
            return super().__lt__(other)

        table = self.tableWidget()
        is_descending = False
        if table is not None:
            header = table.horizontalHeader()
            if header is not None:
                is_descending = (header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder)

        self_empty = self.is_dash or self.text() == ""
        other_empty = other.is_dash or other.text() == ""
        if self_empty and other_empty:
            return False
        if self_empty:
            return is_descending
        if other_empty:
            return not is_descending

        if self.sort_key is not None and other.sort_key is not None:
            try:
                return self.sort_key < other.sort_key
            except TypeError:
                if (isinstance(self.sort_key, (int, float, tuple))
                        and isinstance(other.sort_key, (int, float, tuple))):
                    return _normalize_sort_key(self.sort_key) < _normalize_sort_key(other.sort_key)
                return str(self.sort_key) < str(other.sort_key)
        if self.sort_key is not None:
            return True
        if other.sort_key is not None:
            return False

        return self.text().casefold() < other.text().casefold()


class EvaluationPanel(QWidget):
    def __init__(self, app_context, workspace, parent=None):
        super().__init__(parent)
        # Object names here are the stable targets of the Help figures (resources/help/figures).
        self.setObjectName("EvaluationPanel")
        self.app_context = app_context
        self.workspace = workspace
        self._focused_dock = None
        self._stale = False
        self._evaluation_name = "max"
        self._current_table: Optional[EvaluationTable] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("Evaluation:"))
        self.combo_evaluation = QComboBox()
        self.combo_evaluation.setObjectName("EvaluationCombo")
        for name, spec in EVALUATIONS.items():
            self.combo_evaluation.addItem(spec.label, name)
        self.combo_evaluation.setCurrentIndex(self.combo_evaluation.findData(self._evaluation_name))
        self.combo_evaluation.currentIndexChanged.connect(self._on_evaluation_changed)
        header.addWidget(self.combo_evaluation)

        # Top-N maxima parameters (Issue #140) -- hidden unless that Evaluation is selected.
        self.lbl_n = QLabel("N:")
        header.addWidget(self.lbl_n)
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 20)
        self.spin_n.setValue(DEFAULT_N)
        self.spin_n.setToolTip(
            "How many Local maxima to return per curve, ranked by height. "
            "A curve with fewer qualifying humps gives fewer rows -- never padded."
        )
        self.spin_n.valueChanged.connect(self._on_params_changed)
        header.addWidget(self.spin_n)

        self.lbl_min_distance = QLabel("Min distance:")
        header.addWidget(self.lbl_min_distance)
        self.spin_min_distance = QDoubleSpinBox()
        self.spin_min_distance.setRange(0.0, 1_000_000.0)
        self.spin_min_distance.setDecimals(3)
        self.spin_min_distance.setValue(0.0)
        self.spin_min_distance.setSpecialValueText("Auto (5% of axis range)")
        self.spin_min_distance.setToolTip(
            "Minimum separation between two selected maxima, in the curve's own X-axis unit "
            "(RPM, Hz or s). \"Auto\" uses 5% of each curve's own axis range."
        )
        self.spin_min_distance.valueChanged.connect(self._on_params_changed)
        header.addWidget(self.spin_min_distance)

        self.lbl_min_prominence = QLabel("Min prominence:")
        header.addWidget(self.lbl_min_prominence)
        self.spin_min_prominence = QDoubleSpinBox()
        self.spin_min_prominence.setRange(0.0, 100.0)
        self.spin_min_prominence.setDecimals(1)
        self.spin_min_prominence.setValue(DEFAULT_MIN_PROMINENCE_DB)
        self.spin_min_prominence.setSuffix(" dB")
        self.spin_min_prominence.setToolTip(
            "How far a maximum must stand above the valley toward its higher neighbour, "
            "in amplitude dB (computed from the square root of canonical power for spectra), "
            "so it does not depend on RMS/Peak or channel sensitivity."
        )
        self.spin_min_prominence.valueChanged.connect(self._on_params_changed)
        header.addWidget(self.spin_min_prominence)

        self._topn_widgets = (
            self.lbl_n, self.spin_n,
            self.lbl_min_distance, self.spin_min_distance,
            self.lbl_min_prominence, self.spin_min_prominence,
        )

        # Typed orders parameters (Issue #141) -- hidden unless that Evaluation is selected.
        self.lbl_orders = QLabel("Orders:")
        header.addWidget(self.lbl_orders)
        self._default_orders_tooltip = (
            "List of orders to read off this rpm spectrogram, separated by commas or semicolons, "
            "e.g. \"1, 2, 4.79\" or \"1; 2; 4.79\". Decimal separator must be a dot. "
            "Each gives one table row: the Max of an order cut sliced directly out of the "
            "spectrogram's own canonical matrix, at the same value and rpm Order Tracking's "
            "Max would give with identical FFT, window, step and order width."
        )
        self.edit_orders = QLineEdit()
        self.edit_orders.setFixedWidth(110)
        self.edit_orders.setPlaceholderText("1, 2, 4.79")
        self.edit_orders.setToolTip(self._default_orders_tooltip)
        self.edit_orders.editingFinished.connect(self._on_params_changed)
        header.addWidget(self.edit_orders)

        self.lbl_order_width = QLabel("Order width:")
        header.addWidget(self.lbl_order_width)
        self.spin_order_width = QDoubleSpinBox()
        self.spin_order_width.setDecimals(2)
        self.spin_order_width.setRange(0.01, 2.0)
        self.spin_order_width.setSingleStep(0.05)
        self.spin_order_width.setValue(DEFAULT_ORDER_WIDTH)
        self.spin_order_width.setToolTip(
            "Order band width ΔO for the moving-band integration, same meaning and default "
            f"({DEFAULT_ORDER_WIDTH:g}) as Order Tracking's own Order Width. This is the evaluation's own parameter, not read "
            "from the Order Tracking ribbon -- the evaluation must be reproducible from itself."
        )
        self.spin_order_width.valueChanged.connect(self._on_params_changed)
        header.addWidget(self.spin_order_width)

        self._typed_orders_widgets = (
            self.lbl_orders, self.edit_orders, self.lbl_order_width, self.spin_order_width,
        )

        # Dominant orders parameters (Issue #142). Order width is the Typed
        # orders spinbox above -- same meaning, one widget.
        self.lbl_order_range = QLabel("Orders:")
        header.addWidget(self.lbl_order_range)
        self.spin_order_min = self._order_spinbox(
            0.0, 1000.0, 2, DEFAULT_ORDER_MIN,
            f"Lowest order searched (default {DEFAULT_ORDER_MIN:g}).",
        )
        header.addWidget(self.spin_order_min)
        self.lbl_order_range_to = QLabel("–")
        header.addWidget(self.lbl_order_range_to)
        self.spin_order_max = self._order_spinbox(
            DEFAULT_ORDER_MIN, 1000.0, 2, DEFAULT_ORDER_MAX,
            f"Highest order searched (default {DEFAULT_ORDER_MAX:g}).",
        )
        header.addWidget(self.spin_order_max)
        self.spin_order_min.valueChanged.connect(self._on_dominant_order_min_changed)
        self.spin_order_max.valueChanged.connect(self._on_dominant_order_max_changed)

        self.lbl_dominant_n = QLabel("N:")
        header.addWidget(self.lbl_dominant_n)
        self.spin_dominant_n = QSpinBox()
        self.spin_dominant_n.setRange(1, 50)
        self.spin_dominant_n.setValue(DEFAULT_DOMINANT_N)
        self.spin_dominant_n.setToolTip(
            f"How many Dominant orders to return, ranked by amplitude (default {DEFAULT_DOMINANT_N}). "
            "Fewer candidates give fewer rows -- never padded."
        )
        self.spin_dominant_n.valueChanged.connect(self._on_params_changed)
        header.addWidget(self.spin_dominant_n)

        self.lbl_min_order_distance = QLabel("Min distance:")
        header.addWidget(self.lbl_min_order_distance)
        self.spin_min_order_distance = self._order_spinbox(
            0.01, 100.0, 2, DEFAULT_MIN_ORDER_DISTANCE,
            "Minimum separation between two Dominant orders, in orders "
            f"(default {DEFAULT_MIN_ORDER_DISTANCE:g}). Also sets how sharp a spectrogram row must be to "
            "take part: rows whose window main lobe spans more orders than this are left out.",
        )
        header.addWidget(self.spin_min_order_distance)

        self.lbl_dominant_prominence = QLabel("Min prominence:")
        header.addWidget(self.lbl_dominant_prominence)
        self.spin_dominant_prominence = self._order_spinbox(
            0.0, 100.0, 1, DEFAULT_MIN_PROMINENCE_DB,
            "How far an order must stand above the valley toward its higher neighbour on the "
            f"max-amplitude-vs-order curve, in amplitude dB (default {DEFAULT_MIN_PROMINENCE_DB:g} dB).",
        )
        self.spin_dominant_prominence.setSuffix(" dB")
        header.addWidget(self.spin_dominant_prominence)

        self.lbl_order_resolution = QLabel("Grid:")
        header.addWidget(self.lbl_order_resolution)
        self.spin_order_resolution = self._order_spinbox(
            0.001, 1.0, 3, DEFAULT_ORDER_RESOLUTION,
            f"Spacing of the common order grid the spectrogram is resampled onto (default "
            f"{DEFAULT_ORDER_RESOLUTION:g}). Coarser is faster; the centroid still refines the order.",
        )
        header.addWidget(self.spin_order_resolution)

        self._dominant_orders_widgets = (
            self.lbl_order_range, self.spin_order_min, self.lbl_order_range_to, self.spin_order_max,
            self.lbl_dominant_n, self.spin_dominant_n,
            self.lbl_min_order_distance, self.spin_min_order_distance,
            self.lbl_dominant_prominence, self.spin_dominant_prominence,
            self.lbl_order_width, self.spin_order_width,
            self.lbl_order_resolution, self.spin_order_resolution,
        )

        # Evaluation name -> its parameter widgets, how to read them into a
        # params dict, and how to write a params dict back into them.
        self._param_groups: Dict[str, _ParamGroup] = {
            "topn_maxima": _ParamGroup(
                self._topn_widgets, self._current_topn_params, self._sync_topn_widgets_from_params,
            ),
            "typed_orders": _ParamGroup(
                self._typed_orders_widgets, self._current_typed_orders_params,
                self._sync_typed_orders_widgets_from_params,
            ),
            "dominant_orders": _ParamGroup(
                self._dominant_orders_widgets, self._current_dominant_orders_params,
                self._sync_dominant_orders_widgets_from_params,
            ),
        }
        self._show_param_group(None)

        # Amplitude switcher (RMS / Peak)
        header.addWidget(QLabel("Amplitude:"))
        self.combo_amplitude = QComboBox()
        self.combo_amplitude.addItem("RMS", "rms")
        self.combo_amplitude.addItem("Peak", "peak")
        self.combo_amplitude.setCurrentIndex(0)
        self.combo_amplitude.currentIndexChanged.connect(self._on_display_setting_changed)
        header.addWidget(self.combo_amplitude)

        # Format switcher (Linear / Power / PSD) for spectra
        self.lbl_format = QLabel("Format:")
        header.addWidget(self.lbl_format)
        self.combo_format = QComboBox()
        self.combo_format.addItem("Linear", "linear")
        self.combo_format.addItem("Power", "power")
        self.combo_format.addItem("PSD", "psd")
        self.combo_format.setCurrentIndex(0)
        self.combo_format.setEnabled(False)
        self.lbl_format.setEnabled(False)
        self.combo_format.currentIndexChanged.connect(self._on_display_setting_changed)
        header.addWidget(self.combo_format)

        header.addStretch()

        # Copy & Export CSV buttons
        self.btn_copy = QToolButton()
        self.btn_copy.setText("Copy")
        self.btn_copy.setToolTip("Copy table to clipboard (tab-separated with headers for Excel)")
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        header.addWidget(self.btn_copy)

        self.btn_export_csv = QToolButton()
        self.btn_export_csv.setObjectName("ExportCsvButton")
        self.btn_export_csv.setText("Export CSV")
        self.btn_export_csv.setToolTip("Export table to CSV file with headers")
        self.btn_export_csv.clicked.connect(lambda: self.export_csv())
        header.addWidget(self.btn_export_csv)

        # Columns selection button (Issue #139)
        self.btn_columns = QToolButton()
        self.btn_columns.setText("Columns\u2026")
        self.btn_columns.setToolTip("Select metadata and identity columns to display in the table")
        self.btn_columns.clicked.connect(self._open_columns_dialog)
        header.addWidget(self.btn_columns)

        # Default on (ADR Â§1.64 point 1). Remembered per dock.
        self.chk_respect_filter = QCheckBox("Respect Trace filter")
        self.chk_respect_filter.setChecked(True)
        self.chk_respect_filter.toggled.connect(self._on_respect_trace_filter_changed)
        header.addWidget(self.chk_respect_filter)

        self.btn_help = QToolButton()
        self.btn_help.setText("?")
        self.btn_help.setToolTip("Open the help page for this Evaluation")
        self.btn_help.clicked.connect(self._open_help)
        header.addWidget(self.btn_help)
        layout.addLayout(header)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("EvaluationTable")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSortingEnabled(True)

        # Context menu and copy shortcut
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self._shortcut_copy = QShortcut(QKeySequence(QKeySequence.StandardKey.Copy), self.table)
        self._shortcut_copy.activated.connect(self.copy_to_clipboard)

        self.message_label = QLabel(_NO_DOCK_MESSAGE)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setWordWrap(True)

        self._body = QStackedLayout()
        self._body.addWidget(self.table)
        self._body.addWidget(self.message_label)
        self._body.setCurrentWidget(self.message_label)
        layout.addLayout(self._body)

    # ---- recompute triggers ------------------------------------------------

    def on_dock_focus_changed(self, dock) -> None:
        """Wired to workspace_tabs.currentChanged."""
        self._focused_dock = dock
        if dock is not None:
            cfg = dock.evaluation_config
            self._evaluation_name = cfg.evaluation_name or "max"

            self.combo_evaluation.blockSignals(True)
            idx = self.combo_evaluation.findData(self._evaluation_name)
            if idx >= 0:
                self.combo_evaluation.setCurrentIndex(idx)
            self.combo_evaluation.blockSignals(False)

            group = self._show_param_group(self._evaluation_name)
            if group is not None:
                group.sync(cfg.params)

            self.chk_respect_filter.blockSignals(True)
            self.chk_respect_filter.setChecked(cfg.respect_trace_filter)
            self.chk_respect_filter.blockSignals(False)
        else:
            self._current_table = None
            self._show_message(_NO_DOCK_MESSAGE)
            return

        if self.isVisible():
            self._recompute()
        else:
            self._stale = True

    def on_dock_content_changed(self, dock) -> None:
        """Wired to GraphDock.sig_content_or_mask_changed."""
        if dock is not self._focused_dock:
            return
        if self.isVisible():
            self._recompute()
        else:
            self._stale = True

    def on_units_changed(self) -> None:
        """Called when global unit settings change."""
        if self._current_table is not None:
            self._render_table_view(self._current_table)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._stale:
            self._recompute()

    def _mark_session_dirty(self) -> None:
        session = getattr(self.app_context, "project_session", None)
        if session is not None and getattr(session, "has_file", False):
            session.mark_dirty()

    def _replace_evaluation_config(self, **overrides: Any) -> Optional[EvaluationConfig]:
        """Applies `overrides` on top of the focused dock's current
        EvaluationConfig (or its defaults), assigns the result back and marks
        the session dirty. The one place every config-mutating action in this
        panel goes through, so a new field added to EvaluationConfig only
        needs a caller to pass it, not four call sites to remember to carry
        the rest forward unchanged."""
        if self._focused_dock is None:
            return None
        current_cfg = getattr(self._focused_dock, "evaluation_config", None) or EvaluationConfig()
        new_cfg = replace(current_cfg, **overrides)
        self._focused_dock.evaluation_config = new_cfg
        self._mark_session_dirty()
        return new_cfg

    def _open_columns_dialog(self) -> None:
        """Opens the evaluation column selection dialog and updates table view."""
        session = getattr(self.app_context, "project_session", None)
        schema = (
            session.project.metadata_schema
            if session is not None and hasattr(session, "project") and hasattr(session.project, "metadata_schema")
            else {}
        )
        settings = getattr(self.app_context, "settings", None)
        cfg = getattr(self._focused_dock, "evaluation_config", None) or EvaluationConfig()
        dlg = EvaluationColumnSelectionDialog(
            schema=schema,
            selected_columns=cfg.metadata_columns,
            parent=self,
            settings=settings,
        )
        if dlg.exec():
            new_cols = dlg.selected_columns()
            if new_cols != cfg.metadata_columns:
                self._replace_evaluation_config(metadata_columns=new_cols)
                if self._current_table is not None:
                    self._render_table_view(self._current_table)

    def _on_evaluation_changed(self, _index: int) -> None:
        self._evaluation_name = self.combo_evaluation.currentData() or "max"
        group = self._show_param_group(self._evaluation_name)
        if self._focused_dock is not None:
            current_cfg = getattr(self._focused_dock, "evaluation_config", None) or EvaluationConfig()
            if group is not None:
                # Keep this dock's own remembered params for this Evaluation if it
                # already had some; otherwise fall back to the widgets' current values.
                params = (
                    current_cfg.params
                    if current_cfg.evaluation_name == self._evaluation_name and current_cfg.params
                    else (group.current() or {})
                )
                group.sync(params)
            else:
                params = {}
            self._replace_evaluation_config(evaluation_name=self._evaluation_name, params=params)
        if self.isVisible():
            self._recompute()
        else:
            self._stale = True

    def _on_params_changed(self, _value=None) -> None:
        group = self._param_groups.get(self._evaluation_name)
        if self._focused_dock is not None and group is not None:
            new_params = group.current()
            if new_params is None:
                # Invalid parameters (e.g. malformed orders input):
                # keep existing configuration and do not recompute.
                return
            self._replace_evaluation_config(params=new_params)
        if self.isVisible():
            self._recompute()
        else:
            self._stale = True

    def _on_dominant_order_min_changed(self, value: float) -> None:
        self.spin_order_max.setMinimum(value)

    def _on_dominant_order_max_changed(self, value: float) -> None:
        self.spin_order_min.setMaximum(value)

    def _show_param_group(self, evaluation_name: Optional[str]) -> Optional["_ParamGroup"]:
        """Shows only `evaluation_name`'s parameter widgets and returns its
        group (None for a parameter-free Evaluation). A widget shared by two
        groups stays visible for either."""
        group = self._param_groups.get(evaluation_name) if evaluation_name else None
        visible = set(group.widgets) if group is not None else set()
        for other in self._param_groups.values():
            for widget in other.widgets:
                widget.setVisible(widget in visible)
        return group

    def _order_spinbox(
        self, minimum: float, maximum: float, decimals: int, value: float, tooltip: str,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(decimals)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setToolTip(tooltip)
        spin.valueChanged.connect(self._on_params_changed)
        return spin

    def _current_dominant_orders_params(self) -> Dict[str, Any]:
        return {
            "n": self.spin_dominant_n.value(),
            "order_min": self.spin_order_min.value(),
            "order_max": self.spin_order_max.value(),
            "min_order_distance": self.spin_min_order_distance.value(),
            "min_prominence_db": self.spin_dominant_prominence.value(),
            "order_width": self.spin_order_width.value(),
            "order_resolution": self.spin_order_resolution.value(),
        }

    def _sync_dominant_orders_widgets_from_params(self, params: Mapping[str, Any]) -> None:
        order_min = float(params.get("order_min", DEFAULT_ORDER_MIN))
        order_max = float(params.get("order_max", DEFAULT_ORDER_MAX))
        self.spin_order_min.blockSignals(True)
        self.spin_order_max.blockSignals(True)
        self.spin_order_min.setRange(0.0, 1000.0)
        self.spin_order_max.setRange(0.0, 1000.0)
        self.spin_order_min.setValue(order_min)
        self.spin_order_max.setValue(order_max)
        self.spin_order_max.setMinimum(order_min)
        self.spin_order_min.setMaximum(order_max)
        self.spin_order_min.blockSignals(False)
        self.spin_order_max.blockSignals(False)

        values = (
            (self.spin_dominant_n, int(params.get("n", DEFAULT_DOMINANT_N))),
            (self.spin_min_order_distance, float(params.get("min_order_distance", DEFAULT_MIN_ORDER_DISTANCE))),
            (self.spin_dominant_prominence, float(params.get("min_prominence_db", DEFAULT_MIN_PROMINENCE_DB))),
            (self.spin_order_width, float(params.get("order_width", DEFAULT_ORDER_WIDTH))),
            (self.spin_order_resolution, float(params.get("order_resolution", DEFAULT_ORDER_RESOLUTION))),
        )
        for spin, value in values:
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _current_typed_orders_params(self) -> Optional[Dict[str, Any]]:
        orders = parse_orders_text(self.edit_orders.text())
        if orders is None:
            self.edit_orders.setStyleSheet("border: 1px solid #d9534f;")
            self.edit_orders.setToolTip(
                "Invalid orders: enter positive numbers with decimal dot (.), "
                "separated by commas or semicolons."
            )
            return None
        self.edit_orders.setStyleSheet("")
        self.edit_orders.setToolTip(self._default_orders_tooltip)
        return {
            "orders": orders,
            "order_width": self.spin_order_width.value(),
        }

    def _sync_typed_orders_widgets_from_params(self, params: Mapping[str, Any]) -> None:
        self.edit_orders.blockSignals(True)
        self.spin_order_width.blockSignals(True)
        orders = params.get("orders") or ()
        self.edit_orders.setText(", ".join(f"{float(o):g}" for o in orders))
        self.edit_orders.setStyleSheet("")
        self.edit_orders.setToolTip(self._default_orders_tooltip)
        self.spin_order_width.setValue(float(params.get("order_width", DEFAULT_ORDER_WIDTH)))
        self.edit_orders.blockSignals(False)
        self.spin_order_width.blockSignals(False)

    def _current_topn_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "n": self.spin_n.value(),
            "min_prominence_db": self.spin_min_prominence.value(),
        }
        min_distance = self.spin_min_distance.value()
        if min_distance > 0.0:
            params["min_distance"] = min_distance
        return params

    def _sync_topn_widgets_from_params(self, params: Mapping[str, Any]) -> None:
        for widget in (self.spin_n, self.spin_min_distance, self.spin_min_prominence):
            widget.blockSignals(True)
        self.spin_n.setValue(int(params.get("n", DEFAULT_N)))
        min_distance = params.get("min_distance")
        self.spin_min_distance.setValue(float(min_distance) if min_distance is not None else 0.0)
        self.spin_min_prominence.setValue(float(params.get("min_prominence_db", DEFAULT_MIN_PROMINENCE_DB)))
        for widget in (self.spin_n, self.spin_min_distance, self.spin_min_prominence):
            widget.blockSignals(False)

    def _on_respect_trace_filter_changed(self, checked: bool) -> None:
        self._replace_evaluation_config(respect_trace_filter=checked)
        if self.isVisible():
            self._recompute()
        else:
            self._stale = True

    def _on_display_setting_changed(self) -> None:
        """Rescales the Single values without recomputing the evaluation."""
        if self._current_table is not None:
            self._render_table_view(self._current_table)

    # ---- recompute ---------------------------------------------------------

    def _recompute(self) -> None:
        self._stale = False
        dock = self._focused_dock
        if dock is None or not hasattr(dock, "visible_traces"):
            self._current_table = None
            self._show_message(_NO_DOCK_MESSAGE)
            return

        curves = curves_for_evaluation(
            dock, self.app_context, respect_trace_filter=self.chk_respect_filter.isChecked(),
        )
        accepted = EVALUATIONS[self._evaluation_name].accepted_block_kinds
        if not any(block.kind in accepted for block, _ in curves):
            self._current_table = None
            self._show_message(_UNSUPPORTED_MESSAGE)
            return

        cfg = getattr(dock, "evaluation_config", None)
        eval_params = cfg.params if cfg is not None else None
        target_dock_id = getattr(dock, "dock_id", None)

        def _on_success(table: EvaluationTable) -> None:
            if self._focused_dock is not None and getattr(self._focused_dock, "dock_id", None) == target_dock_id:
                self._display_table(table)

        def _on_error(message: str) -> None:
            if self._focused_dock is not None and getattr(self._focused_dock, "dock_id", None) == target_dock_id:
                self._show_message(f"Evaluation failed: {message}")

        self.workspace.dock_tasks.run(
            dock.dock_id, evaluate, self._evaluation_name, curves, eval_params,
            on_success=_on_success,
            on_error=_on_error,
            purpose=PURPOSE_EVALUATION,
        )

    def _display_table(self, table: EvaluationTable) -> None:
        self._current_table = table
        self._render_table_view(table)

    def _render_table_view(self, table: EvaluationTable) -> None:
        if not table.rows:
            if self._evaluation_name == "typed_orders":
                self._show_message("No orders specified or found.")
            elif self._evaluation_name == "dominant_orders":
                self._show_message("No dominant orders found in the selected range.")
            else:
                self._show_message("No evaluation results for the current parameters.")
            return

        # Format switcher is enabled only when spectral curves are present
        self.combo_format.setEnabled(has_spectra(table))
        self.lbl_format.setEnabled(has_spectra(table))

        amp_mode = self.combo_amplitude.currentData() or "rms"
        spec_format = self.combo_format.currentData() or "linear"
        prefs: Optional[UnitPreferences] = None
        if hasattr(self.app_context, "unit_preferences"):
            prefs = self.app_context.unit_preferences()

        cfg = getattr(self._focused_dock, "evaluation_config", None)
        selected_cols = cfg.metadata_columns if cfg is not None else ()

        session = getattr(self.app_context, "project_session", None)
        schema = (
            session.project.metadata_schema
            if session is not None and hasattr(session, "project") and hasattr(session.project, "metadata_schema")
            else {}
        )

        headers, active_meta_cols = table_headers(table, selected_cols, schema, spec_format, amp_mode, prefs)

        sorting_was_enabled = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(table.rows))

        rows = rows_for_table(table, spec_format, amp_mode, prefs, active_meta_cols, schema)
        for row_index, row_cells in enumerate(rows):
            for col_index, (text, s_key) in enumerate(zip(row_cells.texts, row_cells.sort_keys)):
                item = EvaluationTableItem(text, sort_key=s_key, is_dash=row_cells.is_dash)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, col_index, item)

        self.table.setSortingEnabled(sorting_was_enabled)
        self._body.setCurrentWidget(self.table)

    def _show_message(self, text: str) -> None:
        self.message_label.setText(text)
        self._body.setCurrentWidget(self.message_label)

    # ---- clipboard & export ------------------------------------------------

    def _export_grid(self, selected_only: bool = False) -> Tuple[List[str], List[List[str]]]:
        """Gathers headers + the currently visible cell grid from self.table
        -- whatever sort order and row selection the user applied stays
        intact, since this reads the live widget rather than re-deriving
        from EvaluationTable."""
        headers = [
            self.table.horizontalHeaderItem(col).text()
            if self.table.horizontalHeaderItem(col) is not None else ""
            for col in range(self.table.columnCount())
        ]
        if selected_only:
            rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()))
            if not rows:
                rows = list(range(self.table.rowCount()))
        else:
            rows = list(range(self.table.rowCount()))
        grid = [
            [
                self.table.item(r, c).text() if self.table.item(r, c) is not None else ""
                for c in range(self.table.columnCount())
            ]
            for r in rows
        ]
        return headers, grid

    def copy_to_clipboard(self) -> None:
        """Copies the table (or selection) to the system clipboard with headers."""
        has_selection = len(self.table.selectedIndexes()) > 0
        headers, grid = self._export_grid(selected_only=has_selection)
        QApplication.clipboard().setText(to_clipboard_string(headers, grid))

    def export_csv(self, file_path: Optional[str] = None) -> Optional[str]:
        """Exports the table to a CSV file with headers."""
        if not file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self, "Export Evaluation Table to CSV", "evaluation.csv", "CSV Files (*.csv);;All Files (*)"
            )
        if not file_path:
            return None
        headers, grid = self._export_grid(selected_only=False)
        try:
            with open(file_path, "w", encoding="utf-8", newline="") as f:
                f.write(to_csv_string(headers, grid))
        except OSError as error:
            QMessageBox.warning(
                self,
                "Export Evaluation Table Failed",
                f"Cannot write to '{file_path}':\n{error}\n\n"
                "The file may be open in another application or the directory is not writable.",
            )
            if hasattr(self.app_context, "log"):
                self.app_context.log(f"ERROR: Failed to export table to {file_path}: {error}")
            return None
        if hasattr(self.app_context, "log"):
            self.app_context.log(f"EVALUATION: Exported table to {file_path}")
        return file_path

    def _show_context_menu(self, pos) -> None:
        if self.table.rowCount() == 0:
            return
        menu = QMenu(self)
        act_copy = menu.addAction("Copy")
        act_copy.triggered.connect(self.copy_to_clipboard)
        act_csv = menu.addAction("Export CSV...")
        act_csv.triggered.connect(lambda: self.export_csv())
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---- help --------------------------------------------------------------

    def _open_help(self) -> None:
        from gui.help import show_help
        topic = EVALUATIONS[self._evaluation_name].help_topic
        show_help(topic, self)


class _ParamGroup(NamedTuple):
    """One Evaluation's parameter widgets and both directions between them
    and an EvaluationConfig.params dict."""
    widgets: Tuple[QWidget, ...]
    current: Callable[[], Optional[Dict[str, Any]]]
    sync: Callable[[Mapping[str, Any]], None]
