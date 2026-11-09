"""
How step 3 of the wizard draws a role: its colour, a chip in a slot, and
the chips with a role inside a text (a header cell, or the sheet / file /
folder text above the preview) -- a tint and a border of the role, two roles as
two bands. When a text does not fit, its plain runs shrink to "…" first, so the
chips with a role stay in sight. Tints are laid over the theme, so the text
keeps the theme's colour on a dark theme too.
"""

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QAbstractButton, QApplication

from core.import_template import ROLE_AXIS, ROLE_FIELDS, ROLE_NAME, ROLE_ORDER, ROLE_SAMPLE_RATE

ROLE_COLORS = {ROLE_NAME: "#4f8ef7", ROLE_AXIS: "#a66cf0", ROLE_ORDER: "#f0953a", ROLE_SAMPLE_RATE: "#d14d72",
               ROLE_FIELDS: "#3fb37a"}
ROLE_LABELS = {ROLE_NAME: "Channel name", ROLE_AXIS: "Axis", ROLE_ORDER: "Order", ROLE_SAMPLE_RATE: "Sample rate",
               ROLE_FIELDS: "Metadata"}
_TINT = 85
_TINT_BANDS = 140

# (start, end, role kinds) of a chip with a role in a text.
Mark = Tuple[int, int, Tuple[str, ...]]
_KEEP_AROUND_ELLIPSIS = ",:;\\- "


def role_tint(kind: str, alpha: int = _TINT) -> QColor:
    color = QColor(ROLE_COLORS[kind])
    color.setAlpha(alpha)
    return color


def role_tint_over_base(kind: str, alpha: int = _TINT) -> str:
    """The tint as an opaque colour over the theme's base, for rich text, which knows no alpha."""
    color, base, share = QColor(ROLE_COLORS[kind]), QApplication.palette().color(QPalette.ColorRole.Base), alpha / 255
    return QColor(*(round(own * share + under * (1 - share)) for own, under in
                    ((color.red(), base.red()), (color.green(), base.green()), (color.blue(), base.blue())))).name()


def role_chip_style(kind: str, *, picking: bool = False, dashed: bool = False) -> str:
    """A slot chip (or the "+ pick" button) of a role, as a style sheet for a QToolButton or QFrame."""
    tint = role_tint(kind, 60)
    width = 3 if picking else 2 if dashed else 1        # the "+ Pick" button stands out from the chips
    return (f"border: {width}px {'dashed' if dashed else 'solid'} {ROLE_COLORS[kind]};"
            f" border-radius: 9px; padding: 2px 8px;"
            f" background: rgba({tint.red()},{tint.green()},{tint.blue()},{60 if not dashed else 0});")


def _runs(text: str, marks: Sequence[Mark]) -> List[list]:
    """The text as runs [piece, kinds or None] -- the marked chips and the plain text between them."""
    runs, at = [], 0
    by_start = {start: (end, kinds) for start, end, kinds in marks if 0 <= start < end <= len(text)}
    while at < len(text):
        if at in by_start:
            end, kinds = by_start[at]
            runs.append([text[at:end], kinds])
            at = end
        else:
            following = min([start for start in by_start if start > at] + [len(text)])
            runs.append([text[at:following], None])
            at = following
    return runs


def paint_role_chips(painter: QPainter, rect: QRect, text: str, marks: Sequence[Mark], font: QFont,
                     text_color: QColor) -> None:
    """`text` drawn left to right in `rect`, every marked chip with its role tint and border behind it."""
    painter.save()
    painter.setClipRect(rect)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    x, middle = rect.left() + 4, rect.center().y()
    height = metrics.height() + 2
    top = middle - height // 2
    baseline = middle + metrics.ascent() / 2 - 1
    runs = _runs(text, marks)

    def width_of() -> int:
        return sum(metrics.horizontalAdvance(piece) + (7 if kinds else 0) for piece, kinds in runs)

    while width_of() > rect.width() - 8:
        plain = [run for run in runs if run[1] is None and len(run[0].strip()) > 3]
        if not plain:
            break
        longest = max(plain, key=lambda run: len(run[0]))
        lead = longest[0][:1] if longest[0][:1] in _KEEP_AROUND_ELLIPSIS else ""
        tail = longest[0][-1:] if longest[0][-1:] in _KEEP_AROUND_ELLIPSIS else ""
        longest[0] = f"{lead}…{tail}"
    for piece, kinds in runs:
        if not kinds:
            painter.setPen(text_color)
            painter.drawText(QPointF(x, baseline), piece)
            x += metrics.horizontalAdvance(piece)
            continue
        width = metrics.horizontalAdvance(piece) + 6
        box = QRectF(x - 1, top, width, height)
        path = QPainterPath()
        path.addRoundedRect(box, 5, 5)
        # Two roles: two bands, each with its own tint and its own stretch of the border, so the
        # colours do not blend into one; the tint is stronger then, a half-height band reads less.
        band = box.height() / len(kinds)
        tint = _TINT if len(kinds) == 1 else _TINT_BANDS
        for number, kind in enumerate(kinds):
            strip = QRectF(box.left() - 1, box.top() + number * band, box.width() + 2, band + 0.5)
            painter.save()
            painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
            painter.fillRect(strip, role_tint(kind, tint))
            painter.restore()
            painter.save()
            painter.setClipRect(strip.adjusted(0, -0.5 if number else -1, 0, 0 if number < len(kinds) - 1 else 1),
                                Qt.ClipOperation.IntersectClip)
            painter.setPen(QPen(QColor(ROLE_COLORS[kind]), 1.5 if len(kinds) > 1 else 1))
            painter.drawPath(path)
            painter.restore()
        painter.setPen(text_color)
        painter.drawText(QPointF(x + 2, baseline), piece)
        x += width + 1
    painter.restore()


class RoleTextButton(QAbstractButton):
    """"File: TEST65NmA_H1" above the preview, its chips with a role marked like the header cells."""

    def __init__(self, label: str, text: str, marks: Sequence[Mark], selected: bool, parent=None):
        super().__init__(parent)
        self.label, self.shown_text, self.marks, self.selected = label, text, tuple(marks), selected
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        metrics = QFontMetrics(self.font())
        self.setFixedHeight(metrics.height() + 10)
        self.setMinimumWidth(metrics.horizontalAdvance(f"{label}: {text}") + 30)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        frame = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Highlight) if self.selected
                            else palette.color(QPalette.ColorRole.Mid), 2 if self.selected else 1))
        painter.drawRoundedRect(frame, 4, 4)
        metrics = QFontMetrics(self.font())
        prefix = f"{self.label}: "
        painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(QPointF(6, self.rect().center().y() + metrics.ascent() / 2 - 1), prefix)
        rest = self.rect().adjusted(6 + metrics.horizontalAdvance(prefix) - 4, 0, 0, 0)
        paint_role_chips(painter, rest, self.shown_text, self.marks, self.font(),
                         palette.color(QPalette.ColorRole.WindowText))


def resolve_shifted_marks(cell_text: str, text: str, marks: Sequence[Mark]) -> Optional[Tuple[Mark, ...]]:
    """The marks of `text` moved to where it is in the cell's text (a heading cell keeps its "(unit)"); None when it is not there."""
    at = cell_text.find(text) if text else -1
    if at < 0:
        return None
    return tuple((start + at, end + at, kinds) for start, end, kinds in marks)
