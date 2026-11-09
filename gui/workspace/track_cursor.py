# =====================================================================
# FILE: gui/workspace/track_cursor.py
# =====================================================================
"""
Track cursor on GraphDock: a vertical line and the Track table over a curve
graph (CONTEXT.md "Track cursor", "Track table").

Where the line stands, each curve's value there and what the table says are
decided in view_models.track_cursor; this module draws the line (a
``pg.InfiniteLine``) and the table (a ``GraphOverlay``), turns a drag of the line
into a new X. With the Track cursor pin off the line follows the mouse through
CursorMixin's one hover gate (no second SignalProxy; ``_init_track_cursor``
adds its step there) and takes no mouse button, so zoom and the Cursor keep
the mouse. Mixed into GraphDock only: a spectrogram or an empty graph shows
neither, without a word; the `T` shortcut lives with `C` in CursorMixin, so it
flips the tool from any dock.

Runs synchronously on the GUI thread: it reads only curves already
in memory, never the disk, and the numbers must keep up with the line. The
curves are prepared once per redraw (X monotonicity, metadata, columns,
units); a move of the line only interpolates each curve at one X.

The table always fits the graph: gui measures how many curve lines and columns
fit the ViewBox and build_track_table turns the rest into "… and N more" and
"+N columns". It can be dragged (a GraphOverlay, no auto-range, #579); a dragged
table stays where the user put it until the tool is switched off.

The Track cursor highlight (CONTEXT.md) puts a solid dot in the curve's colour
where the line crosses each drawn curve: one scatter item per ViewBox (main and
the right Y axis), above the curves and the line. A curve gets a dot exactly when
resolve_track_value reads it at the line's X, the read the Track table makes, so
dots and table agree, also for rows the table folds away. The dots are put
wherever the table is (_show_track_table), never through a second hover gate.
While it shows, every curve is dimmed by the Highlight's pen work (HighlightMixin).
"""

from html import escape
from typing import List, NamedTuple, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtCore import QPointF, Qt

from core.cursor_config import DEFAULT_TRACK_TABLE_FIELDS, CursorConfig
from gui.workspace.graph_overlay import GraphOverlay
from gui.workspace.plot_area import GRAPH_TOKENS
from core.axis_projections import AxisScreenRule
from view_models.track_cursor import (
    TrackCurves,
    TrackCursorState,
    TrackTable,
    build_track_curves,
    build_track_table,
    resolve_track_value,
)

# The table's distance from the ViewBox's top right corner, in pixels.
_TABLE_MARGIN_PX = 12
# The cellpadding of the table's HTML, in pixels.
_CELL_PADDING_PX = 2
# Horizontal padding of a cell: the gap between two columns is twice this.
_CELL_SIDE_PX = 7
# How often a measured table may still give up a row or a column to fit.
_FIT_ATTEMPTS = 4
# A Track cursor highlight dot is this much wider than its curve's pen, and never smaller
# than _DOT_MIN_PX, in pixels. No outline or halo: the OpenGL viewport ignores alpha (§1.163).
_DOT_EXTRA_PX = 4
_DOT_MIN_PX = 10
# Above every curve and the line (998), under the table (1001).
_DOT_Z = 999


class TrackDot(NamedTuple):
    """One Track cursor highlight dot: coordinates on its ViewBox (the right Y axis one when
    ``right_axis``), the curve's colour name and the diameter in px."""

    x: float
    y: float
    color: str
    size: float
    right_axis: bool


class TrackCursorMixin:
    """The Track cursor's line and table, mixed into GraphDock."""

    def _init_track_cursor(self) -> None:
        """Called at the end of init_ui, after ``_init_cursor`` (its hover gate takes our step)."""
        self._track_state = TrackCursorState()
        self._track_curves: Optional[TrackCurves] = None
        # Track cursor Settings' Auto apply preview: (fields, opacity %) shown instead of the saved ones.
        self._track_preview: Optional[Tuple[CursorConfig, Optional[int]]] = None
        self._track_placing = False
        vb = self.plot_widget.plotItem.vb
        colour = GRAPH_TOKENS.cursor_box_line
        # Thicker under the mouse only while pinned, where it says "drag me".
        self._track_pen = pg.mkPen(color=colour, width=1)
        self._track_hover_pen = pg.mkPen(color=colour, width=3)
        self._track_line = pg.InfiniteLine(
            angle=90, movable=True, pen=self._track_pen, hoverPen=self._track_hover_pen)
        self._track_line.setZValue(998)
        self._track_line_buttons = self._track_line.acceptedMouseButtons()
        self._track_line.hide()
        self._track_line.sigPositionChanged.connect(self._on_track_line_moved)
        self._track_table = GraphOverlay(
            vb, z_value=1001, anchor=(1, 0), color=colour, fill=self._track_table_brush())
        self._track_table.set_draggable(True)
        # Where the table was last put; a different pos() means the user dragged it.
        self._track_table_placed: Optional[QPointF] = None
        self._track_table_dragged = False
        vb.sigResized.connect(self._on_track_view_resized)
        # The Track cursor highlight's dots, one item per ViewBox; the right one joins its ViewBox when it exists.
        self._track_dots = {axis: self._new_track_dots() for axis in ("primary", "secondary")}
        self._track_dots_shown: List[TrackDot] = []
        self._add_hover_step(self._hover_track_cursor)

    @staticmethod
    def _new_track_dots() -> pg.ScatterPlotItem:
        item = pg.ScatterPlotItem(pen=None, symbol="o", pxMode=True)
        item.setZValue(_DOT_Z)
        # The dots sit on the line: a click or drag there belongs to the line.
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setAcceptHoverEvents(False)
        item.hide()
        return item

    def _track_table_brush(self):
        """The box fill of the Graph theme at the opacity chosen in Track cursor Settings."""
        percent = getattr(self.app_context, "track_table_opacity", None)
        if self._track_preview is not None and self._track_preview[1] is not None:
            percent = self._track_preview[1]
        r, g, b, alpha = GRAPH_TOKENS.cursor_box_fill
        if isinstance(percent, int):
            alpha = int(percent * 255 / 100 + 0.5)
        return pg.mkBrush(r, g, b, alpha)

    def _track_cursor_enabled(self) -> bool:
        return bool(getattr(self.app_context, "track_cursor_enabled", False))

    def _track_cursor_pinned(self) -> bool:
        return bool(getattr(self.app_context, "track_cursor_pinned", True))

    def _track_cursor_highlight_enabled(self) -> bool:
        return bool(getattr(self.app_context, "track_cursor_highlight_enabled", False))

    def set_track_preview(self, config: Optional[CursorConfig], opacity: Optional[int] = None) -> None:
        """Show ``config`` and ``opacity`` (%) in place of the saved Track cursor Settings; None puts the saved ones back."""
        self._track_preview = None if config is None else (config, opacity)
        self.refresh_track_cursor()

    def _track_cursor_config(self) -> CursorConfig:
        if self._track_preview is not None:
            return self._track_preview[0]
        return getattr(self.app_context, "track_cursor_config", None) or CursorConfig(DEFAULT_TRACK_TABLE_FIELDS)

    def _track_axis(self) -> AxisScreenRule:
        # The line has no setLogMode: it is placed through the graph's X screen rule
        # (§1.276), and GraphDock.apply_logarithmic_axes refreshes it on a log X switch.
        return self.x_screen_rule()

    def track_line_value(self) -> Optional[float]:
        """The line's X on the ViewBox (drawn unit), or None while it is not shown."""
        return float(self._track_line.value()) if self._track_line.isVisible() else None

    def track_table_text(self) -> str:
        """The Track table as plain text, or "" while it is not shown."""
        return self._track_table.textItem.toPlainText() if self._track_table.isVisible() else ""

    def track_cursor_highlight_dots(self) -> List[TrackDot]:
        """The Track cursor highlight's dots on screen, in legend order; [] while none is shown."""
        return list(self._track_dots_shown)

    def refresh_track_cursor_highlight(self) -> None:
        """Follow the Track cursor highlight switch: put or take away the dots; line and table stay as they are."""
        self._show_track_dots()

    def refresh_track_cursor(self) -> None:
        """Follow the global switch and the drawn curves: show, move or hide the line and table.

        Called on every redraw of the graph and when the switch flips. Switching
        off or emptying the graph forgets the place, so the line comes back in
        the middle; a Trace filter that hides every curve only hides the line.
        """
        if not self._track_cursor_enabled():
            self._track_state.forget()
            self._track_table_placed = None
            self._track_table_dragged = False
            self._hide_track_cursor()
            return
        model = self.curves.model
        if model is None or not model.traces:
            self._track_state.forget()
            self._hide_track_cursor()
            return
        traces = self.visible_traces()
        if not traces:
            self._hide_track_cursor()
            return
        # Metadata, columns and units are taken here, once per redraw; a move of the line only interpolates.
        self._track_curves = build_track_curves(
            traces, self._track_cursor_config(), metadata_reader=self._read_trace_metadata,
            x_scale=self._x_axis.scale, x_unit=self._x_axis.unit, x_quantity=model.x_domain,
            prefs=self._unit_preferences())
        vb = self.plot_widget.plotItem.vb
        # A first curve's auto-range is still pending: settle it so the middle is the middle on screen.
        vb.prepareForPaint()
        axis = self._track_axis()
        x = self._track_state.place(model.x_domain, axis, tuple(vb.viewRange()[0]))
        if self._track_line not in self.plot_widget.plotItem.items:
            # plot_widget.clear() takes every item away on a full redraw.
            self.plot_widget.addItem(self._track_line, ignoreBounds=True)
        self._track_placing = True
        try:
            self._track_line.setValue(axis.to_screen(x))
        finally:
            self._track_placing = False
        self.apply_track_cursor_pin()
        self._track_line.show()
        self._show_track_table()

    def apply_track_cursor_pin(self) -> None:
        """Follow the Track cursor pin; the line keeps its place and the table is left as it is.

        Pinned: the line is dragged and thickens under the mouse. Unpinned: it
        takes no mouse button, does not thicken and follows the hover gate.
        """
        pinned = self._track_cursor_pinned()
        self._track_line.setMovable(pinned)
        self._track_line.setAcceptedMouseButtons(self._track_line_buttons if pinned else Qt.MouseButton.NoButton)
        self._track_line.setHoverPen(self._track_hover_pen if pinned else self._track_pen)

    def _hover_track_cursor(self, vb, scene_pos, *, in_bounds: bool, button_pressed: bool) -> None:
        """One step of CursorMixin's hover gate: an unpinned line goes to the mouse's X.

        It stands while a button is pressed and stays where it is once the mouse
        is off the graph; flipping the pin moves nothing until the next move here.
        """
        if not in_bounds or button_pressed or self._track_cursor_pinned() or not self._track_line.isVisible():
            return
        # sigPositionChanged reads the new X into the table (_on_track_line_moved).
        self._track_line.setValue(float(vb.mapSceneToView(scene_pos).x()))

    def _hide_track_cursor(self) -> None:
        self._track_curves = None
        self._track_line.hide()
        self._track_table.hide()
        self._show_track_dots()

    def _on_track_line_moved(self, line: pg.InfiniteLine) -> None:
        if self._track_placing or not self._track_line.isVisible():
            return
        self._track_state.move_to(float(line.value()), self._track_axis())
        self._show_track_table()

    def _on_track_view_resized(self, *_args) -> None:
        if self._track_table.isVisible():
            self._show_track_table()

    def _show_track_table(self) -> None:
        # The fit is measured from the font first, then checked on the laid-out table.
        # Only the rows that fit are built and laid out: a move costs the same at 20 or 200 curves.
        self._track_table.fill = self._track_table_brush()
        self._track_table.update()  # setHtml repaints nothing when only the fill changed
        max_rows: Optional[int] = self._track_rows_that_fit()
        max_columns: Optional[int] = None
        table = self._build_track_table(max_rows, max_columns)
        fit = self._track_columns_that_fit(table)
        if fit < len(table.header):
            max_columns = fit
            table = self._build_track_table(max_rows, max_columns)
        self._track_table.setHtml(self._track_table_html(table))
        width, height = self._track_room()
        for _ in range(_FIT_ATTEMPTS):
            rect = self._track_table.boundingRect()
            lines, columns = len(table.rows) + (1 if table.more_rows else 0), len(table.header)
            # The table keeps at least one curve row (build_track_table).
            too_tall = rect.height() > height and len(table.rows) > 1
            too_wide = rect.width() > width and columns > 1
            if not (too_tall or too_wide):
                break
            if too_tall:
                max_rows = lines - 1
            if too_wide:
                max_columns = columns - 1
            table = self._build_track_table(max_rows, max_columns)
            self._track_table.setHtml(self._track_table_html(table))
        self._place_track_table()
        self._track_table.show()
        self._show_track_dots()

    def _show_track_dots(self) -> None:
        """A dot where the line crosses each drawn curve while the Track cursor highlight is on; else none.

        Placed through the graph's screen rules (§1.276), so log axes and the X
        axis unit need nothing of their own; a right Y axis curve goes on its ViewBox.
        While it shows, the Highlight's pen work dims every curve (set_track_cursor_dimming),
        also one the line does not cross; the dots never dim.
        """
        dots: List[TrackDot] = []
        x = self._track_state.x
        showing = (self._track_cursor_highlight_enabled() and self._track_curves is not None and x is not None
                   and self._track_line.isVisible())
        if showing:
            screen_x = self._track_axis().to_screen(x)
            y_rule = self.y_screen_rule()
            for curve in self._track_curves.curves:
                value = resolve_track_value(curve, x)
                if value is None:
                    continue
                screen_y = y_rule.to_screen(value)
                if not np.isfinite(screen_y):
                    continue  # no place on a Logarithmic Y axis
                pen = self._curve_pen(curve.trace)
                dots.append(TrackDot(
                    float(screen_x), float(screen_y), pen.color().name(),
                    max(pen.widthF() + _DOT_EXTRA_PX, _DOT_MIN_PX), curve.trace.axis == "secondary"))
        views = {"primary": self.plot_widget.plotItem.vb, "secondary": self.secondary_axis.view_box}
        shown: List[TrackDot] = []
        for axis, item in self._track_dots.items():
            vb = views[axis]
            group = [dot for dot in dots if dot.right_axis == (axis == "secondary")]
            if vb is None or not group:
                item.hide()
                continue
            if item.parentItem() is not vb.childGroup:
                # Straight onto the ViewBox, outside the auto-range: PlotItem.addItem would count
                # the dots as a data curve. A redraw's new right ViewBox takes them again here.
                vb.addItem(item, ignoreBounds=True)
            item.setData(x=[dot.x for dot in group], y=[dot.y for dot in group],
                         size=[dot.size for dot in group],
                         brush=[pg.mkBrush(dot.color) for dot in group], pen=None)
            item.show()
            shown += group
        self._track_dots_shown = shown
        # Compared there with the last look, so a move of the line touches no pen.
        self.set_track_cursor_dimming(showing)

    def _build_track_table(self, max_rows: Optional[int], max_columns: Optional[int]) -> TrackTable:
        return build_track_table(
            self._track_curves, self._track_state.x, max_rows=max_rows, max_columns=max_columns)

    def _track_room(self) -> Tuple[float, float]:
        """The width and height the table may take inside the ViewBox, in pixels."""
        vb = self.plot_widget.plotItem.vb
        return vb.width() - 2 * _TABLE_MARGIN_PX, vb.height() - 2 * _TABLE_MARGIN_PX

    def _track_metrics(self, *, bold: bool = False) -> QFontMetricsF:
        font = QFont(self._track_table.textItem.font())
        font.setBold(bold)
        return QFontMetricsF(font)

    def _track_rows_that_fit(self) -> int:
        line = self._track_metrics().height()
        row = line + 2 * _CELL_PADDING_PX
        margin = 2 * self._track_table.textItem.document().documentMargin()
        # The X line and the header row come first.
        free = self._track_room()[1] - margin - line - row
        return max(int(free // row), 1)

    def _track_columns_that_fit(self, table: TrackTable) -> int:
        plain, bold = self._track_metrics(), self._track_metrics(bold=True)
        pad = 2 * _CELL_SIDE_PX
        free = (self._track_room()[0] - 2 * self._track_table.textItem.document().documentMargin()
                - plain.horizontalAdvance("\u25a0") - pad)
        widths = [
            max([bold.horizontalAdvance(label)] + [plain.horizontalAdvance(row.cells[c]) for row in table.rows]) + pad
            for c, label in enumerate(table.header)
        ]
        if sum(widths) <= free:
            return len(widths)
        # "+N columns" needs its own room at the end of the header.
        free -= plain.horizontalAdvance(f"+{len(widths)} columns") + pad
        fit, used = 0, 0.0
        for width in widths:
            if used + width > free:
                break
            fit, used = fit + 1, used + width
        return max(fit, 1)

    def _track_table_html(self, table: TrackTable) -> str:
        label, text = table.x_line
        # The axis colour reads on the box fill of both Graph themes.
        muted = GRAPH_TOKENS.axis
        pad = f"padding:{_CELL_PADDING_PX}px {_CELL_SIDE_PX}px;"
        head = "".join(f"<th align='center' style='{pad}'>{escape(name)}</th>" for name in table.header)
        if table.more_columns:
            head += f"<th align='center' style='{pad}color:{muted}; font-weight:normal'>{escape(table.more_columns)}</th>"
        rule = f"border-top:1px solid {muted};"
        rows = []
        for index, row in enumerate(table.rows):
            # A rule over the right Y axis group: its values have another unit.
            top = rule if index == table.right_axis_from else ""
            swatch = self._curve_pen(row.trace).color().name()
            cells = "".join(f"<td align='center' style='{pad}{top}'>{escape(cell)}</td>" for cell in row.cells)
            rows.append(f"<tr><td style='{pad}{top}color:{swatch}'>&#9632;</td>{cells}</tr>")
        if table.more_rows:
            span = max(len(table.header), 1)
            rows.append(f"<tr><td></td><td colspan='{span}' style='color:{muted}'>{escape(table.more_rows)}</td></tr>")
        return (f"<div><b>{escape(label)}: {escape(text)}</b></div>"
                f"<table cellspacing='0' cellpadding='0'><tr><th style='{pad}'></th>{head}</tr>"
                f"{''.join(rows)}</table>")

    def _place_track_table(self, *_args) -> None:
        """Top right, or where the user dragged it; either way kept inside the ViewBox."""
        vb = self.plot_widget.plotItem.vb
        table = self._track_table
        if self._track_table_placed is not None and table.pos() != self._track_table_placed:
            self._track_table_dragged = True
        if self._track_table_dragged:
            x, y = table.pos().x(), table.pos().y()
        else:
            x, y = vb.width() - _TABLE_MARGIN_PX, _TABLE_MARGIN_PX
        # The anchor is the top right corner.
        rect = table.boundingRect()
        x = min(max(x, rect.width()), vb.width())
        y = max(min(y, vb.height() - rect.height()), 0.0)
        table.setPos(x, y)
        self._track_table_placed = table.pos()
