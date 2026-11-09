# =====================================================================
# FILE: gui/dialogs/restore_defaults.py
# =====================================================================
"""
Restore Defaults for a settings dialog: one button, one meaning.

The button puts every control of the window back to its default -- what the
window shows, nothing more. Nothing is saved until OK; Cancel throws the restored
values away like any other edit. What "default" means is the dialog's business:
it passes a `restore` callable that resets its own controls.

Usage:

    from gui.dialogs.restore_defaults import add_restore_defaults_button

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    add_restore_defaults_button(buttons, self.restore_defaults)
"""
from typing import Callable

from PySide6.QtWidgets import QDialogButtonBox, QPushButton

RESTORE_DEFAULTS_TOOLTIP = ("Put every setting of this window back to its default. "
                            "Nothing is saved until OK; Cancel keeps the current settings.")


def add_restore_defaults_button(buttons: QDialogButtonBox, restore: Callable[[], None]) -> QPushButton:
    """Add the Restore Defaults button to `buttons` (the platform puts it apart from OK / Cancel); a click calls `restore`."""
    button = buttons.addButton(QDialogButtonBox.StandardButton.RestoreDefaults)
    button.setToolTip(RESTORE_DEFAULTS_TOOLTIP)
    button.setAutoDefault(False)   # Enter still means OK, never a reset
    button.clicked.connect(lambda _checked=False: restore())
    return button
