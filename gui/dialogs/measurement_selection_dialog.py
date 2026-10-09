# =====================================================================
# FILE: gui/dialogs/measurement_selection_dialog.py
# =====================================================================
"""
The Selection editor (#462, ADR §1.131): a name, the Filter panel's facet
column grid over the whole Data Pool, and a live "N measurements / M channels"
count. Accepting it hands back a query MeasurementSelection; storing it is the
caller's business. Given a stored selection it is the Edit dialog (#463): the
name is fixed (Rename is its own action), the checkmarks start from the rule,
and the columns the rule restricts are drawn even when the editor's column
configuration does not list them, so no part of the rule is invisible.

The grid's checked state lives in a FilterSelectionStore of the dialog's own,
so authoring a Selection never touches the Filter panel's mask. The column
configuration is one card for every Selection, stored with the Filter cards
in the project under SELECTION_CARD_ID. The count runs on the job runner,
superseding itself on every edit, so a large pool never freezes the dialog.
"""
from typing import Iterable, Optional

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from core.filter_card_config import BUILTIN_COLUMN_KEYS, FilterCardConfig, add_column
from core.jobs import job_step
from core.measurement_selection import MeasurementSelection
from selection.measurement_selection import (
    SELECTION_EXCLUDED_COLUMNS, WHOLE_POOL_SELECTION_NAME, SelectionResolution,
    build_checks_from_selection, build_selection_from_checks, resolve, resolve_selection_facets,
)
from selection.source_facets import all_pool_sources
from selection.trace_filter import build_column_for_key, resolve_card, resolve_panel_facets
from session.trace_filter import FilterSelectionStore

from gui.dialogs.dialog_state import remember_dialog_geometry
from gui.filter_panel.facet_grid import FacetGrid

# The project's Filter card id the editor's column configuration lives under.
SELECTION_CARD_ID = "measurement_selection_editor"

_COUNT_SLOT = "measurement_selection_dialog.count"


def describe_counts(resolution: SelectionResolution) -> str:
    """The "N measurements / M channels" line the editor and the tab share."""
    return (f"{resolution.measurement_count} measurement(s) / "
            f"{resolution.channel_count} channel(s)")


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
        self._taken_names = set(taken_names) | {WHOLE_POOL_SELECTION_NAME}
        self._sources = all_pool_sources(session.project)
        self._facets = None
        self._card: Optional[FilterCardConfig] = None
        self._resolution: Optional[SelectionResolution] = None

        self._store = FilterSelectionStore()
        self._store.set_scope(SELECTION_CARD_ID, "global")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.txt_name = QLineEdit(selection.name if selection else "")
        self.txt_name.setReadOnly(selection is not None)
        self.txt_name.textChanged.connect(self._update_ok)
        form.addRow("Name:", self.txt_name)
        layout.addLayout(form)

        self.grid = FacetGrid(self._store, lambda: (SELECTION_CARD_ID, None),
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
        self.lbl_problem.setStyleSheet("color: #b00020;")
        layout.addWidget(self.lbl_count)
        layout.addWidget(self.lbl_problem)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        remember_dialog_geometry(self, settings, "measurement_selection", default_size=(720, 560))
        card = resolve_card(session, SELECTION_CARD_ID, schema)
        if selection is None:
            self._populate(card)
            return
        for key in selection.column_values:
            if (key not in SELECTION_EXCLUDED_COLUMNS and not card.has_column(key)
                    and (key in schema or key in BUILTIN_COLUMN_KEYS)):
                card = add_column(card, build_column_for_key(key, schema))
        self._populate(card)
        checks = build_checks_from_selection(selection, self._facets)
        current = self.grid.filter_selection
        for name in ("checked_metadata_values", "checked_identity_values",
                     "checked_channel_identities", "checked_empty_buckets"):
            setattr(current, name, getattr(checks, name))
        self._populate(card)

    # ---- grid -----------------------------------------------------------

    def _populate(self, card: FilterCardConfig) -> None:
        self._card = card
        facets = resolve_panel_facets(
            "global", card, self._schema, project=self._session.project,
            pool_sources=self._sources, focused_identities=[], open_dock_identities=[])
        self._facets = resolve_selection_facets(facets)
        self.grid.populate_facets(self._facets)
        self._recount()

    def _configure(self) -> None:
        from gui.dialogs.filter_field_selection_dialog import FilterFieldSelectionDialog

        card = self._card
        dialog = FilterFieldSelectionDialog(
            self._schema, self._session.project, self, settings=self._settings, card=card,
            on_live_change=self._populate, excluded_columns=SELECTION_EXCLUDED_COLUMNS)
        try:
            updated = dialog.result_card() if dialog.exec() else card
        finally:
            dialog.deleteLater()
        if updated != card:
            self._session.project.put_filter_card(updated)
            self._session.mark_dirty()
        self._populate(updated)

    # ---- count ----------------------------------------------------------

    def selection(self) -> MeasurementSelection:
        """The rule the current checkmarks describe, under the typed name."""
        return build_selection_from_checks(
            self.txt_name.text().strip(), self.grid.filter_selection, self._facets)

    def _recount(self) -> None:
        self._resolution = None
        self.lbl_count.setText("Counting…")
        self._update_ok()
        self._job_runner.submit(
            "Count Selection",
            [job_step("Count", resolve, self.selection(), self._sources, self._schema)],
            lane="interactive", slot_key=_COUNT_SLOT, quiet=True,
            on_step=lambda resolution, _index: self._show_count(resolution),
        )

    def _show_count(self, resolution: SelectionResolution) -> None:
        self._resolution = resolution
        self.lbl_count.setText(describe_counts(resolution))
        self._update_ok()

    # ---- validation -----------------------------------------------------

    def _problem(self) -> str:
        name = self.txt_name.text().strip()
        if not name:
            return "Type a name."
        if name in self._taken_names:
            return f"'{name}' is already taken."
        if self._resolution is not None and self._resolution.measurement_count == 0:
            return "Nothing matches -- check at least one value in every column."
        return ""

    def _update_ok(self) -> None:
        problem = self._problem()
        self.lbl_problem.setText(problem)
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setEnabled(not problem and self._resolution is not None)

    def done(self, result: int) -> None:
        self._job_runner.cancel_slot(_COUNT_SLOT)
        super().done(result)
