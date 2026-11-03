# =====================================================================
# FILE: gui/ribbon/save_section.py
# =====================================================================
"""
The "Batch" group every analysis ribbon tab ends with: one big button that
opens the "Compute Result Set" dialog (gui/dialogs/compute_result_set_dialog.py,
ARCHITECTURE_DECISIONS §1.6).

The button used to be a whole inline section -- channel-type combo,
All/Selected switch, a "Choose..." dialog, plus a second "Input Data..."
button -- crammed into the ribbon's fixed height, where the lower half was
clipped off. All of that moved into the dialog, and the dialog's answer goes
to the batch as a value (#770). What stays here is the button, a one-line
status label under it.

`settings_prefix` ("order" / "spec1d" / "spec2d") keys the QSettings entries so
each tab keeps its own remembered choice -- under the key it already used,
because a renamed key silently resets a preference set months ago.

Lives beside ribbon_widgets.py because it is the same sort of thing: a shared
building block of the ribbon.
"""
from typing import Optional

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.ribbon.ribbon_widgets import _STACK_SIZE, make_ribbon_button


class ComputeResultSetButton(QWidget):
    """
    The ribbon's "Compute Result Set..." button plus its status line.

    A plain QWidget wrapper so the tab can give it stretch 0 in its group and
    have it keep its natural width.
    """

    def __init__(self, settings_prefix: str, app_context, *, tooltip: str = "",
                 extra_orders: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("ComputeBatchButton")  # Help figure target
        self.app_context = app_context
        self.settings = getattr(app_context, "settings", None) if app_context else None
        self._settings_prefix = settings_prefix
        self.extra_orders = extra_orders

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        self.button = make_ribbon_button(
            "Compute Batch", "compute", kind="commit",
            tooltip=tooltip or "Compute this analysis across a folder or a saved "
                               "query and save it as a result set",
        )
        self.button.setFixedSize(_STACK_SIZE)
        column.addWidget(self.button)

        self.status = QLabel("")
        self.status.setStyleSheet("color: palette(placeholder-text); font-size: 10px;")
        self.status.setWordWrap(True)
        self.status.hide()  # shown only while it has text, so the button stacks flush under Refresh
        column.addWidget(self.status)

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))
