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
clipped off. All of that moved into the dialog. What stays here is:

  * the button and a one-line status label under it, and
  * the channel scope as *values*, read back from QSettings (the dialog is
    what writes them). `batch_run.py` still asks this object
    `get_save_channel_types()` / `is_save_mode_all_channels()` /
    `selected_channel_identities()`; it just no longer holds live widgets.

`settings_prefix` ("order" / "spec1d" / "spec2d") keys the QSettings entries so
each tab keeps its own remembered choice -- under the key it already used,
because a renamed key silently resets a preference set months ago.

Lives beside ribbon_widgets.py because it is the same sort of thing: a shared
building block of the ribbon.
"""
from typing import Optional, Set

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.ribbon.ribbon_widgets import _STACK_SIZE, make_ribbon_button

# What the "Channels:" choice maps to, both for filtering and for detecting an
# "all channels" selection. One dictionary, not one per tab.
SAVE_CHANNEL_TYPE_OPTIONS = {
    "Acceleration": {"accelerometer"},
    "Sound": {"microphone"},
    "Acceleration + Sound": {"accelerometer", "microphone"},
}

_DEFAULT_CHANNEL_TYPE = "Acceleration"
_FALLBACK_TYPES = {"accelerometer"}
_IDENTITY_SEP = "\x1f"  # base <sep> direction, inside one QSettings list entry


def identities_to_settings(identities) -> list:
    out = []
    for base, direction in identities:
        out.append(f"{base}{_IDENTITY_SEP}{'' if direction is None else direction}")
    return sorted(out)


def identities_from_settings(raw) -> set:
    result = set()
    for entry in raw or []:
        base, _, direction = str(entry).partition(_IDENTITY_SEP)
        result.add((base, direction or None))
    return result


def read_selected_identities(settings, settings_prefix) -> set:
    """Load the batch channel-identity scope from QSettings.

    One home: the same read lived on the ribbon button and in the Compute
    Result Set dialog, comment and all, and a logic change in one copy (the
    one-item-list collapse below) would have silently skipped the other.
    """
    if not settings:
        return set()
    raw = settings.value(f"{settings_prefix}_save_selected_identities", [])
    if isinstance(raw, str):  # QSettings collapses a one-item list to a bare str
        raw = [raw]
    return identities_from_settings(raw)


class ComputeResultSetButton(QWidget):
    """
    The ribbon's "Compute Result Set..." button plus its status line, and the
    batch's channel scope as QSettings-backed values.

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
        self.status.setStyleSheet("color: #9aa0a6; font-size: 10px;")
        self.status.setWordWrap(True)
        self.status.hide()  # shown only while it has text, so the button stacks flush under Refresh
        column.addWidget(self.status)

    # ---- what BatchRunHandler asks ----------------------------------

    def get_save_channel_types(self) -> Set[str]:
        return set(SAVE_CHANNEL_TYPE_OPTIONS.get(
            self._get_val("save_channel_type", _DEFAULT_CHANNEL_TYPE), _FALLBACK_TYPES
        ))

    def is_save_mode_all_channels(self) -> bool:
        return self._get_val("save_channel_mode", "all") != "selected"

    def selected_channel_identities(self) -> set:
        return read_selected_identities(self.settings, self._settings_prefix)

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    # ---- QSettings -------------------------------------------------------

    def _get_val(self, suffix: str, default):
        if self.settings:
            return str(self.settings.value(f"{self._settings_prefix}_{suffix}", default))
        return default
