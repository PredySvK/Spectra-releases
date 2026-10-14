# gui/bottom_panels/log_widget.py
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit
from gui.appearance import APP_TOKENS


class LogWidget(QPlainTextEdit):
    """
    Read-only system log panel that displays status notifications,
    file ingestion statistics, and diagnostic messages.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        self.setReadOnly(True)
        # No fixed height: the widget lives in the bottom panel, whose height the
        # user drags via the splitter above it. A floor keeps it usable when
        # dragged small.
        self.setMinimumHeight(60)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet("""
            QPlainTextEdit {
                background-color: %s;
                color: %s;
                border: 1px solid %s;
            }
        """ % (APP_TOKENS.log_background, APP_TOKENS.log_text, APP_TOKENS.log_border))
        self.setFont(QFont("Consolas", 9))

    def log_message(self, message: str):
        """Appends a timestamped text log line and auto-scrolls to the end."""
        timestamp = datetime.now().strftime("%H:%M")
        self.appendPlainText(f"{timestamp}: {message}")
        self.moveCursor(QTextCursor.End)












