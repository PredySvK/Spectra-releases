# =====================================================================
# FILE: gui/workspace/save_spec_editor.py
# =====================================================================
"""
The "Save result set" box under a block node's parameter form
(ARCHITECTURE_DECISIONS §1.6, Epic P phase 7C -- run-first plan, step 2).

A block node carries an optional `core/workflow_graph.py:SaveSpec`: tick it and
that node's output is written as its own result set when the workflow runs; leave
it and the node is just an intermediate the graph feeds downstream. Until now a
`SaveSpec` could only be set from code -- this is the widget that puts it in the
user's hands.

Scope is deliberately half of the full `SaveSpec` (plan 2026-09-02): channel
identity / channel type and a name, nothing more. The measurement facet
(`metadata_values` / `ranges`) stays code-only until §1.1's FilterPanel grows
range/date facets -- but a spec already carrying one from code is preserved
through an edit here rather than silently dropped.

Its own file, not more lines in workflow_view.py, for the same reason
`BlockParamForm` is: phase 8's canvas reuses it in a block's settings dialog.
The channel-type vocabulary is `SAVE_CHANNEL_TYPE_OPTIONS` from the ribbon's
save section -- the same dictionary, so the tree and the ribbon cannot disagree
on what "Acceleration" filters to. The channel picker is the shared
`ChannelSelectionDialog`.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from core.workflow_graph import SaveSpec
from gui.dialogs.channel_selection_dialog import ChannelSelectionDialog
from gui.ribbon.save_section import SAVE_CHANNEL_TYPE_OPTIONS
from io_modules.result_cache.cache_naming import sanitize_result_set_label

_ANY_TYPE = "Any type"


def _identity_sort_key(identity):
    base, direction = identity
    return (base, direction is None, direction or "")


def _type_label_for(channel_types) -> str:
    """The combo label whose channel-type set matches `channel_types`. An
    unrecognised combination falls back to "Any type" -- a v1 limitation, since
    the combo only offers the three ribbon presets."""
    wanted = set(channel_types)
    if not wanted:
        return _ANY_TYPE
    for label, types in SAVE_CHANNEL_TYPE_OPTIONS.items():
        if set(types) == wanted:
            return label
    return _ANY_TYPE


def _channel_types_for(label: str) -> tuple:
    if label == _ANY_TYPE:
        return ()
    return tuple(sorted(SAVE_CHANNEL_TYPE_OPTIONS[label]))


class SaveSpecEditor(QGroupBox):
    """
    Editor for one block node's `SaveSpec`. `set_spec` loads a node's current
    state; `current_spec()` reads the widgets back to a `SaveSpec` or `None`
    (the "Save this node's output" box unticked).

    Does not persist anything itself -- WorkflowView's "Apply node settings"
    button reads `current_spec()` and rebuilds the workflow.
    """

    def __init__(self, parent: Optional[QWidget] = None, settings=None):
        super().__init__("Save result set", parent)
        self._settings = settings
        self._original: Optional[SaveSpec] = None
        # A channel-type set the combo cannot name (imported, or from a newer
        # build). Carried verbatim so a rename here does not silently widen the
        # save filter to every channel (audit 02 finding 2.5).
        self._carried_types: tuple = ()
        self._channel_groups: Dict[str, List[Optional[str]]] = {}
        self._selected_identities: set = set()
        self._read_only = False
        self._build_ui()
        self._sync_enabled()

    # ---- construction ---------------------------------------------------

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setSpacing(4)

        self.chk_save = QCheckBox("Save this node's output")
        self.chk_save.toggled.connect(self._sync_enabled)
        col.addWidget(self.chk_save)

        label_row = QHBoxLayout()
        label_row.addWidget(QLabel("Name:"))
        self.edit_label = QLineEdit()
        self.edit_label.setPlaceholderText("(auto name)")
        label_row.addWidget(self.edit_label, stretch=1)
        col.addLayout(label_row)

        # The name becomes a folder name, so it is sanitised (finding 5.1);
        # show the result when it differs from what was typed.
        self.lbl_label_note = QLabel("")
        self.lbl_label_note.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        self.lbl_label_note.setVisible(False)
        col.addWidget(self.lbl_label_note)
        self.edit_label.textChanged.connect(self._sync_label_note)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Channel type:"))
        self.combo_type = QComboBox()
        self.combo_type.addItem(_ANY_TYPE)
        self.combo_type.addItems(list(SAVE_CHANNEL_TYPE_OPTIONS))
        type_row.addWidget(self.combo_type, stretch=1)
        col.addLayout(type_row)

        self.lbl_type_note = QLabel("")
        self.lbl_type_note.setWordWrap(True)
        self.lbl_type_note.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        self.lbl_type_note.setVisible(False)
        col.addWidget(self.lbl_type_note)
        self.combo_type.currentTextChanged.connect(self._sync_type_note)

        self.radio_all = QRadioButton("All channels")
        self.radio_selected = QRadioButton("Selected channels…")
        self._scope_group = QButtonGroup(self)
        self._scope_group.addButton(self.radio_all)
        self._scope_group.addButton(self.radio_selected)
        self.radio_all.setChecked(True)
        self.radio_all.toggled.connect(self._sync_enabled)

        scope_row = QHBoxLayout()
        scope_row.addWidget(self.radio_all)
        scope_row.addWidget(self.radio_selected)
        self.btn_choose = QPushButton("Choose…")
        self.btn_choose.clicked.connect(self._choose_channels)
        scope_row.addWidget(self.btn_choose)
        scope_row.addStretch()
        col.addLayout(scope_row)

        self.lbl_scope = QLabel("")
        self.lbl_scope.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        col.addWidget(self.lbl_scope)

    # ---- load / read ---------------------------------------------------

    def set_spec(self, save: Optional[SaveSpec], *,
                 channel_groups: Dict[str, List[Optional[str]]],
                 read_only: bool = False) -> None:
        self._original = save
        self._channel_groups = channel_groups or {}
        self._read_only = read_only

        type_label = _type_label_for(save.channel_types) if save else _ANY_TYPE
        self._carried_types = tuple(save.channel_types) if (
            save and save.channel_types and type_label == _ANY_TYPE
        ) else ()

        self.chk_save.setChecked(save is not None)
        self.edit_label.setText(save.label if save else "")
        self.combo_type.setCurrentText(type_label)
        self._sync_type_note()
        self._sync_label_note()

        all_channels = save.all_channels if save else True
        self.radio_all.setChecked(all_channels)
        self.radio_selected.setChecked(not all_channels)
        self._selected_identities = set(save.channel_identities) if save else set()

        self._sync_enabled()

    def current_spec(self) -> Optional[SaveSpec]:
        if not self.chk_save.isChecked():
            return None
        all_channels = self.radio_all.isChecked()
        identities = () if all_channels else tuple(
            sorted(self._selected_identities, key=_identity_sort_key)
        )
        # The measurement facet is not editable here yet -- carry forward
        # whatever an earlier code path put on the spec.
        base = self._original
        type_label = self.combo_type.currentText()
        channel_types = (self._carried_types if type_label == _ANY_TYPE and self._carried_types
                         else _channel_types_for(type_label))
        return SaveSpec(
            label=sanitize_result_set_label(self.edit_label.text()),
            all_channels=all_channels,
            channel_identities=identities,
            channel_types=channel_types,
            metadata_values=dict(base.metadata_values) if base else {},
            ranges=dict(base.ranges) if base else {},
        )

    def _sync_label_note(self, *_) -> None:
        typed = self.edit_label.text().strip()
        clean = sanitize_result_set_label(typed)
        if typed and not clean:
            text = "This name has no usable characters -- it will be auto-named."
        elif clean and clean != typed:
            text = f"Saved as folder: {clean}"
        else:
            text = ""
        self.lbl_label_note.setText(text)
        self.lbl_label_note.setVisible(bool(text))

    def _sync_type_note(self, *_) -> None:
        show = bool(self._carried_types) and self.combo_type.currentText() == _ANY_TYPE
        if show:
            self.lbl_type_note.setText(
                "Keeps an existing channel-type filter: "
                f"{', '.join(self._carried_types)}. Pick a type above to replace it."
            )
        self.lbl_type_note.setVisible(show)

    def set_selected_identities(self, identities) -> None:
        """Test seam: set the explicit channel list without the dialog."""
        self._selected_identities = set(identities)
        self._sync_enabled()

    # ---- interaction --------------------------------------------------

    def _choose_channels(self) -> None:
        dialog = ChannelSelectionDialog(
            self._channel_groups, self._selected_identities, parent=self,
            settings=self._settings,
        )
        if dialog.exec():
            self._selected_identities = dialog.selected_identities()
            self._sync_enabled()

    def _sync_enabled(self) -> None:
        on = self.chk_save.isChecked() and not self._read_only
        self.chk_save.setEnabled(not self._read_only)
        for widget in (self.edit_label, self.combo_type, self.radio_all, self.radio_selected):
            widget.setEnabled(on)
        self.btn_choose.setEnabled(on and self.radio_selected.isChecked())

        if not self.chk_save.isChecked():
            self.lbl_scope.setText("")
        elif self.radio_all.isChecked():
            self.lbl_scope.setText("Every channel that passes the type filter.")
        else:
            self.lbl_scope.setText(
                f"{len(self._selected_identities)} channel(s) selected."
            )
