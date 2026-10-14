"""Neutral canvas colours and inherited application styling for Workflow."""
from PySide6.QtWidgets import QWidget

from gui.appearance import APP_TOKENS



def apply_workflow_style(widget: QWidget) -> None:
    """Keep standard controls on the application theme, like the Explorer.

    Only captions and semantic status colours are specific to Workflow. Fonts,
    backgrounds, frames, tabs, buttons and selection inherit the Qt app style.
    """
    widget.setStyleSheet(f"""
        QLabel[workflowCaption="true"] {{ color: palette(placeholder-text); font-weight: bold; }}
        QLabel[workflowStatus="ready"] {{ color: {APP_TOKENS.workflow_ready}; }}
        QLabel[workflowStatus="not_ready"], QLabel[workflowError="true"] {{ color: {APP_TOKENS.workflow_error}; }}
    """)
