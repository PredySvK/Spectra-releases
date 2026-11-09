# =====================================================================
# FILE: gui/dialogs/auto_apply.py
# =====================================================================
"""
Auto apply for a dialog that previews its edits on the graphs.

One checkbox, remembered across starts, on by default. While it is ticked the
dialog calls its own preview after every edit; ticking it mid-dialog catches the
graphs up to what is already edited, unticking leaves the last preview in place.
What a preview is, and how Cancel takes it back, is the caller's business -- the
dialog only decides *when* to preview.

Usage:

    self._auto_apply_check = make_auto_apply_check(settings, "my_dialog/auto_apply", tooltip, self._notify_live)
    button_row.addWidget(self._auto_apply_check)
"""
from typing import Callable

from PySide6.QtWidgets import QCheckBox


def read_auto_apply(settings, key: str) -> bool:
    """The remembered Auto apply state under `key`, defaulting on."""
    if settings is None:
        return True
    return settings.value(key, True, type=bool)


def make_auto_apply_check(settings, key: str, tooltip: str, catch_up: Callable[[], None]) -> QCheckBox:
    """The "Auto apply" checkbox: remembers its state under `key` and calls `catch_up` when ticked."""
    check = QCheckBox("Auto apply")
    check.setToolTip(tooltip)
    check.setChecked(read_auto_apply(settings, key))

    def on_toggled(checked: bool) -> None:
        if settings is not None:
            settings.setValue(key, checked)
        if checked:
            catch_up()

    check.toggled.connect(on_toggled)
    return check
