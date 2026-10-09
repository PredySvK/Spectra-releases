# =====================================================================
# FILE: gui/dialogs/schema_conflict_dialog.py
# =====================================================================
"""
Telling the user when two data folders disagree about a metadata field.

The pool merges the columns of every folder in it, which is what lets a
measurement from one folder be compared against one from another. Most of that
merge is uncontroversial: a column only one folder has simply has no value for
the others. What is not uncontroversial is a field name that means two
different things -- a spreadsheet column here and a file header field there,
or numbers here and free text there. Merged blindly, it becomes one filter
facet that behaves like two, and the user finds out from a chart that looks
wrong rather than from a message.

So the merge still happens -- refusing it would hide a column the user just
added -- and this reports it afterwards, offering the one decision worth
making: leave the field merged, or keep it out of the filters. The choice is
recorded in the project, so the same folders opened tomorrow do not ask again.

All internal documentation strings and variable labels are standardly written
in English.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs.dialog_state import remember_dialog_geometry
from session.data_pool import ACKNOWLEDGED_KEY, unacknowledged
from view_models.data_pool import describe_schema_conflict


def show_schema_conflicts(app_context, parent, conflicts) -> bool:
    """
    Reports new field collisions, if there are any. Returns whether it showed.

    Deliberately not modal-blocking the ingest: by the time this runs the data
    is already in the pool and usable. This is a notice with a decision
    attached, not a gate in front of the folder.
    """
    pending = unacknowledged(app_context.project_session.project, conflicts)
    if not pending:
        return False

    dialog = SchemaConflictDialog(app_context, pending, parent)
    dialog.exec()
    return True


class SchemaConflictDialog(QDialog):
    def __init__(self, app_context, conflicts, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.conflicts = conflicts
        self._checkboxes = {}

        self.setWindowTitle("Metadata fields differ between folders")
        self.setMinimumWidth(560)
        self._build()

        remember_dialog_geometry(
            self, getattr(app_context, "settings", None), "schema_conflict",
            default_size=(600, 460),
        )

    def _build(self):
        layout = QVBoxLayout(self)

        heading = QLabel(
            f"<b>{len(self.conflicts)} field(s) mean different things in different data folders.</b>"
            "<br>They have been merged so nothing is lost. Tick a field to keep it out of the "
            "filter panel, where a merged field would read as one facet and behave like two."
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        for conflict in self.conflicts:
            checkbox = QCheckBox(f"Exclude '{conflict.key}' from filters")
            detail = QLabel(describe_schema_conflict(conflict))
            detail.setWordWrap(True)
            detail.setStyleSheet("color: #808080; margin-left: 18px; margin-bottom: 6px;")

            body_layout.addWidget(checkbox)
            body_layout.addWidget(detail)
            self._checkboxes[conflict.key] = checkbox

        body_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self._accept)
        layout.addWidget(buttons)

    def _accept(self):
        session = self.app_context.project_session
        schema = dict(session.project.metadata_schema)
        excluded = 0

        for conflict in self.conflicts:
            if not self._checkboxes[conflict.key].isChecked():
                continue
            definition = dict(schema.get(conflict.key) or {})
            definition["usable_as_filter"] = False
            definition["is_active"] = False
            schema[conflict.key] = definition
            excluded += 1

        if excluded:
            self.app_context.pool.update_project_schema(schema)

        seen = set(session.project.ui_state.get(ACKNOWLEDGED_KEY) or [])
        seen.update(conflict.key for conflict in self.conflicts)
        session.project.ui_state[ACKNOWLEDGED_KEY] = sorted(seen)
        session.mark_dirty()

        self.accept()
