# =====================================================================
# FILE: gui/dialogs/measurement_selection_dialog.py
# =====================================================================
"""
The Selection editor (#462, ADR §1.131): a name, the Filter panel's facet
column grid over the whole Data Pool, and a live "N measurements / M channels"
count. Accepting it hands back a query MeasurementSelection; storing it is the
caller's business. Given a stored selection it is the Edit dialog (#463): the
name is fixed (Rename is its own action).

What the editor holds -- the offer, the checkmarks, the rule an Edit opened
and the validation -- is a session.measurement_selection Selection draft
(#906); this dialog only draws it and hands it the user's input. The draft's
checks live in a FilterSelectionStore of its own, so authoring a Selection
never touches the Filter panel's mask. The column configuration is one card
for every Selection, stored with the Filter cards in the project under
SELECTION_CARD_ID. The count runs on the job runner, superseding itself on
every edit, so a large pool never freezes the dialog.
"""
from typing import Iterable, Optional

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from core.filter_card_config import FilterCardConfig
from core.jobs import job_step
from core.measurement_selection import MeasurementSelection
from selection.measurement_selection import SELECTION_EXCLUDED_COLUMNS, SelectionResolution, resolve
from selection.trace_filter import resolve_card
from session.measurement_selection import SELECTION_CARD_ID, MeasurementSelectionDraft
from view_models.measurement_selection import describe_counts

from gui.dialogs.dialog_state import remember_dialog_geometry
from gui.filter_panel.facet_grid import FacetGrid
from gui.appearance import APP_TOKENS


_COUNT_SLOT = "measurement_selection_dialog.count"


class MeasurementSelectionDialog(QDialog):
    def __init__(self, session, schema: dict, job_runner, *,
                 selection: Optional[MeasurementSelection] = None,
                 taken_names: Iterable[str] = (), settings=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Selection" if selection else "Create Selection")
        self._session = session
        self._schema = schema
        self._settings = settings
        self._job_runner = job_runner
        self._draft = draft = MeasurementSelectionDraft(
            session.project, schema, resolve_card(session, SELECTION_CARD_ID, schema),
            selection=selection, taken_names=taken_names)
        self._resolution: Optional[SelectionResolution] = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.txt_name = QLineEdit(draft.name)
        self.txt_name.setReadOnly(draft.is_edit)
        self.txt_name.textChanged.connect(self._on_name_changed)
        form.addRow("Name:", self.txt_name)
        layout.addLayout(form)

        self.grid = FacetGrid(draft.store, lambda: draft.selection_key,
                              excluded_columns=SELECTION_EXCLUDED_COLUMNS, parent=self)
        self.grid.btn_configure.setText("⚙ Configure…")
        self.grid.btn_configure.setToolTip("Pick which columns the Selection editor shows.")
        self.grid.btn_configure.clicked.connect(self._configure)
        self.grid.selection_changed.connect(self._recount)
        layout.addWidget(self.grid, stretch=1)

        self.lbl_count = QLabel()
        self.lbl_problem = QLabel()
        # object names: targets of the help figure annotations
        self.txt_name.setObjectName("SelectionNameField")
        self.grid.setObjectName("SelectionGrid")
        self.lbl_count.setObjectName("SelectionCount")
        self.lbl_problem.setStyleSheet(f"color: {APP_TOKENS.text_problem};")
        layout.addWidget(self.lbl_count)
        layout.addWidget(self.lbl_problem)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        remember_dialog_geometry(self, settings, "measurement_selection", default_size=(720, 560))
        self._draw()

    # ---- grid -----------------------------------------------------------

    def _draw(self) -> None:
        self.grid.populate_facets(self._draft.facets)
        self._recount()

    def _show_card(self, card: FilterCardConfig) -> None:
        self._draft.set_card(card)
        self._draw()

    def _configure(self) -> None:
        from gui.dialogs.filter_field_selection_dialog import FilterFieldSelectionDialog

        card = self._draft.card
        dialog = FilterFieldSelectionDialog(
            self._schema, self, settings=self._settings, card=card,
            cardinalities=self._draft.resolve_cardinalities(),
            on_live_change=self._show_card, excluded_columns=SELECTION_EXCLUDED_COLUMNS)
        try:
            updated = dialog.result_card() if dialog.exec() else card
        finally:
            dialog.deleteLater()
        if updated != card:
            self._session.put_filter_card(updated)
        self._show_card(updated)

    # ---- count ----------------------------------------------------------

    def selection(self) -> MeasurementSelection:
        """The rule the current checkmarks describe, under the typed name."""
        return self._draft.resolve_selection()

    def _recount(self) -> None:
        self._resolution = None
        self.lbl_count.setText(describe_counts(None))
        self._update_ok()
        self._job_runner.submit(
            "Count Selection",
            [job_step("Count", resolve, self.selection(), self._draft.pool_sources, self._schema)],
            lane="interactive", slot_key=_COUNT_SLOT, quiet=True,
            on_step=lambda resolution, _index: self._show_count(resolution),
        )

    def _show_count(self, resolution: SelectionResolution) -> None:
        self._resolution = resolution
        self.lbl_count.setText(describe_counts(resolution))
        self._update_ok()

    # ---- validation -----------------------------------------------------

    def _on_name_changed(self, text: str) -> None:
        self._draft.name = text
        self._update_ok()

    def _update_ok(self) -> None:
        problem = self._draft.problem(self._resolution)
        self.lbl_problem.setText(problem)
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setEnabled(not problem and self._resolution is not None)

    def done(self, result: int) -> None:
        self._job_runner.cancel_slot(_COUNT_SLOT)
        super().done(result)
