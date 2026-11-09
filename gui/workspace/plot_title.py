"""
The plot title above a graph: wrapped to the plot's width, never wider than its dock (#999).

pyqtgraph's title label takes the width of its text on one line as its minimum width, so a long
curve label would push the plot past the dock. `set_plot_title` is the only way a title is set:
the label gets no minimum width, its text wraps (anywhere, if a word does not fit) to the width
the layout gives it, and what does not fit in `MAX_TITLE_LINES` is cut with "…" and shown whole
in the tooltip.
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QTextDocument, QTextOption

MAX_TITLE_LINES = 3
_ELLIPSIS = "…"
_ONE_LINE_ROW = 30  # PlotItem.setTitle's fixed height of the title row


def set_plot_title(plot_widget: pg.PlotWidget, text: str) -> None:
    """Sets the plot title of `plot_widget`; it wraps to the plot's width (at most 3 lines)."""
    plot_item = plot_widget.getPlotItem()
    plot_item.setTitle(text)
    label = plot_item.titleLabel
    state = getattr(label, "_wrap_state", None)
    if state is None:
        state = _Wrap(plot_item)
        label._wrap_state = state
        label.updateMin = state.update  # LabelItem.resizeEvent ends in updateMin(): re-wrap there
    state.text = text
    state.applied = None
    state.update()


class _Wrap:
    def __init__(self, plot_item: pg.PlotItem) -> None:
        self._plot_item = plot_item
        self.text = ""
        self.applied: tuple[str, int] | None = None  # (text, width) the label shows now

    def update(self) -> None:
        label = self._plot_item.titleLabel
        width = int(label.geometry().width())
        if width <= 0 or not label.isVisible():
            self._set_size(label)
            return
        if self.applied != (self.text, width):
            self.applied = (self.text, width)
            shown = _fit(self.text, _drawn_font(label), width)
            if shown != label.item.toPlainText():
                label.setText(shown)  # re-enters update(): `applied` already matches
            label.setToolTip("" if shown == self.text else self.text)
            label.item.document().setDefaultTextOption(_wrap_anywhere())
            label.item.setTextWidth(width)
        self._set_size(label)

    def _set_size(self, label: pg.LabelItem) -> None:
        height = max(label.itemRect().height(), _ONE_LINE_ROW)
        label.setMinimumWidth(0)
        label.setMinimumHeight(height)
        label.setMaximumHeight(height)
        self._plot_item.layout.setRowFixedHeight(0, height)


def _drawn_font(label: pg.LabelItem):
    """The font the label's HTML span draws with (pyqtgraph sets its size per span, not on the item)."""
    fragments = label.item.document().begin().begin()
    return fragments.fragment().charFormat().font() if not fragments.atEnd() else label.item.font()


def _wrap_anywhere() -> QTextOption:
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    return option


def _line_count(text: str, font, width: int) -> int:
    doc = QTextDocument()
    doc.setDefaultFont(font)
    doc.setDefaultTextOption(_wrap_anywhere())
    doc.setTextWidth(width)
    doc.setPlainText(text)
    doc.size()  # lays the text out; block layouts have no lines before that
    block, lines = doc.begin(), 0
    while block.isValid():
        lines += block.layout().lineCount()
        block = block.next()
    return lines


def _fit(text: str, font, width: int) -> str:
    """`text`, or its longest start that fits `MAX_TITLE_LINES` lines of `width` with a "…"."""
    if _line_count(text, font, width) <= MAX_TITLE_LINES:
        return text
    low, high = 0, len(text)  # longest prefix that still fits
    while low < high:
        mid = (low + high + 1) // 2
        if _line_count(text[:mid].rstrip() + _ELLIPSIS, font, width) <= MAX_TITLE_LINES:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + _ELLIPSIS
