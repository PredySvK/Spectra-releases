"""
"Split a chip…" (#1033): the editor step 3 opens to cut one chip into pieces.
It shows the chip's value of every sample, one per line. A click between two
characters of the first value offers the cuts that fit every sample (the first
fitting one is the default, the others are greyed out with the reason), a
double click on a word offers to cut it out. The cuts are a list with ✕, and
every sample's line shows the pieces they make as they stand, or is red with
why a cut does not fit it.
"""

from typing import Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QToolButton, QVBoxLayout,
)

from core.import_template import ChipCut
from view_models.import_template import (
    CutOffer, build_cut_offers, build_word_cut_offer, resolve_cut_label, resolve_cut_pieces, resolve_default_offer,
)

from ._sample_grid import RED


class _ValueEdit(QLineEdit):
    """The first value, read only: `split_at` is a click between two characters, `word_selected` a double click on a word."""

    split_at = Signal(int)
    word_selected = Signal(int, int)

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setToolTip("click between two characters to cut there · double click a word to cut it out")

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if not self.hasSelectedText():
            self.split_at.emit(self.cursorPositionAt(event.position().toPoint()))

    def mouseDoubleClickEvent(self, event) -> None:
        super().mouseDoubleClickEvent(event)
        if self.hasSelectedText():
            self.word_selected.emit(self.selectionStart(), self.selectionEnd())


class CutDialog(QDialog):
    """The own cuts of one chip, given its values in the samples; `cuts()` is the result once accepted."""

    def __init__(self, values: Sequence[str], existing: Sequence[ChipCut] = (), parent=None):
        super().__init__(parent)
        self.values = tuple(values)
        self._cuts = list(existing)
        self.setWindowTitle("Split a chip")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("The chip's value in each sample. Click between two characters of the first one "
                                "to cut there; double click a word to cut it out."))
        self.first = _ValueEdit(self.values[0] if self.values else "")
        self.first.split_at.connect(self._on_click)
        self.first.word_selected.connect(self._on_word)
        layout.addWidget(self.first)
        self.cut_list = QVBoxLayout()
        layout.addLayout(self.cut_list)
        self.samples = QVBoxLayout()
        layout.addLayout(self.samples)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._redraw()

    def cuts(self) -> Tuple[ChipCut, ...]:
        return tuple(self._cuts)

    # ---- the user's clicks ------------------------------------------------------------------

    def _on_click(self, at: int) -> None:
        self._offer(build_cut_offers(self.values, at))

    def _on_word(self, start: int, end: int) -> None:
        offer = build_word_cut_offer(self.values, start, end)
        if offer is not None:
            self._offer((offer,))

    def _offer(self, offers: Sequence[CutOffer]) -> None:
        """The offers as a menu (the first fitting one bold): a fitting one is added, a greyed one says why not."""
        if not offers:
            return
        menu, default = QMenu(self), resolve_default_offer(offers)
        for offer in offers:
            action = menu.addAction(offer.label if offer.is_fitting else f"{offer.label}  — {offer.problem}")
            action.setEnabled(offer.is_fitting)
            if offer is default:
                menu.setDefaultAction(action)
                font = action.font()
                font.setBold(True)
                action.setFont(font)
            action.triggered.connect(lambda _=False, cut=offer.cut: self.add_cut(cut))
        menu.exec(self.cursor().pos())

    def add_cut(self, cut: ChipCut) -> None:
        if cut not in self._cuts:
            self._cuts.append(cut)
            self._redraw()

    def remove_cut(self, index: int) -> None:
        if 0 <= index < len(self._cuts):
            del self._cuts[index]
            self._redraw()

    # ---- what is shown ---------------------------------------------------------------------------

    @staticmethod
    def _clear(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _redraw(self) -> None:
        self._clear(self.cut_list)
        self._clear(self.samples)
        for index, cut in enumerate(self._cuts):
            row = QFrame()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(QLabel(resolve_cut_label(cut)))
            cross = QToolButton()
            cross.setText("✕")
            cross.setAutoRaise(True)
            cross.setToolTip("take this cut off")
            cross.clicked.connect(lambda _=False, index=index: self.remove_cut(index))
            line.addWidget(cross)
            line.addStretch(1)
            self.cut_list.addWidget(row)
        for value in self.values:
            pieces, problem = resolve_cut_pieces(value, self._cuts) if self._cuts else ((value,), "")
            label = QLabel(f"<span style='color:{RED}'>{problem}</span>" if problem
                           else f"{value}  →  " + " · ".join(f"<b>{piece}</b>" for piece in pieces))
            self.samples.addWidget(label)
