"""
orchestration.import_template -- the import wizard's background work, in order (Floor 2).

- WizardJobs: reads the wizard's sample (and again when its text format changes),
  previews the template, checks further sample files and looks for duplicate curves,
  each on the `JobRunner` port. It keeps every result with the question it answers,
  so one rule says what still holds (`is_preview_current`, `duplicate_groups`) and
  which ending action can be used now (`resolve_action_problems`). `on_change` gets
  one of the `CHANGE_*` kinds.

What does NOT belong here: the wizard's state and the preview's computation
(view_models/import_template), reading the sample (io_modules/import_template),
the widgets and the preview's delay while typing (gui/dialogs/import_template_wizard).
"""

from orchestration.import_template._wizard_jobs import (
    CHANGE_DUPLICATES,
    CHANGE_FITS,
    CHANGE_MESSAGE,
    CHANGE_OPENED,
    CHANGE_PREVIEW,
    CHANGE_REWRITTEN,
    CHANGE_TEMPLATE,
    CHANGE_WORKBOOK,
    WizardJobs,
)

__all__ = [
    "CHANGE_DUPLICATES",
    "CHANGE_FITS",
    "CHANGE_MESSAGE",
    "CHANGE_OPENED",
    "CHANGE_PREVIEW",
    "CHANGE_REWRITTEN",
    "CHANGE_TEMPLATE",
    "CHANGE_WORKBOOK",
    "WizardJobs",
]
