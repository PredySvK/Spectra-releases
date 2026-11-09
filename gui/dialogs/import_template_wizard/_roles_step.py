"""
Step 3 of the wizard, "Texts → roles" (#1031): a slot per role -- Channel
name, Axis, Order (an order cut), Sample rate (a time signal whose rate is in a
text) -- filled first by the guess from how the chips change, and the table of
what the roles make of every channel, which goes under the preview.

"+ Pick" (first in its slot) arms a slot; a click on a header cell or on the Sheet /
File / Folder text above the grid then offers that text's chips. Without an
armed slot the click offers every role for every chip. ✕ on a slot chip takes
only that one role. Name chips go in text order and are dragged to another
place; "‿" between two says the text between them stays, and the axis is the
locked last chip. Everything here reads the newest preview's chips and hands
each change to TemplateWizardJobs; the role results are cheap, so they are
redrawn on the GUI thread at once.
"""

import os
from typing import Optional, Tuple

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QTableWidget,
    QToolButton, QVBoxLayout, QWidget,
)

from core.import_template import (
    SOURCE_HEADER, ROLE_AXIS, ROLE_FIELDS, ROLE_NAME, ROLE_ORDER, ChipRef, MetadataField,
)
from io_modules.import_template import NAME_JOIN, resolve_axis_text, resolve_chip_label, resolve_text_source_label
from orchestration.import_template import TemplateWizardJobs
from view_models.import_template import (
    CHIP_BETWEEN_FILES, CHIP_BETWEEN_SHEETS, CHIP_IN_COLUMNS, CHIP_MISSING, CHIP_SAME, SampleChips,
    SampleRoles, build_field_offer, resolve_channel_roles, resolve_chip_anchor, resolve_chip_kinds, resolve_chip_values,
    resolve_name_joins, resolve_role_ref,
)

from ._choices import fill_result_table
from ._cut_dialog import CutDialog
from ._field_dialog import FieldDialog
from ._role_chips import ROLE_COLORS, ROLE_LABELS, role_chip_style, role_tint_over_base
from ._sample_grid import RED, SampleGridPane, muted_color

_NAME_CHIP_MIME = "application/x-spectra-name-chip"
_CHANGES = {
    CHIP_IN_COLUMNS: "changes in the columns",
    CHIP_BETWEEN_SHEETS: "changes between the sheets",
    CHIP_BETWEEN_FILES: "changes between the files",
    CHIP_SAME: "the same everywhere",
    CHIP_MISSING: "missing somewhere",
}
_SLOT_NAMES = {ROLE_NAME: "WizardSlotName", ROLE_AXIS: "WizardSlotAxis", ROLE_ORDER: "WizardSlotOrder",
               ROLE_FIELDS: "WizardSlotMetadata"}
_ONE_SAMPLE_SAME = "one value in this sample"


def _field_text(field: MetadataField, value) -> str:
    """A field's value as the slot and the result table show it: a number with its unit, "" when the channel has none."""
    if value is None:
        return ""
    return f"{value:g} {field.unit}".strip() if isinstance(value, float) else str(value)


def _source_label(ref: ChipRef, heading_row: int) -> str:
    """Where a chip's text is: a header row by its number on the selected channel's sheet, else as the reader names it."""
    if ref.source != SOURCE_HEADER:
        return resolve_text_source_label(ref)
    return f"row {heading_row - ref.row_above + 1}" + (" (the heading row)" if ref.row_above == 0 else "")


class _NameChip(QFrame):
    """A name chip in its slot: dragged to another place of the name, ✕ takes it out of the name."""

    removed = Signal()

    def __init__(self, index: int, text: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.index = index
        self._pressed: Optional[QPoint] = None
        self.setObjectName("chip")
        self.setStyleSheet(f"QFrame#chip {{ {role_chip_style(ROLE_NAME)} }}")
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tooltip + "\ndrag = another place in the name · ✕ = out of the name · right click = split")
        line = QHBoxLayout(self)
        line.setContentsMargins(4, 0, 0, 0)
        line.addWidget(QLabel(text))
        cross = QToolButton()
        cross.setText("✕")
        cross.setAutoRaise(True)
        cross.clicked.connect(self.removed.emit)
        line.addWidget(cross)

    def mousePressEvent(self, event) -> None:
        self._pressed = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pressed is None or (event.position().toPoint() - self._pressed).manhattanLength() \
                < QApplication.startDragDistance():
            return
        self._pressed = None
        mime = QMimeData()
        mime.setData(_NAME_CHIP_MIME, str(self.index).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.exec(Qt.DropAction.MoveAction)


class _NameRow(QWidget):
    """The name slot's line; a name chip dropped on it goes where it was dropped."""

    moved = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.line = QHBoxLayout(self)
        self.line.setContentsMargins(0, 0, 0, 0)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_NAME_CHIP_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_NAME_CHIP_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        index = int(bytes(event.mimeData().data(_NAME_CHIP_MIME)).decode())
        x = event.position().x()
        others = [chip for chip in self.findChildren(_NameChip) if chip.index != index]
        to = sum(1 for chip in others if chip.geometry().center().x() < x)
        event.acceptProposedAction()
        if to != index:
            self.moved.emit(index, to)


class RoleResults(QTableWidget):
    """What the roles make of every channel, under the preview; a click on a row is `channel_selected`."""

    channel_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)
        self.cellClicked.connect(lambda row, _column: self.channel_selected.emit(row))

    def show_results(self, rows, labels, selected: int) -> None:
        self.blockSignals(True)
        fill_result_table(self, labels, rows, RED)
        self.blockSignals(False)
        self.select_channel(selected)

    def select_channel(self, channel: int) -> None:
        """Marks a channel's row without telling `channel_selected`."""
        self.blockSignals(True)
        if 0 <= channel < self.rowCount():
            self.selectRow(channel)
        self.blockSignals(False)


class RolesStep(QWidget):
    """Step 3: the role slots over the preview `grid`; `results` is the table the dialog puts under the preview."""

    def __init__(self, jobs: TemplateWizardJobs, grid: SampleGridPane, parent=None):
        super().__init__(parent)
        self.jobs, self.grid = jobs, grid
        self.selected = 0
        self.picking: Optional[str] = None
        self._results_key = None
        self._order_edit: Optional[QLineEdit] = None
        self._order_typing: Optional[Tuple[str, int]] = None      # (text, cursor) of the order field being typed in
        layout = QVBoxLayout(self)
        self.slots_box = QFrame()
        self.slots_box.setFrameShape(QFrame.Shape.StyledPanel)
        self.slots = QGridLayout(self.slots_box)
        self.slots.setColumnStretch(1, 1)
        layout.addWidget(self.slots_box)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color:{RED}; font-weight:bold;")
        layout.addWidget(self.warning)
        self.status = QLabel()
        self.status.setObjectName("WizardRolesHint")  # Help figure target
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.results = RoleResults()
        self.results.setObjectName("WizardRoleResults")  # Help figure target
        self.results.channel_selected.connect(self.select_channel)
        grid.text_clicked.connect(self._on_text)
        grid.channel_clicked.connect(self.select_channel)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=lambda: self._pick(None))
        self.escape.setContext(Qt.ShortcutContext.WindowShortcut)
        self.escape.setEnabled(False)

    # ---- what is shown -------------------------------------------------------------------

    @property
    def chips(self) -> Optional[SampleChips]:
        preview = self.jobs.preview
        return preview.chips if preview is not None else None

    @property
    def roles(self) -> SampleRoles:
        wizard = self.jobs.wizard
        return wizard.roles if wizard is not None and wizard.roles is not None else SampleRoles()

    def describe(self, ref: ChipRef) -> str:
        """How a chip changes across the samples, as its tooltip says it."""
        chips, wizard = self.chips, self.jobs.wizard
        change = chips.resolve_change(ref) if chips is not None else None
        if change is None:
            return ""
        if change.change == CHIP_SAME and wizard is not None and wizard.is_single_sample:
            return _ONE_SAMPLE_SAME
        return _CHANGES[change.change]

    def refresh(self) -> None:
        """Draws the slots, the marks in the preview and the results of the newest chips and the wizard's roles."""
        wizard, chips = self.jobs.wizard, self.chips
        if wizard is None or chips is None or not chips.channels:
            self._clear_slots()
            self.status.setText("The texts are being split into chips…" if wizard is not None else "")
            self.results.show_results([], [], -1)
            self._results_key = None
            return
        self.selected = min(max(self.selected, 0), len(chips.channels) - 1)
        template, roles = wizard.template, self.roles
        self._clear_slots()
        for row, kind in enumerate(self._offered_kinds()):
            head = QLabel(f"<b>{ROLE_LABELS[kind]}</b>")
            head.setStyleSheet(f"color:{ROLE_COLORS[kind]};")
            self.slots.addWidget(head, row, 0)
            slot = self._slot(kind, chips, roles, template)
            slot.setObjectName(_SLOT_NAMES[kind])  # Help figure target
            self.slots.addWidget(slot, row, 1)
        self.warning.setText("⚠ The axis chip is also in the name, so the axis would be in the name twice: "
                             "take it out of the name." if roles.is_axis_in_name else "")
        self.warning.setVisible(roles.is_axis_in_name)
        channel = chips.channels[self.selected]
        if self.picking:
            self.status.setText(f"Picking the <b>{ROLE_LABELS[self.picking]}</b>: click a header cell, or the "
                                f"Sheet / File / Folder text above the preview, and choose the chip (Esc: stop).")
        else:
            self.status.setText(
                f"<span style='color:{muted_color().name()}'>The slots show the selected channel "
                f"({os.path.basename(channel.path)} › {channel.sheet}, column {channel.y_column + 1}). A click on a "
                f"text in the preview offers its chips; a click on a row of the table selects its channel.</span>")
        self.grid.show_roles(chips, roles, self.selected, self.describe, self._offered_kinds())
        self._show_results(wizard, chips, template)
        if self._order_typing is not None and self._order_edit is not None:
            text, cursor = self._order_typing
            self._order_edit.setText(text)
            self._order_edit.setFocus()
            self._order_edit.setCursorPosition(cursor)
        self._order_typing = None

    def _clear_slots(self) -> None:
        edit = self._order_edit
        # The slots are rebuilt on every change, typing the order too: its field keeps what is typed in it.
        self._order_typing = (edit.text(), edit.cursorPosition()) if edit is not None and edit.hasFocus() else None
        self._order_edit = None
        while self.slots.count():
            widget = self.slots.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()

    def _chip_text(self, chips: SampleChips, ref: ChipRef) -> str:
        text_chips = chips.resolve_chips(self.selected, ref.source_key)
        index = text_chips.resolve_index(ref)
        return text_chips.chips[index].text if index is not None else "∅"

    def _chip_tooltip(self, chips: SampleChips, ref: ChipRef) -> str:
        heading = chips.channels[self.selected].heading_row
        return f"from {_source_label(ref, heading)}, {resolve_chip_label(ref)} · {self.describe(ref)}"

    def _slot(self, kind: str, chips: SampleChips, roles: SampleRoles, template) -> QWidget:
        box = _NameRow() if kind == ROLE_NAME else QWidget()
        line = box.line if kind == ROLE_NAME else QHBoxLayout(box)
        line.setContentsMargins(0, 0, 0, 0)
        refs = roles.resolve_refs(kind)
        if kind == ROLE_NAME:
            box.moved.connect(self.jobs.move_name_chip)
            joins = resolve_name_joins(chips, roles, self.selected)
            for index, ref in enumerate(refs):
                if index:
                    joiner = QLabel("‿" if joins[index - 1] else NAME_JOIN)
                    joiner.setToolTip("next to each other in the text: the text between them stays" if joins[index - 1]
                                      else f"joined by '{NAME_JOIN}'")
                    line.addWidget(joiner)
                chip = _NameChip(index, self._chip_text(chips, ref), self._chip_tooltip(chips, ref))
                chip.removed.connect(lambda ref=ref: self.jobs.remove_chip_role(ROLE_NAME, ref))
                self._offer_menu_on_right_click(chip, ROLE_NAME, ref)
                line.addWidget(chip)
            if roles.axis is not None:
                line.addWidget(QLabel(NAME_JOIN))
                locked = QLabel(f"🔒 {resolve_axis_text(self._chip_text(chips, roles.axis))}")
                locked.setStyleSheet(f"border:1px solid {ROLE_COLORS[ROLE_AXIS]}; border-radius:9px; "
                                     f"padding:2px 8px; background:{role_tint_over_base(ROLE_AXIS, 40)};")
                locked.setToolTip("The axis is always the last part of the name.")
                line.addWidget(locked)
            result = resolve_channel_roles(template, chips, self.selected)
            shown = (f"<b>{result.name}</b>" if not result.problem
                     else f"<span style='color:{RED}'>{result.problem}</span>")
            line.addWidget(QLabel(f"  =  {shown}"))
        elif kind == ROLE_FIELDS:
            values = dict(resolve_channel_roles(template, chips, self.selected).metadata)
            for field in roles.fields:
                line.addWidget(self._field_chip(field, values.get(field.field)))
        else:
            for ref in refs:
                chip = QToolButton()
                chip.setText(f"{self._chip_text(chips, ref)}   ✕")
                chip.setToolTip(self._chip_tooltip(chips, ref) + "\nclick = take this role off · right click = more")
                self._offer_menu_on_right_click(chip, kind, ref)
                chip.setStyleSheet(f"QToolButton {{ {role_chip_style(kind)} }}")
                chip.clicked.connect(lambda _=False, ref=ref: self.jobs.remove_chip_role(kind, ref))
                line.addWidget(chip)
        pick = QToolButton()
        pick.setText("… click a text in the preview (Esc: stop)" if self.picking == kind else "+ Pick")
        pick.setToolTip("Pick a chip for this slot: click a text in the preview")
        pick.setStyleSheet(f"QToolButton {{ {role_chip_style(kind, picking=self.picking == kind, dashed=True)} }}")
        pick.clicked.connect(lambda _=False: self._pick(None if self.picking == kind else kind))
        line.insertWidget(0, pick)      # first in the slot, where it does not move as chips come and go
        if kind == ROLE_ORDER:
            line.addWidget(QLabel("  or the same for all:"))
            fixed = QLineEdit(f"{roles.fixed_order:g}" if roles.fixed_order > 0 else "")
            fixed.setMaximumWidth(70)
            fixed.setToolTip("One order for every channel, used while no chip is the order")
            fixed.textEdited.connect(self._fix_order)       # every keystroke counts, no Enter needed
            line.addWidget(fixed)
            self._order_edit = fixed
        line.addStretch(1)
        return box

    def _field_chip(self, field: MetadataField, value) -> QWidget:
        """A field in the slot: its name and the selected channel's value; a click edits it, ✕ takes it off."""
        frame = QFrame()
        frame.setObjectName("chip")
        frame.setStyleSheet(f"QFrame#chip {{ {role_chip_style(ROLE_FIELDS)} }}")
        line = QHBoxLayout(frame)
        line.setContentsMargins(0, 0, 0, 0)
        edit = QToolButton()
        edit.setText(f"{field.field} = {_field_text(field, value)}")
        edit.setAutoRaise(True)
        edit.setToolTip("click = edit the field")
        edit.clicked.connect(lambda _=False: self._edit_field(field.chip, field))
        self._offer_menu_on_right_click(edit, ROLE_FIELDS, field.chip)
        line.addWidget(edit)
        cross = QToolButton()
        cross.setText("✕")
        cross.setAutoRaise(True)
        cross.setToolTip("take this field off")
        cross.clicked.connect(lambda _=False: self.jobs.remove_field(field.field))
        line.addWidget(cross)
        return frame

    def _edit_field(self, ref: ChipRef, existing: Optional[MetadataField] = None) -> None:
        """Asks for the name, value and kind of a field from this chip, then hands it to the wizard."""
        chips = self.chips
        if chips is None:
            return
        dialog = FieldDialog(ref, build_field_offer(chips, ref), existing, self)
        if dialog.exec():
            self.jobs.set_field(dialog.field())

    def _offer_menu_on_right_click(self, widget: QWidget, kind: str, ref: ChipRef) -> None:
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(lambda _pos: self._slot_chip_menu(kind, ref).exec(self.cursor().pos()))

    def _slot_chip_menu(self, kind: str, ref: ChipRef) -> QMenu:
        """A slot chip's menu: split it, and -- in a text whose chip count varies -- count it from the other end."""
        menu = QMenu(self)
        menu.addAction("Split this chip…").triggered.connect(lambda _=False: self.split_chip(ref))
        chips = self.chips
        if chips is not None and not ref.piece and chips.is_counted_from_either_end(ref.source_key):
            label = "Count from the start" if ref.chip < 0 else "Count from the end"
            action = menu.addAction(label)
            action.setToolTip("The headers have different numbers of chips; the chip is now counted "
                              + ("from the end of its text." if ref.chip < 0 else "from the start of its text."))
            action.triggered.connect(
                lambda _=False: self.jobs.count_chip_from_other_end(kind, ref, self.selected))
        return menu

    def split_chip(self, ref: ChipRef) -> None:
        """Opens the editor of the own cuts of the delimiter chip `ref` is a piece of; what it says goes to the wizard."""
        chips, wizard = self.chips, self.jobs.wizard
        if chips is None or wizard is None:
            return
        chip = chips.resolve_position(ref, self.selected) if ref.chip < 0 else ref.chip    # cuts count from the start
        if chip is None:
            return
        texts = [channel.resolve_text(ref.source_key) for channel in chips.channels]
        values = resolve_chip_values(chips.sources, texts, ref.source_key, chip)
        if not values:
            return
        dialog = CutDialog(values, wizard.resolve_chip_cuts(ref.source_key, chip), self)
        if dialog.exec():
            self.jobs.set_chip_cuts(ref.source_key, chip, dialog.cuts())

    def _show_results(self, wizard, chips: SampleChips, template) -> None:
        kinds = wizard.resolve_role_kinds()
        ordered, rated = ROLE_ORDER in kinds, wizard.is_rate_from_text
        if self._results_key is not None and self._results_key[1] is chips and self._results_key[0] == template:
            self.results.select_channel(self.selected)      # the same roles on the same chips: nothing to recount
            return
        self._results_key = (template, chips)
        fields = template.metadata_fields
        labels = (["File", "Sheet", "Channel"] + (["Order"] if ordered else []) + (["Sample rate"] if rated else [])
                  + [field.field for field in fields] + ["Problem"])
        rows = []
        for number, channel in enumerate(chips.channels):
            result = resolve_channel_roles(template, chips, number)
            order = [f"{result.order:g}" if result.order is not None else ""] if ordered else []
            rate = [result.sample_rate_text] if rated else []
            values = dict(result.metadata)
            rows.append(([os.path.basename(channel.path), channel.sheet, result.name] + order + rate
                         + [_field_text(field, values.get(field.field)) for field in fields] + [result.problem],
                         bool(result.problem)))
        self.results.show_results(rows, labels, self.selected)

    # ---- the user's clicks -----------------------------------------------------------------

    def select_channel(self, channel: int) -> None:
        """Selects a channel: the slots show its chips and the preview its sheet; the result is redrawn at once."""
        chips = self.chips
        if chips is None or not 0 <= channel < len(chips.channels):
            return
        self.selected = channel
        found = chips.channels[channel]
        self.grid.show_sheet((found.path, found.sheet),
                             tuple(column for column in (found.x_column, found.y_column) if column >= 0))
        self.refresh()

    def stop_picking(self) -> None:
        if self.picking is not None:
            self._pick(None)

    def _pick(self, kind: Optional[str]) -> None:
        self.picking = kind
        self.escape.setEnabled(kind is not None)
        self.refresh()

    def _fix_order(self, text: str) -> None:
        try:
            order = float(text.replace(",", ".")) if text.strip() else 0.0
        except ValueError:
            self.status.setText(f"<span style='color:{RED}'>'{text}' is not a number.</span>")
            return
        if order != self.roles.fixed_order:
            self.jobs.fix_order(order)

    def _on_text(self, channel: int, key) -> None:
        """A click on a text in the preview: its chips, for the armed slot or for any role."""
        chips = self.chips
        if chips is None:
            return
        if channel != self.selected:
            self.select_channel(channel)
        found = chips.resolve_chips(channel, key).chips
        if not found:
            return
        roles, menu = self.roles, QMenu(self)
        kind = self.picking
        if kind is not None:
            title = menu.addAction(f"Which chip is the {ROLE_LABELS[kind]}?")
            title.setEnabled(False)
        for chip in found:
            ref = ChipRef(key[0], key[1], chip.chip, chip.piece)
            held = ", ".join(ROLE_LABELS[other] for other in resolve_chip_kinds(chips, roles, channel, ref))
            label = f"{chip.text}    — {self.describe(ref)}" + (f"   (now: {held})" if held else "")
            if kind is not None:
                menu.addAction(label).triggered.connect(lambda _=False, ref=ref: self._give(kind, ref))
                continue
            sub = menu.addMenu(label)
            for other in self._offered_kinds():
                own = resolve_role_ref(chips, roles, other, channel, ref)     # the role's ref may count from the end
                action = sub.addAction(ROLE_LABELS[other])
                action.setCheckable(True)
                action.setChecked(own is not None)
                action.triggered.connect(lambda checked, ref=ref, own=own, other=other: (
                    self._set_role(other, ref) if checked else self.jobs.remove_chip_role(other, own or ref)))
        menu.addSeparator()
        for chip_number in dict.fromkeys(chip.chip for chip in found):      # a piece is split as its whole chip
            menu.addAction(f"Split chip {chip_number + 1}…").triggered.connect(
                lambda _=False, chip_number=chip_number: self.split_chip(ChipRef(key[0], key[1], chip_number)))
        menu.exec(self.cursor().pos())

    def _offered_kinds(self) -> Tuple[str, ...]:
        wizard = self.jobs.wizard
        return wizard.resolve_role_kinds() if wizard is not None else ()

    def _give(self, kind: str, ref: ChipRef) -> None:
        self.picking = None
        self.escape.setEnabled(False)
        self._set_role(kind, ref)

    def _set_role(self, kind: str, ref: ChipRef) -> None:
        """Gives the chip `ref` names in the selected channel's text a role, counted from whichever end reads better."""
        if kind == ROLE_FIELDS:
            chips = self.chips
            if chips is not None:       # a field needs its name and value first, from the chip it will take
                self._edit_field(resolve_chip_anchor(chips, ROLE_FIELDS, ref, self.selected))
        else:
            self.jobs.set_chip_role(kind, ref, self.selected)
