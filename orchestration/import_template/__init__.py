"""
orchestration.import_template -- the import wizard's background work, in order.

- TemplateWizardJobs: the import wizard's background work on the `JobRunner` port
  (#1028) -- reads the samples and the first one's folder, the files added later,
  the samples again when the text format changes, and previews every sample; it
  opens a template for editing, looks for duplicate curves and says which ending
  action can be used (`resolve_action_problems`). It keeps every result with the
  question it answers, so one rule says what still holds (`is_preview_current`).
  Why Next is off is `resolve_step_problem`; `on_change` gets one of the
  `SAMPLES_*` kinds.

What does NOT belong here: the wizard's state and the preview's computation
(view_models/import_template), reading the sample (io_modules/import_template),
the widgets and the preview's delay while typing (gui/dialogs/import_template_wizard).
"""

from orchestration.import_template._wizard_jobs import (
    SAMPLES_CHANGED,
    SAMPLES_CHOICE,
    SAMPLES_DUPLICATES,
    SAMPLES_MESSAGE,
    SAMPLES_OPENED,
    SAMPLES_PREVIEW,
    SAMPLES_ROLES,
    TemplateWizardJobs,
)

__all__ = [
    "SAMPLES_CHANGED",
    "SAMPLES_CHOICE",
    "SAMPLES_DUPLICATES",
    "SAMPLES_MESSAGE",
    "SAMPLES_OPENED",
    "SAMPLES_PREVIEW",
    "SAMPLES_ROLES",
    "TemplateWizardJobs",
]
