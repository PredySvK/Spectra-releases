# =====================================================================
# FILE: gui/ribbon/ribbon_widgets.py
# =====================================================================
"""
Shared building blocks for the ribbon, so every tab reads as one system:
Excel/SpaceClaim-style groups separated by a rule and captioned underneath,
and buttons that are an icon over (or beside) a short label rather than a bare
word.

Two things every ribbon control funnels through here:

  * `make_ribbon_button` -- one button factory with a fixed vocabulary of
    `kind`s (primary / commit / neutral / danger). Colour means the same thing
    on every tab; no tab writes its own setStyleSheet.
  * `RibbonGroup` -- a captioned box. A tab is a row of these plus separators.

`tooltip` is a first-class argument on both: the visible label stays short and
scannable, the sentence that explains what the control actually does lives in
the hover tooltip (styled dark to match, see RIBBON_TOOLTIP_QSS).
"""
from typing import Iterable, Optional, Union

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QMenu, QSizePolicy, QSpinBox,
    QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from gui.ribbon.icons import ribbon_icon

# Dark tooltip so the hover text does not flash a white box over the ribbon.
# Applied once by RibbonBar; kept here next to the widgets it describes.
RIBBON_TOOLTIP_QSS = (
    "QToolTip {"
    "  background-color: #1f1f1f; color: #e6e6e6;"
    "  border: 1px solid #555555; padding: 4px 6px;"
    "}"
)

# kind -> (background, hover background, text colour, border colour)
_KIND = {
    "primary": ("#33465c", "#3f566f", "#ffffff", "transparent"),
    "commit":  ("#4a4366", "#585078", "#ffffff", "transparent"),
    "danger":  ("#a12d2d", "#b23a3a", "#ffffff", "transparent"),
    "neutral": ("#3c3c3c", "#474747", "#e6e6e6", "#555555"),
}

_BIG_SIZE = (94, 86)
_SMALL_HEIGHT = 28
_STACK_SIZE = QSize(144, 44)  # Refresh over Compute Batch


def _button_qss(kind: str) -> str:
    bg, hover, fg, border = _KIND.get(kind, _KIND["neutral"])
    return (
        "QToolButton {"
        f"  background-color: {bg}; color: {fg};"
        f"  border: 1px solid {border}; border-radius: 6px;"
        "  padding: 4px 8px; font-weight: bold;"
        "}"
        f"QToolButton:hover {{ background-color: {hover}; }}"
        "QToolButton:disabled { color: #808080; }"
    )


def make_ribbon_button(
    text: str,
    icon: Optional[str] = None,
    *,
    kind: str = "neutral",
    tooltip: str = "",
    big: bool = False,
    checkable: bool = False,
) -> QToolButton:
    """
    The one ribbon button. `icon` is a name in resources/icons/ribbon/.

    `big` = icon over label on a fixed square footprint (the lead action of a
    group). Otherwise = icon beside label, 38px tall, width follows the text
    (the stacked secondary actions on Project/Settings).
    """
    button = QToolButton()
    button.setText(text)
    button.setCheckable(checkable)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    on_accent = kind != "neutral"

    if big:
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setFixedSize(*_BIG_SIZE)
        if icon:
            button.setIcon(ribbon_icon(icon, on_accent=on_accent, size=24))
            button.setIconSize(QSize(22, 22))
    else:
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setMinimumHeight(_SMALL_HEIGHT)
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if icon:
            button.setIcon(ribbon_icon(icon, on_accent=on_accent, size=16))
            button.setIconSize(QSize(16, 16))

    button.setStyleSheet(_button_qss(kind))
    if tooltip:
        button.setToolTip(tooltip)
    return button


def make_refresh_button(tooltip: str = "") -> QToolButton:
    """The 'recompute this tab' action every analysis tab leads with."""
    button = make_ribbon_button(
        "Refresh", "refresh", kind="primary",
        tooltip=tooltip or "Recompute what this tab is showing",
    )
    button.setFixedSize(_STACK_SIZE)
    button.setObjectName("RefreshButton")  # Help figure target, as are the names below
    return button


class RefreshSplitButton(QToolButton):
    """The "recompute this tab" action, with a dropdown for a narrower recompute.

    Clicking the button itself behaves exactly like the plain Refresh button
    (`clicked`, unchanged -- every existing `.btn_recalculate.clicked.connect(...)`
    keeps working with no call-site change): it recomputes every curve on the
    dock with the ribbon's current config, which the existing Refresh already
    did (`_restore_pending_overlays` re-drops every overlay through the
    current DSP config on every refresh) -- "Refresh All" needed no new
    compute path, just this dropdown next to it.

    The arrow opens a menu with the one new action this button adds: recompute
    only the last N curves (by the order they were added to the graph), N
    picked with the spinbox beside "Go" (ideas/session_persistence/PLAN.md S8).
    """

    refresh_last_n_requested = Signal(int)

    def __init__(self, tooltip: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("RefreshButton")
        self.setText("Refresh")
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setFixedSize(_STACK_SIZE)
        self.setIcon(ribbon_icon("refresh", on_accent=True, size=16))
        self.setIconSize(QSize(16, 16))
        self.setStyleSheet(_button_qss("primary"))
        self.setToolTip(tooltip or "Recompute what this tab is showing")
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

        menu = QMenu(self)
        row = QWidget(menu)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(6)
        row_layout.addWidget(QLabel("Refresh Last"))
        self.spin_last_n = QSpinBox()
        self.spin_last_n.setRange(1, 99)
        self.spin_last_n.setValue(1)
        self.spin_last_n.setToolTip(
            "How many of the most recently added curves to recompute, oldest to "
            "the base curve excluded once fewer than this many overlays exist -- "
            "then it is the same as Refresh."
        )
        row_layout.addWidget(self.spin_last_n)
        btn_go = make_ribbon_button("Go", kind="neutral", tooltip="Recompute just those curves")
        btn_go.setFixedSize(QSize(40, 24))
        btn_go.clicked.connect(self._emit_last_n)
        row_layout.addWidget(btn_go)

        widget_action = QWidgetAction(menu)
        widget_action.setDefaultWidget(row)
        menu.addAction(widget_action)
        self.setMenu(menu)

    def _emit_last_n(self):
        self.menu().close()
        self.refresh_last_n_requested.emit(self.spin_last_n.value())


def make_refresh_split_button(tooltip: str = "") -> RefreshSplitButton:
    """Refresh, plus a dropdown to recompute only the last N added curves."""
    return RefreshSplitButton(tooltip)


def stack_buttons(*widgets: QWidget) -> QWidget:
    """Rectangular ribbon buttons one above the other (Refresh over Compute Batch)."""
    column = QWidget()
    box = QVBoxLayout(column)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)
    for widget in widgets:
        box.addWidget(widget)
    return column


def make_help_button(topic: str, owner: QWidget) -> QToolButton:
    """The Help action every analysis tab carries, far right."""
    from gui.help import show_help

    button = make_ribbon_button(
        "Help", "help", kind="neutral", big=True,
        tooltip="Open the help page for this tab",
    )
    button.clicked.connect(lambda: show_help(topic, owner))
    return button


def vertical_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    line.setStyleSheet("color: #4a4a4a;")
    return line


def _field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("color: #b8b8b8; font-size: 11px;")
    return label


class RibbonGroup(QWidget):
    """
    A captioned group of controls: content on top, a centred grey caption
    underneath, the way Office and SpaceClaim label a ribbon section.

    `body` is the horizontal layout the content sits in -- add widgets or
    sub-layouts straight to it for a custom arrangement, or use the helpers:
    `add_fields` for label-over-control columns, `add_column` for a stack of
    checkboxes or small buttons.
    """

    def __init__(self, title: str, *, tooltip: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("RibbonGroup" + title.replace(" ", ""))
        column = QVBoxLayout(self)
        column.setContentsMargins(6, 2, 6, 1)
        column.setSpacing(2)

        content = QWidget()
        self.body = QHBoxLayout(content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        column.addWidget(content, 1)

        caption = QLabel(title)
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        caption.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        column.addWidget(caption)

        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        if tooltip:
            self.setToolTip(tooltip)

    def add(self, item: Union[QWidget, QLayout]) -> "RibbonGroup":
        if isinstance(item, QLayout):
            self.body.addLayout(item)
        else:
            self.body.addWidget(item)
        return self

    def add_fields(self, pairs: Iterable, *, rows_per_col: int = 2) -> "RibbonGroup":
        """
        `pairs` is (label, widget) tuples laid out label-over-widget, filling
        each column top to bottom before starting the next. An empty label
        leaves the slot blank (a checkbox that is its own label).
        """
        columns = []
        col: Optional[QVBoxLayout] = None
        for index, (label, widget) in enumerate(pairs):
            if index % rows_per_col == 0:
                col = QVBoxLayout()
                col.setSpacing(1)
                columns.append(col)
                self.body.addLayout(col)
            if index % rows_per_col != 0:
                col.addSpacing(3)
            col.addWidget(_field_label(label or " "))
            col.addWidget(widget)
        # Top-align every column so a shorter one does not float to the middle.
        for column in columns:
            column.addStretch()
        return self

    def add_column(self, *widgets: QWidget, spacing: int = 6) -> "RibbonGroup":
        column = QVBoxLayout()
        column.setSpacing(spacing)
        for widget in widgets:
            column.addWidget(widget)
        column.addStretch()
        self.body.addLayout(column)
        return self


def build_tab_layout(widget: QWidget, content_layout: QHBoxLayout, help_topic: str) -> None:
    """
    Finish a ribbon tab: push everything left, then a Help group on the far
    right, and install the layout.

    The bar has room for one row of RibbonGroups (RibbonBar pins the height);
    a group's caption sits inside that row, it does not add a second one.
    """
    content_layout.addStretch()
    help_group = RibbonGroup("Help")
    help_group.add(make_help_button(help_topic, widget))
    content_layout.addWidget(help_group)
    widget.setLayout(content_layout)
